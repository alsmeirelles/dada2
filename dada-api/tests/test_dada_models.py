"""DADA parts that need torch, Ultralytics, and timm: Mode 1 exact zero
background gradient, Mode 2 neutralization, embedding shapes, and bounded
object candidates. Skipped when the ``learning`` extra is not installed."""

from pathlib import Path
from types import SimpleNamespace

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("torchvision")
pytest.importorskip("ultralytics")
pytest.importorskip("timm")

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from ultralytics import YOLO  # noqa: E402
from ultralytics.cfg import get_cfg  # noqa: E402
from ultralytics.utils.tal import make_anchors  # noqa: E402

from dada_api.active_learning.dada_al.config.schema import (  # noqa: E402
    DADAAlConfig,
    PAITrainingMode,
)
from dada_api.active_learning.dada_al.dataset import (  # noqa: E402
    pai_schema,
    pai_trainer,
)
from dada_api.active_learning.dada_al.models.timm_adapter import (  # noqa: E402
    TimmClassificationAdapter,
)
from dada_api.active_learning.dada_al.models.yolo_adapter import (  # noqa: E402
    YoloAdapter,
)
from dada_api.active_learning.dada_al.uncertainty.cls_extractor import (  # noqa: E402
    ClassificationExtractor,
)
from dada_api.active_learning.dada_al.uncertainty.pre_nms_extractor import (  # noqa: E402
    PreNMSExtractor,
)

SIZE = 64
REGION = [0.0, 0.0, 32.0, 32.0]


def _masked(name: str) -> torch.nn.Module:
    """Build an untrained detector with the Mode 1 criterion."""
    network = YOLO(name).model
    network.__class__ = pai_trainer.PAIDetectionModel
    network.args = get_cfg()
    network.pai_regions = {"img": [REGION]}
    return network.train()


@pytest.mark.parametrize("name", ["yolo26n.yaml", "yolo11n.yaml", "yolo12n.yaml"])
def test_mode_1_gives_unqueried_background_an_exact_zero_gradient(name: str) -> None:
    network = _masked(name)
    image = torch.rand(1, 3, SIZE, SIZE)
    batch = {
        "img": image,
        "cls": torch.zeros(1, 1),
        "bboxes": torch.tensor([[0.2, 0.2, 0.1, 0.1]]),
        "batch_idx": torch.zeros(1),
        "im_file": ["/data/img.png"],
        "ratio_pad": [((1.0, 1.0), (0, 0))],
    }
    preds = network(image)
    branches = [preds["one2many"], preds["one2one"]] if "one2one" in preds else [preds]
    for branch in branches:
        branch["scores"].retain_grad()
    loss, _ = network.loss(batch, preds)
    loss.sum().backward()
    points, strides = make_anchors(branches[0]["feats"], network.model[-1].stride, 0.5)
    centres = points * strides
    outside = ~((centres[:, 0] <= REGION[2]) & (centres[:, 1] <= REGION[3]))

    assert len(branches) == (2 if name.startswith("yolo26") else 1)
    for branch in branches:
        gradient = branch["scores"].grad[0]
        assert gradient[:, outside].abs().max().item() == 0.0
        assert gradient[:, ~outside].abs().max().item() > 0.0


def _write_image(folder: Path, name: str) -> str:
    """Write a random PNG under a project-like key and return the key."""
    key = f"project/{name}"
    path = folder / key
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.full((48, 64, 3), 200, dtype=np.uint8)).save(path, format="PNG")
    return key


def test_mode_2_neutralizes_unqueried_pixels_and_adds_confident_labels(
    tmp_path: Path, monkeypatch
) -> None:
    key = _write_image(tmp_path, "partial")
    manifest = pai_schema.PAIManifest.model_validate(
        {
            "info": {},
            "categories": [{"id": 0, "name": "can", "class_id": "c"}],
            "images": [
                {
                    "id": "partial",
                    "file_name": key,
                    "media_type": "image/png",
                    "width": 64,
                    "height": 48,
                    "annotation_status": "PARTIALLY_LABELED",
                    "queried_rois": [
                        {
                            "roi_id": "r",
                            "bbox_xyxy": [0.0, 0.0, 16.0, 16.0],
                            "resolution": "CONFIRMED_OBJECT",
                        }
                    ],
                }
            ],
            "annotations": [
                {
                    "id": "a",
                    "image_id": "partial",
                    "category_id": 0,
                    "bbox": [2.0, 2.0, 8.0, 8.0],
                    "roi_id": "r",
                }
            ],
        }
    )

    class Teacher:
        def __init__(self, _: str) -> None:
            pass

        def predict(self, *_, **__):
            boxes = SimpleNamespace(
                xyxy=torch.tensor([[40.0, 30.0, 60.0, 44.0], [20.0, 20.0, 30.0, 30.0]]),
                conf=torch.tensor([0.9, 0.5]),
                cls=torch.tensor([0.0, 0.0]),
            )
            return [SimpleNamespace(boxes=boxes, masks=None)]

    monkeypatch.setattr(pai_trainer, "YOLO", Teacher)
    images = pai_trainer.neutralize(
        manifest, str(tmp_path), tmp_path / "train", "detection", Path("t.pt"), "cpu"
    )

    pixels = np.array(Image.open(images / "partial.png"))
    labels = (tmp_path / "train" / "labels" / "partial.txt").read_text().splitlines()
    assert (pixels[:16, :16] == 200).all()
    assert (pixels[30:44, 40:60] == 200).all()
    assert (pixels[20:30, 20:30] == 114).all()
    assert (pixels[46:, :] == 114).all()
    assert len(labels) == 2
    assert labels[1].startswith("0 0.781250 0.770833")


def _images(folder: Path, count: int) -> list[pai_schema.PAIImage]:
    """Write random images and describe them."""
    return [
        pai_schema.PAIImage(
            id=f"i{index}",
            file_name=_write_image(folder, f"i{index}"),
            media_type="image/png",
            width=64,
            height=48,
            annotation_status="UNLABELED",
        )
        for index in range(count)
    ]


def _checkpoints(adapter: TimmClassificationAdapter, folder: Path, count: int):
    """Save untrained EfficientNet-B1 classifiers."""
    paths = []
    for seed in range(1, count + 1):
        torch.manual_seed(seed)
        model = adapter.build("efficientnet_b1", pretrained=False)
        path = folder / f"proxy-{seed}.pt"
        torch.save(
            {"model_name": "efficientnet_b1", "state_dict": model.state_dict()}, path
        )
        paths.append(path)
    return paths


@pytest.mark.parametrize(
    ("method", "models", "dimension"),
    [("deep_ensemble", 3, 3840), ("tta_multiview", 1, 1280)],
)
def test_classification_embeddings_have_the_specified_shape(
    tmp_path: Path, method: str, models: int, dimension: int
) -> None:
    timm_adapter = TimmClassificationAdapter(
        str(tmp_path), 3, "efficientnet_b1", image_size=64, batch_size=2, device="cpu"
    )
    config = DADAAlConfig.for_request(
        {
            "proxy_model_name": "efficientnet_b1",
            "target_model_name": "efficientnet_b1",
            "uncertainty_method": method,
        },
        "classification",
        2,
    )

    candidates = ClassificationExtractor(timm_adapter, config).extract(
        _checkpoints(timm_adapter, tmp_path, models),
        _images(tmp_path, 3),
        str(tmp_path),
    )

    assert len(candidates) == 3
    for candidate in candidates:
        assert candidate.feature_vector.shape == (dimension,)
        assert np.linalg.norm(candidate.feature_vector) == pytest.approx(1.0, abs=1e-5)
        assert 0.0 < candidate.total_uncertainty <= 1.0


@pytest.mark.parametrize("name", ["yolo26n.yaml", "yolo11n.yaml"])
def test_pre_nms_candidates_are_bounded_and_embedded(tmp_path: Path, name: str) -> None:
    torch.manual_seed(0)
    network = YOLO(name).model.float().eval()
    adapter = YoloAdapter(
        "detection",
        str(tmp_path),
        tmp_path / "weights",
        image_size=SIZE,
        batch_size=2,
        device="cpu",
        mode=PAITrainingMode.MODE_1_LOSS_MASK,
    )
    config = DADAAlConfig.for_request({"candidate_conf_floor": 1e-9}, "detection", 2)

    candidates = PreNMSExtractor(adapter, config).extract(
        network, _images(tmp_path, 2), str(tmp_path)
    )

    assert candidates
    for candidate in candidates:
        assert 0.0 <= candidate.cls_uncertainty <= 1.0
        assert 0.0 <= candidate.spatial_uncertainty <= 1.0
        assert 0.0 <= candidate.total_uncertainty <= 1.0
        assert np.linalg.norm(candidate.feature_vector) == pytest.approx(1.0, abs=1e-5)
        x1, y1, x2, y2 = candidate.bbox_xyxy
        assert 0 <= x1 <= x2 <= 64 and 0 <= y1 <= y2 <= 48
