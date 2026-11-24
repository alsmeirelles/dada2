"""Background-safe YOLO training on partially annotated images (spec 4.6.2).

Mode 1 keeps the images untouched and multiplies the negative classification
loss of every anchor by a validity weight: one for a matched foreground
anchor, for any anchor of an exhaustively labeled image, and for an anchor
whose centre lies in an answered region; zero elsewhere, so unqueried regions
receive an exact zero background gradient on both YOLO26 heads. Images are
letterboxed without geometric augmentation so the regions map exactly onto
the training image.

Mode 2 is the fallback for trainers whose loss cannot be changed: confident
predictions of the previous target model outside the answered regions become
temporary labels, and every other pixel outside the regions is neutralized.
"""

from pathlib import Path
from typing import Any

import numpy as np
import torch
from ultralytics import YOLO
from ultralytics.models.yolo.detect import DetectionTrainer
from ultralytics.models.yolo.segment import SegmentationTrainer
from ultralytics.nn.modules.head import Segment26
from ultralytics.nn.tasks import DetectionModel, SegmentationModel
from ultralytics.utils.loss import (
    E2ELoss,
    SegmentLoss26,
    v8DetectionLoss,
    v8SegmentationLoss,
)
from ultralytics.utils.tal import make_anchors

from dada_api.active_learning.contract import PARTIALLY_LABELED
from dada_api.active_learning.dada_al.dataset import pai_schema

NEUTRAL_PIXEL = (114, 114, 114)
PSEUDO_LABEL_CONFIDENCE = 0.80
SEED_MODULUS = 2**32


class MaskedBCE:
    """Element-wise BCE whose terms are weighted per anchor, except for the
    anchors that carry a positive target."""

    def __init__(self) -> None:
        """Start without weights."""
        self.bce = torch.nn.BCEWithLogitsLoss(reduction="none")
        self.weight: torch.Tensor | None = None

    def __call__(self, logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        """Return the weighted element-wise loss.

        Args:
            logits: Class logits of shape ``(B, A, C)``.
            targets: Target scores of the same shape.

        Returns:
            The loss of shape ``(B, A, C)``.
        """
        loss = self.bce(logits, targets)
        if self.weight is None:
            return loss
        positive = targets.sum(-1, keepdim=True) > 0
        return loss * torch.where(positive, torch.ones_like(self.weight), self.weight)


def anchor_weights(
    feats: list[torch.Tensor],
    strides: torch.Tensor,
    batch: dict[str, Any],
    regions: dict[str, list[list[float]]],
) -> torch.Tensor:
    """Return the validity weight of every anchor of a batch.

    Regions are ``xyxy`` in canonical pixels and are mapped to the training
    image with the batch's letterbox gain and padding.

    Args:
        feats: Feature maps the head received.
        strides: Head strides.
        batch: Training batch, with ``im_file`` and ``ratio_pad``.
        regions: Answered regions keyed by media id.

    Returns:
        Weights of shape ``(B, A, 1)``.
    """
    points, stride = make_anchors(feats, strides, 0.5)
    centres = points * stride
    weights = torch.ones(feats[0].shape[0], centres.shape[0], 1, device=centres.device)
    for index, file in enumerate(batch["im_file"]):
        boxes = regions.get(Path(file).stem)
        if boxes is None:
            continue
        (gain_h, gain_w), (left, top) = batch["ratio_pad"][index]
        scale = centres.new_tensor([gain_w, gain_h, gain_w, gain_h])
        shift = centres.new_tensor([left, top, left, top])
        rois = centres.new_tensor(boxes).reshape(-1, 4) * scale + shift
        inside = (
            (centres[:, None, 0] >= rois[None, :, 0])
            & (centres[:, None, 0] <= rois[None, :, 2])
            & (centres[:, None, 1] >= rois[None, :, 1])
            & (centres[:, None, 1] <= rois[None, :, 3])
        ).any(1)
        weights[index, :, 0] = inside.to(weights.dtype)
    return weights


class RegionMasking:
    """Loss mixin applying :func:`anchor_weights` to the background term."""

    def __init__(self, model: Any, tal_topk: int = 10, tal_topk2: int | None = None):
        """Build the wrapped loss and read the regions from the model."""
        super().__init__(model, tal_topk, tal_topk2)
        self.regions = model.pai_regions
        self.bce = MaskedBCE()

    def get_assigned_targets_and_loss(
        self, preds: dict[str, Any], batch: dict[str, Any], **kwargs: Any
    ) -> tuple:
        """Weight the anchors of this batch, then compute the loss."""
        self.bce.weight = anchor_weights(
            preds["feats"], self.stride, batch, self.regions
        )
        return super().get_assigned_targets_and_loss(preds, batch, **kwargs)


class PAIDetectionLoss(RegionMasking, v8DetectionLoss):
    """Detection loss with region-aware background masking."""


class PAISegmentationLoss(RegionMasking, v8SegmentationLoss):
    """YOLO11 and YOLO12 segmentation loss with region-aware masking."""


class PAISegmentLoss26(RegionMasking, SegmentLoss26):
    """YOLO26 segmentation loss with region-aware masking."""


def _dual(model: DetectionModel) -> bool:
    """Return whether the head has the YOLO26 one-to-one branch."""
    return getattr(model.model[-1], "one2one_cv2", None) is not None


class PAIDetectionModel(DetectionModel):
    """Detection model whose criterion masks unqueried background."""

    def init_criterion(self) -> Any:
        """Return the masked loss, on both heads for YOLO26."""
        return (
            E2ELoss(self, PAIDetectionLoss) if _dual(self) else PAIDetectionLoss(self)
        )


class PAISegmentationModel(SegmentationModel):
    """Segmentation model whose criterion masks unqueried background."""

    def init_criterion(self) -> Any:
        """Return the masked loss, on both heads for YOLO26."""
        loss = (
            PAISegmentLoss26
            if isinstance(self.model[-1], Segment26)
            else PAISegmentationLoss
        )
        return E2ELoss(self, loss) if _dual(self) else loss(self)


class RegionAware:
    """Trainer mixin: masked models and letterboxed, unaugmented images."""

    regions: dict[str, list[list[float]]] = {}
    model_class: type = PAIDetectionModel

    def get_model(self, cfg: Any = None, weights: Any = None, verbose: bool = True):
        """Return the task model, switched to its masked variant."""
        model = super().get_model(cfg, weights, verbose)
        model.__class__ = self.model_class
        model.pai_regions = self.regions
        return model

    def build_dataset(self, img_path: str, mode: str = "train", batch: Any = None):
        """Build the dataset; training images are only letterboxed."""
        dataset = super().build_dataset(img_path, mode, batch)
        if mode == "train":
            dataset.augment = False
            dataset.transforms = dataset.build_transforms(hyp=self.args)
        return dataset


class PAIDetectionTrainer(RegionAware, DetectionTrainer):
    """Mode 1 trainer for detection."""


class PAISegmentationTrainer(RegionAware, SegmentationTrainer):
    """Mode 1 trainer for segmentation."""

    model_class = PAISegmentationModel


def train(
    weights: str,
    data: Path,
    task: str,
    regions: dict[str, list[list[float]]],
    *,
    epochs: int,
    imgsz: int,
    batch: int,
    seed: int,
    device: str,
    output: Path,
    name: str,
) -> Path:
    """Train a YOLO model, masking unqueried background when regions exist.

    Args:
        weights: Checkpoint or model name to start from.
        data: Ultralytics dataset description.
        task: ``detection`` or ``segmentation``.
        regions: Answered regions of the partially labeled images, keyed by
            media id; empty when Mode 1 is not needed.
        epochs: Training epochs.
        imgsz: Input size.
        batch: Batch size.
        seed: Seed of the request.
        device: Torch device.
        output: Folder receiving the training run.
        name: Name of the run folder.

    Returns:
        The final checkpoint.
    """
    trainer = None
    if regions:
        base = PAISegmentationTrainer if task == "segmentation" else PAIDetectionTrainer
        trainer = type(base.__name__, (base,), {"regions": regions})
    YOLO(weights).train(
        data=str(data),
        epochs=epochs,
        imgsz=imgsz,
        batch=batch,
        seed=seed % SEED_MODULUS,
        deterministic=True,
        device=device,
        project=str(output),
        name=name,
        exist_ok=True,
        val=False,
        plots=False,
        verbose=False,
        amp=device != "cpu",
        workers=0 if device == "cpu" else 4,
        trainer=trainer,
    )
    return output / name / "weights" / "last.pt"


def neutralize(
    manifest: pai_schema.PAIManifest,
    media_root: str,
    folder: Path,
    task: str,
    teacher: Path | None,
    device: str,
) -> Path:
    """Write the Mode 2 training view of a manifest (spec 4.6.2, Mode 2).

    For each partially labeled image, predictions of the previous target
    model at 0.80 or more whose centre lies outside every answered region are
    added as temporary labels, and every pixel outside the regions and those
    boxes is set to the dataset mean ``(114, 114, 114)``. Other images are
    linked unchanged.

    Args:
        manifest: Training manifest.
        media_root: Media root of the request.
        folder: Split folder to write.
        task: ``detection`` or ``segmentation``.
        teacher: Previous target model, or None before the first evaluation.
        device: Torch device.

    Returns:
        The ``images`` folder.
    """
    from PIL import Image

    images = pai_schema.write_split(manifest, media_root, folder, task)
    model = YOLO(str(teacher)) if teacher is not None else None
    for image in manifest.images:
        if image.annotation_status != PARTIALLY_LABELED:
            continue
        rois = [roi.bbox_xyxy for roi in image.queried_rois]
        with Image.open(Path(media_root) / image.file_name) as opened:
            pixels = np.array(opened.convert("RGB"))
        keep = np.zeros(pixels.shape[:2], dtype=bool)
        extra: list[str] = []
        if model is not None:
            result = model.predict(
                np.ascontiguousarray(pixels[..., ::-1]),
                device=device,
                retina_masks=True,
                verbose=False,
            )[0]
            outlines = result.masks.xy if result.masks is not None else None
            for index, (box, score, label) in enumerate(
                zip(
                    result.boxes.xyxy.tolist(),
                    result.boxes.conf.tolist(),
                    result.boxes.cls.tolist(),
                    strict=True,
                )
            ):
                cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
                if score < PSEUDO_LABEL_CONFIDENCE or any(
                    r[0] <= cx <= r[2] and r[1] <= cy <= r[3] for r in rois
                ):
                    continue
                rois.append(box)
                ring = (
                    outlines[index].reshape(-1).tolist()
                    if task == "segmentation" and outlines is not None
                    else None
                )
                extra.append(_pseudo_line(int(label), box, ring, image))
        for x1, y1, x2, y2 in rois:
            keep[int(y1) : int(np.ceil(y2)), int(x1) : int(np.ceil(x2))] = True
        pixels[~keep] = NEUTRAL_PIXEL
        for stale in images.glob(f"{image.id}.*"):
            stale.unlink()
        Image.fromarray(pixels).save(images / f"{image.id}.png")
        label_file = folder / "labels" / f"{image.id}.txt"
        lines = [line for line in label_file.read_text().splitlines() if line]
        label_file.write_text("\n".join(lines + extra))
    return images


def _pseudo_line(
    label: int,
    box: list[float],
    ring: list[float] | None,
    image: pai_schema.PAIImage,
) -> str:
    """Return a temporary YOLO label for a confident prediction: its box, or
    its outline for segmentation."""
    x1, y1, x2, y2 = box
    if ring is not None and len(ring) >= 6:
        values = [
            value / (image.width if index % 2 == 0 else image.height)
            for index, value in enumerate(ring)
        ]
    else:
        values = [
            (x1 + x2) / 2 / image.width,
            (y1 + y2) / 2 / image.height,
            (x2 - x1) / image.width,
            (y2 - y1) / image.height,
        ]
    return " ".join([str(label), *(f"{min(max(v, 0.0), 1.0):.6f}" for v in values)])
