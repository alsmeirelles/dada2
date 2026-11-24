"""Ultralytics YOLO11, YOLO12, and YOLO26 adapter for detection and
segmentation (spec 4.2.2).

Checkpoints are downloaded into the solution's state folder. A forward pass
letterboxes the canonical image itself, so boxes map back exactly, and
observes the head through a hook: its inputs are the P3, P4, and P5 neck maps,
and its raw output holds the dense one-to-many branch and, in YOLO26, the
sparse one-to-one branch, before any NMS. Inference never fuses the model,
which would drop the second YOLO26 head.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch
import torch.nn.functional as functional
from torchvision.ops import batched_nms, box_iou
from ultralytics import YOLO
from ultralytics.utils.tal import dist2bbox, make_anchors

from dada_api.active_learning.dada_al.acquisition.feature_extractor import capture
from dada_api.active_learning.dada_al.config.schema import PAITrainingMode
from dada_api.active_learning.dada_al.dataset import pai_schema, pai_trainer
from dada_api.active_learning.dada_al.dataset.pai_schema import snap
from dada_api.active_learning.dada_al.models.base_adapter import ModelAdapter

DEFAULT_IMAGE_SIZE = 640
NMS_IOU = 0.7
PREDICT_CONFIDENCE = 0.25
LETTERBOX_FILL = 114
POLYGON_TOLERANCE = 1.0


@dataclass
class Pass:
    """One forward pass over one letterboxed image.

    Attributes:
        feats: P3, P4, and P5 maps, each ``(1, C, H, W)``.
        one_to_many: Raw dense branch of the head.
        one_to_one: Raw sparse YOLO26 branch, or None.
        gain: Scale from canonical to network pixels.
        pad: Left and top padding in network pixels.
    """

    feats: list[torch.Tensor]
    one_to_many: dict[str, Any]
    one_to_one: dict[str, Any] | None
    gain: float
    pad: tuple[float, float]


@dataclass
class Decoded:
    """Decoded predictions of one branch for one image.

    Attributes:
        boxes: ``xyxy`` boxes in network pixels, ``(A, 4)``.
        scores: Sigmoid class scores, ``(A, C)``.
        raw_boxes: Raw box outputs, ``(A, 4 * reg_max)``.
        coefficients: Mask coefficients ``(A, 32)``, or None for detection.
        proto: Mask prototypes ``(32, h, w)``, or None for detection.
    """

    boxes: torch.Tensor
    scores: torch.Tensor
    raw_boxes: torch.Tensor
    coefficients: torch.Tensor | None
    proto: torch.Tensor | None


def letterbox(pixels: np.ndarray, size: int) -> tuple[np.ndarray, float, tuple]:
    """Resize an RGB image into a square, keeping its aspect, centred.

    Args:
        pixels: Image of shape ``(H, W, 3)``.
        size: Side of the square.

    Returns:
        The square image, the gain, and the ``(left, top)`` padding.
    """
    height, width = pixels.shape[:2]
    gain = min(size / height, size / width)
    new_width, new_height = round(width * gain), round(height * gain)
    resized = cv2.resize(
        pixels, (new_width, new_height), interpolation=cv2.INTER_LINEAR
    )
    left = round((size - new_width) / 2 - 0.1)
    top = round((size - new_height) / 2 - 0.1)
    square = cv2.copyMakeBorder(
        resized,
        top,
        size - new_height - top,
        left,
        size - new_width - left,
        cv2.BORDER_CONSTANT,
        value=(LETTERBOX_FILL,) * 3,
    )
    return square, gain, (float(left), float(top))


def _turn(a, b, c) -> int:
    """Return the turn direction of ``a -> b -> c``: 1, -1, or 0."""
    value = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return (value > 0) - (value < 0)


def _on(a, b, c) -> bool:
    """Return whether collinear point ``c`` lies on segment ``a-b``."""
    return min(a[0], b[0]) <= c[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= c[
        1
    ] <= max(a[1], b[1])


def _meet(a, b, c, d) -> bool:
    """Return whether closed segments ``ab`` and ``cd`` share a point."""
    o1, o2, o3, o4 = _turn(a, b, c), _turn(a, b, d), _turn(c, d, a), _turn(c, d, b)
    if o1 != o2 and o3 != o4:
        return True
    return (
        (o1 == 0 and _on(a, b, c))
        or (o2 == 0 and _on(a, b, d))
        or (o3 == 0 and _on(c, d, a))
        or (o4 == 0 and _on(c, d, b))
    )


def _simple(points: list[tuple[float, float]]) -> bool:
    """Return whether a closed ring never crosses or touches itself."""
    count = len(points)
    edges = [(points[i], points[(i + 1) % count]) for i in range(count)]
    for i in range(count):
        for j in range(i + 2, count):
            if i == 0 and j == count - 1:
                continue
            if _meet(*edges[i], *edges[j]):
                return False
    return True


def outline(binary: np.ndarray) -> np.ndarray | None:
    """Trace the largest region of a binary mask, simplified by one pixel.

    Args:
        binary: Mask of shape ``(H, W)``.

    Returns:
        Points of shape ``(N, 2)`` in mask pixels, or None without a region.
    """
    contours, _ = cv2.findContours(
        binary.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        return None
    largest = max(contours, key=cv2.contourArea)
    return (
        cv2.approxPolyDP(largest, POLYGON_TOLERANCE, True).reshape(-1, 2).astype(float)
    )


def canonical_ring(points: np.ndarray, width: int, height: int) -> list[float] | None:
    """Turn traced points into a valid canonical polygon ring.

    Points are snapped to the 1/64-pixel grid inside the image and repeated
    neighbours dropped. A ring that crosses or touches itself is replaced by
    the convex hull of its points, which never does.

    Args:
        points: Points of shape ``(N, 2)`` in canonical pixels.
        width: Image width.
        height: Image height.

    Returns:
        The flat ring, or None when fewer than three distinct points remain.
    """
    ring: list[tuple[float, float]] = []
    for x, y in points.tolist():
        point = (snap(x, 0, width), snap(y, 0, height))
        if not ring or ring[-1] != point:
            ring.append(point)
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring.pop()
    if len(set(ring)) < 3:
        return None
    if not _simple(ring):
        hull = cv2.convexHull(np.array(ring, dtype=np.float64).astype(np.float32))
        ring = [tuple(map(float, point)) for point in hull.reshape(-1, 2)]
        if len(set(ring)) < 3 or not _simple(ring):
            return None
    return [value for point in ring for value in point]


class YoloAdapter(ModelAdapter):
    """Trains, observes, and measures YOLO models of one task."""

    def __init__(
        self,
        task: str,
        media_root: str,
        weights_dir: Path,
        *,
        image_size: int | None,
        batch_size: int,
        device: str,
        mode: PAITrainingMode,
        teacher: Path | None = None,
    ) -> None:
        """Configure the adapter.

        Args:
            task: ``detection`` or ``segmentation``.
            media_root: Media root of the request.
            weights_dir: Folder where pretrained checkpoints are downloaded.
            image_size: Network input size; 640 when None.
            batch_size: Training batch size.
            device: Torch device.
            mode: Partially annotated image training mode.
            teacher: Previous target model, used by Mode 2.
        """
        self.task = task
        self.media_root = media_root
        self.weights_dir = weights_dir
        self.image_size = image_size or DEFAULT_IMAGE_SIZE
        self.batch_size = batch_size
        self.device = device
        self.mode = mode
        self.teacher = teacher

    def resolve(self, model_name: str) -> str:
        """Return where a named checkpoint lives, downloaded on first use."""
        self.weights_dir.mkdir(parents=True, exist_ok=True)
        return str(self.weights_dir / model_name)

    def _dataset(self, training: pai_schema.PAIManifest, folder: Path) -> Path:
        """Write the training split and its dataset description."""
        names = [category.name for category in training.categories]
        if self.mode is PAITrainingMode.MODE_2_VISUAL_MASK:
            images = pai_trainer.neutralize(
                training,
                self.media_root,
                folder / "train",
                self.task,
                self.teacher,
                self.device,
            )
        else:
            images = pai_schema.write_split(
                training, self.media_root, folder / "train", self.task
            )
        return pai_schema.write_data_yaml(folder / "data.yaml", images, images, names)

    def train(
        self,
        model_name: str,
        training: pai_schema.PAIManifest,
        *,
        epochs: int,
        seed: int,
        output: Path,
        name: str,
    ) -> Path:
        """Train a YOLO model on the accepted training data (spec 4.6)."""
        data = self._dataset(training, output / f"{name}-data")
        regions = (
            pai_schema.regions(training)
            if self.mode is PAITrainingMode.MODE_1_LOSS_MASK
            else {}
        )
        return pai_trainer.train(
            self.resolve(model_name),
            data,
            self.task,
            regions,
            epochs=epochs,
            imgsz=self.image_size,
            batch=self.batch_size,
            seed=seed,
            device=self.device,
            output=output,
            name=name,
        )

    def load(self, checkpoint: Path) -> torch.nn.Module:
        """Load a checkpoint for observation, unfused and in evaluation mode."""
        return YOLO(str(checkpoint)).model.to(self.device).float().eval()

    def forward(self, network: torch.nn.Module, pixels: np.ndarray) -> Pass:
        """Run one RGB image through the network and observe its head.

        Args:
            network: Loaded model.
            pixels: Canonical image of shape ``(H, W, 3)``.

        Returns:
            The head's inputs and raw branches.
        """
        square, gain, pad = letterbox(pixels, self.image_size)
        tensor = (
            torch.from_numpy(np.ascontiguousarray(square))
            .permute(2, 0, 1)[None]
            .float()
            .div(255)
            .to(self.device)
        )
        with capture(network.model[-1]) as seen, torch.no_grad():
            network(tensor)
        raw = seen["output"][1]
        return Pass(
            feats=list(seen["inputs"][0]),
            one_to_many=raw.get("one2many", raw),
            one_to_one=raw.get("one2one"),
            gain=gain,
            pad=pad,
        )

    @staticmethod
    def decode(network: torch.nn.Module, branch: dict[str, Any]) -> Decoded:
        """Decode one raw branch into boxes and scores, before any NMS."""
        head = network.model[-1]
        anchors, strides = make_anchors(branch["feats"], head.stride, 0.5)
        distances = head.dfl(branch["boxes"])
        boxes = dist2bbox(
            distances, anchors.transpose(0, 1).unsqueeze(0), xywh=False, dim=1
        ) * strides.transpose(0, 1)
        coefficients = branch.get("mask_coefficient")
        proto = branch.get("proto")
        if isinstance(proto, tuple):
            proto = proto[0]
        return Decoded(
            boxes=boxes[0].transpose(0, 1),
            scores=branch["scores"][0].sigmoid().transpose(0, 1),
            raw_boxes=branch["boxes"][0].transpose(0, 1),
            coefficients=coefficients[0].transpose(0, 1)
            if coefficients is not None
            else None,
            proto=proto[0] if proto is not None else None,
        )

    @staticmethod
    def survivors(decoded: Decoded, floor: float) -> torch.Tensor:
        """Return the indices that survive class-wise NMS above a confidence."""
        confidence, labels = decoded.scores.max(1)
        keep = torch.nonzero(confidence >= floor).flatten()
        if keep.numel() == 0:
            return keep
        kept = batched_nms(decoded.boxes[keep], confidence[keep], labels[keep], NMS_IOU)
        return keep[kept]

    def to_canonical(
        self, boxes: torch.Tensor, step: Pass, width: int, height: int
    ) -> np.ndarray:
        """Map network-pixel ``xyxy`` boxes back to the canonical image."""
        left, top = step.pad
        shift = boxes.new_tensor([left, top, left, top])
        mapped = ((boxes - shift) / step.gain).cpu().numpy()
        mapped[:, [0, 2]] = mapped[:, [0, 2]].clip(0, width)
        mapped[:, [1, 3]] = mapped[:, [1, 3]].clip(0, height)
        return mapped

    def mask_probabilities(
        self, decoded: Decoded, index: int, box: torch.Tensor
    ) -> torch.Tensor:
        """Return one object's mask probabilities at network resolution,
        zero outside its box."""
        channels, height, width = decoded.proto.shape
        logits = (
            decoded.coefficients[index] @ decoded.proto.reshape(channels, -1)
        ).reshape(1, 1, height, width)
        size = self.image_size
        probabilities = functional.interpolate(
            logits, size=(size, size), mode="bilinear", align_corners=False
        )[0, 0].sigmoid()
        x1, y1, x2, y2 = (int(v) for v in box.round().clamp(0, size).tolist())
        cropped = torch.zeros_like(probabilities)
        cropped[y1:y2, x1:x2] = probabilities[y1:y2, x1:x2]
        return cropped

    def polygon(
        self, probabilities: torch.Tensor, step: Pass, width: int, height: int
    ) -> list[float] | None:
        """Trace a mask's outline as one canonical-pixel ring."""
        points = outline((probabilities > 0.5).cpu().numpy())
        if points is None:
            return None
        left, top = step.pad
        points[:, 0] = (points[:, 0] - left) / step.gain
        points[:, 1] = (points[:, 1] - top) / step.gain
        return canonical_ring(points, width, height)

    def predict(self, checkpoint: Path, pixels: np.ndarray) -> list[dict[str, Any]]:
        """Return the final predictions of a trained model on one image.

        Args:
            checkpoint: Trained model.
            pixels: Canonical RGB image.

        Returns:
            One dict per instance with ``box`` (``xyxy``), ``score``,
            ``label``, and, for segmentation, ``mask`` at canonical size.
        """
        result = YOLO(str(checkpoint)).predict(
            np.ascontiguousarray(pixels[..., ::-1]),
            imgsz=self.image_size,
            conf=PREDICT_CONFIDENCE,
            device=self.device,
            retina_masks=True,
            verbose=False,
        )[0]
        masks = (
            result.masks.data.cpu().numpy() > 0.5 if result.masks is not None else None
        )
        return [
            {
                "box": result.boxes.xyxy[index].tolist(),
                "score": float(result.boxes.conf[index]),
                "label": int(result.boxes.cls[index]),
                "mask": masks[index] if masks is not None else None,
            }
            for index in range(len(result.boxes))
        ]

    def evaluate(
        self,
        checkpoint: Path,
        manifest: pai_schema.PAIManifest,
        metric: str,
        output: Path,
    ) -> dict[str, float]:
        """Measure the target model with the task's metric (D9).

        Detection reports ``map50`` averaged over the classes present in the
        split. Segmentation reports ``mean_iou``: per class, mask intersection
        over union summed over the images; a class absent from both the
        reference and the prediction is left out of the mean.
        """
        if self.task == "detection":
            names = [category.name for category in manifest.categories]
            images = pai_schema.write_split(
                manifest, self.media_root, output, self.task
            )
            data = pai_schema.write_data_yaml(
                output / "data.yaml", images, images, names
            )
            result = YOLO(str(checkpoint)).val(
                data=str(data),
                imgsz=self.image_size,
                batch=self.batch_size,
                device=self.device,
                plots=False,
                verbose=False,
                project=str(output),
                name="val",
                exist_ok=True,
            )
            return {"map50": float(result.box.map50)}

        classes = len(manifest.categories)
        intersection = np.zeros(classes)
        union = np.zeros(classes)
        for image in manifest.images:
            pixels = read_rgb(self.media_root, image)
            truth = np.zeros((classes, image.height, image.width), dtype=bool)
            for annotation in manifest.annotations:
                if annotation.image_id == image.id and annotation.segmentation:
                    canvas = np.zeros((image.height, image.width), dtype=np.uint8)
                    for ring in annotation.segmentation:
                        polygon = np.array(ring, dtype=np.float32).reshape(-1, 2)
                        cv2.fillPoly(canvas, [polygon.round().astype(np.int32)], 1)
                    truth[annotation.category_id] |= canvas.astype(bool)
            predicted = np.zeros_like(truth)
            for instance in self.predict(checkpoint, pixels):
                if instance["mask"] is not None:
                    predicted[instance["label"]] |= instance["mask"][
                        : image.height, : image.width
                    ]
            intersection += (truth & predicted).reshape(classes, -1).sum(1)
            union += (truth | predicted).reshape(classes, -1).sum(1)
        present = union > 0
        value = (
            float((intersection[present] / union[present]).mean())
            if present.any()
            else 1.0
        )
        return {"mean_iou": value}


def read_rgb(media_root: str, image: pai_schema.PAIImage) -> np.ndarray:
    """Decode a manifest image in its canonical pixel plane, as RGB."""
    from PIL import Image

    with Image.open(Path(media_root) / image.file_name) as opened:
        return np.array(opened.convert("RGB"))


def iou(first: torch.Tensor, second: torch.Tensor) -> torch.Tensor:
    """Return the IoU matrix of two sets of ``xyxy`` boxes."""
    if first.numel() == 0 or second.numel() == 0:
        return first.new_zeros(len(first), len(second))
    return box_iou(first, second)
