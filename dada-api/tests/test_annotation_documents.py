"""Task and geometry rules a full-image annotation document must meet."""

from dada_api.services import annotation_documents
from dada_api.services.annotation_documents import DocumentError

CLASSES = {"class-a", "class-b"}
WIDTH, HEIGHT = 200, 100


def box(object_id: str, coordinates: list[float], class_id: str = "class-a") -> dict:
    return {
        "id": object_id,
        "class_id": class_id,
        "geometry": {"type": "rectangle", "coordinates": coordinates},
        "attributes": {},
    }


def polygon(object_id: str, *rings: list[float], class_id: str = "class-a") -> dict:
    return {
        "id": object_id,
        "class_id": class_id,
        "geometry": {"type": "polygon", "coordinates": list(rings)},
        "attributes": {},
    }


def label(object_id: str, class_id: str) -> dict:
    return {"id": object_id, "class_id": class_id, "geometry": None, "attributes": {}}


def check(task_type: str, objects: list[dict]) -> list[DocumentError]:
    return annotation_documents.validate_submission(
        task_type, objects, CLASSES, WIDTH, HEIGHT
    )


def test_a_detection_image_may_hold_several_classes() -> None:
    objects = [box("1", [0, 0, 200, 100]), box("2", [10, 10, 5, 5], "class-b")]

    assert check("detection", objects) == []


def test_boxes_must_have_area_and_stay_inside_the_image() -> None:
    errors = check(
        "detection",
        [box("flat", [10, 10, 0, 5]), box("outside", [150, 50, 60, 10])],
    )

    assert errors == [
        DocumentError("flat", "degenerate_geometry"),
        DocumentError("outside", "out_of_bounds"),
    ]


def test_a_valid_polygon_may_repeat_its_first_point() -> None:
    square = [10, 10, 50, 10, 50, 50, 10, 50, 10, 10]

    assert check("segmentation", [polygon("1", square)]) == []


def test_polygon_rings_are_checked_for_points_bounds_and_crossings() -> None:
    errors = check(
        "segmentation",
        [
            polygon("line", [0, 0, 10, 10, 0, 0]),
            polygon("outside", [0, 0, 250, 0, 0, 50]),
            polygon("bowtie", [0, 0, 50, 50, 50, 0, 0, 50]),
            polygon("odd", [0, 0, 10, 0, 10]),
        ],
    )

    assert errors == [
        DocumentError("line", "degenerate_geometry"),
        DocumentError("outside", "out_of_bounds"),
        DocumentError("bowtie", "self_intersecting"),
        DocumentError("odd", "wrong_geometry"),
    ]


def test_the_geometry_must_match_the_task() -> None:
    assert check("detection", [polygon("p", [0, 0, 10, 0, 0, 10])]) == [
        DocumentError("p", "wrong_geometry")
    ]
    assert check("segmentation", [box("b", [0, 0, 5, 5])]) == [
        DocumentError("b", "wrong_geometry")
    ]
    assert check("classification", [box("b", [0, 0, 5, 5])]) == [
        DocumentError("b", "wrong_geometry")
    ]


def test_unknown_classes_and_repeated_object_ids_are_refused() -> None:
    errors = check(
        "detection",
        [box("same", [0, 0, 5, 5], "class-z"), box("same", [0, 0, 5, 5])],
    )

    assert errors == [
        DocumentError("same", "unknown_class"),
        DocumentError("same", "duplicate_object_id"),
    ]


def test_an_empty_image_is_an_answer_for_detection_and_segmentation_only() -> None:
    assert check("detection", []) == []
    assert check("segmentation", []) == []
    assert check("classification", []) == [DocumentError(None, "empty_not_allowed")]


def test_classification_is_a_set_of_distinct_classes() -> None:
    assert check("classification", [label("1", "class-a"), label("2", "class-b")]) == []
    assert check("classification", [label("1", "class-a"), label("2", "class-a")]) == [
        DocumentError("2", "duplicate_class")
    ]


def test_the_content_hash_ignores_key_order_but_not_content() -> None:
    first = [box("1", [0, 0, 5, 5])]
    reordered = [{key: first[0][key] for key in reversed(list(first[0]))}]
    moved = [box("1", [1, 0, 5, 5])]
    digest = annotation_documents.content_hash

    assert digest(first) == digest(reordered)
    assert digest(first) != digest(moved)
