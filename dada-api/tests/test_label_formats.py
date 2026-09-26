"""Parsing of YOLO detection and COCO segmentation labels into seed documents."""

import json

import pytest

from dada_api.services import label_formats
from dada_api.services.label_formats import MediaTarget, SourceFile

MEDIA = {
    "cam/a.jpg": MediaTarget("media-a", 200, 100),
    "cam/b.png": MediaTarget("media-b", 100, 100),
}
CLASSES = {0: "class-zero", 1: "class-one"}


def yolo(path: str, text: str, file_id: str = "f1") -> SourceFile:
    return SourceFile(file_id, path, text.encode())


def coco(images: list, annotations: list, file_id: str = "c1") -> SourceFile:
    body = json.dumps({"images": images, "annotations": annotations})
    return SourceFile(file_id, "labels.json", body.encode())


def codes(result: label_formats.ParseResult) -> list[str]:
    return [error.code for error in result.errors]


def test_yolo_boxes_become_pixel_rectangles_on_the_matching_image() -> None:
    result = label_formats.parse_yolo_detection(
        [yolo("cam/a.txt", "1 0.5 0.5 0.5 0.2\n\n0 0.25 0.5 0.5 1.0\n")],
        MEDIA,
        CLASSES,
    )

    assert result.errors == []
    file_id, document = result.documents["media-a"]
    assert file_id == "f1"
    assert document["task_type"] == "detection"
    first, second = document["objects"]
    assert first["class_id"] == "class-one"
    assert first["geometry"]["type"] == "rectangle"
    assert first["geometry"]["coordinates"] == pytest.approx([50.0, 40.0, 100.0, 20.0])
    assert second["geometry"]["coordinates"] == pytest.approx([0.0, 0.0, 100.0, 100.0])


def test_an_empty_yolo_file_is_an_explicitly_empty_image() -> None:
    result = label_formats.parse_yolo_detection([yolo("cam/b.txt", "")], MEDIA, CLASSES)

    assert result.errors == []
    assert result.documents["media-b"][1]["objects"] == []


def test_yolo_rounding_past_the_edge_is_clamped_to_the_image() -> None:
    result = label_formats.parse_yolo_detection(
        [yolo("cam/b.txt", "0 0.9500005 0.5 0.1 0.2")], MEDIA, CLASSES
    )

    assert result.errors == []
    x, _, width, _ = result.documents["media-b"][1]["objects"][0]["geometry"][
        "coordinates"
    ]
    assert x + width == pytest.approx(100.0)


@pytest.mark.parametrize(
    ("path", "text", "code"),
    [
        ("../cam/a.txt", "0 0.5 0.5 0.1 0.1", "invalid_relative_path"),
        ("/cam/a.txt", "0 0.5 0.5 0.1 0.1", "invalid_relative_path"),
        ("cam/a.csv", "0 0.5 0.5 0.1 0.1", "malformed_label"),
        ("cam/missing.txt", "0 0.5 0.5 0.1 0.1", "unmatched_path"),
        ("cam/a.txt", "7 0.5 0.5 0.1 0.1", "unknown_class_index"),
        ("cam/a.txt", "0 0.5 0.5 0.1", "malformed_label"),
        ("cam/a.txt", "0 0.5 0.5 0.1 0.1 0.9", "malformed_label"),
        ("cam/a.txt", "zero 0.5 0.5 0.1 0.1", "malformed_label"),
        ("cam/a.txt", "0 0.95 0.5 0.2 0.1", "invalid_geometry"),
        ("cam/a.txt", "0 0.5 0.5 0 0.1", "invalid_geometry"),
        ("cam/a.txt", "0 nan 0.5 0.1 0.1", "invalid_geometry"),
    ],
)
def test_invalid_yolo_input_is_reported_and_produces_no_document(
    path: str, text: str, code: str
) -> None:
    result = label_formats.parse_yolo_detection([yolo(path, text)], MEDIA, CLASSES)

    assert codes(result) == [code]
    assert result.documents == {}


def test_two_yolo_files_for_one_image_are_duplicates() -> None:
    result = label_formats.parse_yolo_detection(
        [
            yolo("cam/a.txt", "0 0.5 0.5 0.1 0.1", "f1"),
            yolo("cam/a.txt", "1 0.5 0.5 0.1 0.1", "f2"),
        ],
        MEDIA,
        CLASSES,
    )

    assert codes(result) == ["duplicate_source_label"]
    assert result.errors[0].file_id == "f2"


def test_a_yolo_stem_shared_by_two_images_is_ambiguous() -> None:
    media = {
        "cam/a.jpg": MediaTarget("media-a", 10, 10),
        "cam/a.png": MediaTarget("media-a2", 10, 10),
    }

    result = label_formats.parse_yolo_detection(
        [yolo("cam/a.txt", "0 0.5 0.5 0.1 0.1")], media, CLASSES
    )

    assert codes(result) == ["ambiguous_media_match"]


def test_coco_polygons_become_rings_and_unannotated_images_are_empty() -> None:
    result = label_formats.parse_coco_segmentation(
        [
            coco(
                [
                    {"id": 1, "file_name": "cam/a.jpg"},
                    {"id": 2, "file_name": "cam/b.png"},
                ],
                [
                    {
                        "image_id": 1,
                        "category_id": 1,
                        "segmentation": [[10, 10, 50, 10, 50, 40, 10, 10]],
                    }
                ],
            )
        ],
        MEDIA,
        CLASSES,
    )

    assert result.errors == []
    document = result.documents["media-a"][1]
    assert document["task_type"] == "segmentation"
    (polygon,) = document["objects"]
    assert polygon["class_id"] == "class-one"
    assert polygon["geometry"] == {
        "type": "polygon",
        "coordinates": [[10.0, 10.0, 50.0, 10.0, 50.0, 40.0]],
    }
    assert result.documents["media-b"][1]["objects"] == []


@pytest.mark.parametrize(
    ("image", "annotation", "code"),
    [
        ({"id": 1, "file_name": "../a.jpg"}, None, "invalid_relative_path"),
        ({"id": 1, "file_name": "cam/c.jpg"}, None, "unmatched_path"),
        (
            {"id": 1, "file_name": "cam/a.jpg"},
            {"image_id": 9, "category_id": 0, "segmentation": [[0, 0, 5, 0, 5, 5]]},
            "unmatched_path",
        ),
        (
            {"id": 1, "file_name": "cam/a.jpg"},
            {"image_id": 1, "category_id": 4, "segmentation": [[0, 0, 5, 0, 5, 5]]},
            "unknown_class_index",
        ),
        (
            {"id": 1, "file_name": "cam/a.jpg"},
            {"image_id": 1, "category_id": 0, "segmentation": {"counts": "x"}},
            "unsupported_geometry",
        ),
        (
            {"id": 1, "file_name": "cam/a.jpg"},
            {"image_id": 1, "category_id": 0, "segmentation": [[0, 0, 5, 0, 0, 0]]},
            "invalid_geometry",
        ),
        (
            {"id": 1, "file_name": "cam/a.jpg"},
            {"image_id": 1, "category_id": 0, "segmentation": [[0, 0, 500, 0, 5, 5]]},
            "invalid_geometry",
        ),
        (
            {"id": 1, "file_name": "cam/a.jpg"},
            {
                "image_id": 1,
                "category_id": 0,
                "segmentation": [[0, 0, 10, 10, 10, 0, 0, 10]],
            },
            "invalid_geometry",
        ),
        (
            {"id": 1, "file_name": "cam/a.jpg"},
            {"image_id": 1, "category_id": 0, "segmentation": [[0, 0, 5, 0, 5]]},
            "invalid_geometry",
        ),
    ],
)
def test_invalid_coco_input_is_reported_and_produces_no_document(
    image: dict, annotation: dict | None, code: str
) -> None:
    annotations = [] if annotation is None else [annotation]

    result = label_formats.parse_coco_segmentation(
        [coco([image], annotations)], MEDIA, CLASSES
    )

    assert codes(result) == [code]
    assert result.documents == {}


def test_a_coco_image_described_twice_is_a_duplicate() -> None:
    image = {"id": 1, "file_name": "cam/a.jpg"}

    result = label_formats.parse_coco_segmentation(
        [coco([image], [], "c1"), coco([image], [], "c2")], MEDIA, CLASSES
    )

    assert codes(result) == ["duplicate_source_label"]
    assert result.errors[0].file_id == "c2"


def test_a_coco_file_that_is_not_json_is_malformed() -> None:
    result = label_formats.parse_coco_segmentation(
        [SourceFile("c1", "labels.json", b"not json")], MEDIA, CLASSES
    )

    assert codes(result) == ["malformed_label"]


@pytest.mark.parametrize(
    ("points", "simple"),
    [
        ([(0, 0), (4, 0), (4, 4), (0, 4)], True),
        ([(0, 0), (4, 4), (4, 0), (0, 4)], False),
        ([(0, 0), (4, 0), (2, 3)], True),
        ([(0, 0), (4, 0), (4, 4), (2, 0), (0, 4)], False),
    ],
)
def test_ring_simplicity(points: list[tuple[float, float]], simple: bool) -> None:
    assert label_formats.ring_is_simple(points) is simple
