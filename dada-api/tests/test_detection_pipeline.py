"""The ``two_stage_detection_consensus`` pipeline on the detection annex cases."""

import pytest

pytest.importorskip("scipy")

from dada_api.consensus import catalog, detection, protocol  # noqa: E402
from dada_api.consensus.protocol import ResolverInput, Source  # noqa: E402

CAT, DOG = "class-cat", "class-dog"
WIDTH, HEIGHT = 200, 100


def _box(object_id: str, class_id: str, x: float, y: float, w: float, h: float):
    """Return one rectangle object."""
    return {
        "id": object_id,
        "class_id": class_id,
        "geometry": {"type": "rectangle", "coordinates": [x, y, w, h]},
        "attributes": {},
    }


def _input(
    documents: dict[str, list[dict]],
    *,
    parameters: dict | None = None,
    thresholds: dict | None = None,
    candidates: list[dict] | None = None,
    reviews: list[Source] = (),
) -> ResolverInput:
    """Return a detection input with one submission per rater."""
    normalized, gates = catalog.normalize(
        "detection", parameters or {}, thresholds or {}
    )
    return ResolverInput(
        pipeline="two_stage_detection_consensus",
        pipeline_version="1.0.0",
        task_type="detection",
        configuration={"parameters": normalized, "review_thresholds": gates},
        width=WIDTH,
        height=HEIGHT,
        class_ids=[CAT, DOG],
        sources=[
            Source(
                kind="submission",
                id=f"s-{rater}",
                annotator_id=rater,
                annotator_index=index,
                content_hash="h",
                objects=objects,
            )
            for index, (rater, objects) in enumerate(documents.items())
        ]
        + list(reviews),
        candidates=candidates,
    )


def test_agreeing_raters_produce_one_refined_object() -> None:
    output = detection.resolve(
        _input(
            {
                "ana": [_box("a1", CAT, 10, 10, 40, 30)],
                "bia": [_box("b1", CAT, 12, 10, 40, 30)],
            }
        )
    )

    [candidate] = output.candidates
    assert candidate.passed is True
    assert candidate.metrics["outcome"] == CAT
    [entry] = candidate.objects
    assert entry["class_id"] == CAT
    assert entry["geometry"]["coordinates"] == [11.0, 10.0, 40.0, 30.0]
    assert {member["source_id"] for member in candidate.members} == {"s-ana", "s-bia"}
    assert output.diagnostics["observation_matrix"][candidate.key] == {
        "ana": CAT,
        "bia": CAT,
    }


def test_the_same_object_with_different_classes_is_one_tied_candidate() -> None:
    output = detection.resolve(
        _input(
            {
                "ana": [_box("a1", CAT, 10, 10, 40, 30)],
                "bia": [_box("b1", DOG, 10, 10, 40, 30)],
            }
        )
    )

    [candidate] = output.candidates
    assert candidate.passed is False
    assert candidate.reasons == ["class_tie"]
    assert candidate.objects == []
    assert candidate.region is not None


def test_an_omitted_object_is_a_no_object_vote_and_needs_review() -> None:
    output = detection.resolve(
        _input(
            {
                "ana": [
                    _box("a1", CAT, 10, 10, 40, 30),
                    _box("a2", CAT, 120, 10, 40, 30),
                ],
                "bia": [_box("b1", CAT, 10, 10, 40, 30)],
            }
        )
    )

    by_members = {len(entry.members): entry for entry in output.candidates}
    assert by_members[2].passed is True
    lonely = by_members[1]
    assert lonely.passed is False
    assert lonely.reasons == ["class_tie"]
    assert output.diagnostics["observation_matrix"][lonely.key]["bia"] == "no_object"


def test_a_false_positive_is_rejected_by_a_majority_of_no_object() -> None:
    output = detection.resolve(
        _input(
            {
                "ana": [_box("a1", CAT, 120, 10, 40, 30)],
                "bia": [],
                "caio": [],
            }
        )
    )

    [candidate] = output.candidates
    assert candidate.passed is True
    assert candidate.metrics["outcome"] == "no_object"
    assert candidate.objects == []


def test_adjacent_objects_stay_separate() -> None:
    output = detection.resolve(
        _input(
            {
                "ana": [
                    _box("a1", CAT, 10, 10, 30, 30),
                    _box("a2", CAT, 45, 10, 30, 30),
                ],
                "bia": [
                    _box("b1", CAT, 10, 10, 30, 30),
                    _box("b2", CAT, 45, 10, 30, 30),
                ],
            }
        )
    )

    assert len(output.candidates) == 2
    assert all(entry.passed for entry in output.candidates)


def test_a_large_box_cannot_bridge_two_small_ones() -> None:
    output = detection.resolve(
        _input(
            {
                "ana": [_box("a1", CAT, 10, 10, 40, 40)],
                "bia": [_box("b1", CAT, 10, 10, 40, 28)],
                "caio": [_box("c1", CAT, 10, 22, 40, 28)],
            }
        )
    )

    sizes = sorted(len(entry.members) for entry in output.candidates)
    assert sizes != [3]
    assert sum(sizes) == 3


def test_same_rater_duplicates_never_vote() -> None:
    output = detection.resolve(
        _input(
            {
                "ana": [
                    _box("a1", CAT, 10, 10, 40, 30),
                    _box("a2", CAT, 11, 10, 40, 30),
                ],
                "bia": [_box("b1", CAT, 10, 10, 40, 30)],
            }
        )
    )

    [candidate] = output.candidates
    assert candidate.passed is True
    assert output.diagnostics["duplicates"] == [
        {"source_id": "s-ana", "object_id": "a2"}
    ]


def test_low_box_agreement_needs_review_despite_unanimous_class() -> None:
    output = detection.resolve(
        _input(
            {
                "ana": [_box("a1", CAT, 10, 10, 40, 30)],
                "bia": [_box("b1", CAT, 30, 10, 40, 30)],
            },
            parameters={"matching_iou": 0.3},
        )
    )

    [candidate] = output.candidates
    assert candidate.passed is False
    assert candidate.reasons == ["geometry_below_threshold"]
    assert candidate.objects[0]["class_id"] == CAT
    assert candidate.metrics["median_iou"] < 0.5


def test_boxes_are_clipped_to_the_image() -> None:
    output = detection.resolve(
        _input(
            {
                "ana": [_box("a1", CAT, 180, 80, 20, 20)],
                "bia": [_box("b1", CAT, 181, 81, 19, 19)],
            },
            parameters={"box_refinement": {"strategy": "weighted_box_fusion"}},
        )
    )

    [entry] = output.candidates[0].objects
    x, y, w, h = entry["geometry"]["coordinates"]
    assert x + w <= WIDTH and y + h <= HEIGHT


@pytest.mark.parametrize(
    "class_strategy",
    [
        {"strategy": "categorical_vote", "decision_rule": "plurality"},
        {"strategy": "categorical_vote", "decision_rule": "strict_majority"},
        {"strategy": "dirichlet_vote", "alpha": 0.5},
    ],
)
@pytest.mark.parametrize(
    "box_refinement",
    [
        {"strategy": "coordinate_median"},
        {"strategy": "trimmed_mean_box", "trim_fraction": 0.2},
        {"strategy": "weighted_box_fusion"},
    ],
)
def test_every_initial_strategy_combination_resolves_agreement(
    class_strategy: dict, box_refinement: dict
) -> None:
    output = detection.resolve(
        _input(
            {
                "ana": [_box("a1", CAT, 10, 10, 40, 30)],
                "bia": [_box("b1", CAT, 11, 10, 40, 30)],
                "caio": [_box("c1", CAT, 12, 10, 40, 30)],
            },
            parameters={
                "class_strategy": class_strategy,
                "box_refinement": box_refinement,
            },
        )
    )

    [candidate] = output.candidates
    assert candidate.passed is True
    assert candidate.objects[0]["geometry"]["coordinates"][0] == pytest.approx(11.0)
    assert output.versions[box_refinement["strategy"]] == "1.0.0"


def test_an_empty_image_is_one_passing_image_case() -> None:
    output = detection.resolve(_input({"ana": [], "bia": []}))

    [candidate] = output.candidates
    assert (candidate.key, candidate.scope, candidate.passed) == (
        "image",
        "image",
        True,
    )
    assert candidate.objects == []


def test_a_second_round_adds_the_reviewer_vote_and_box() -> None:
    first = detection.resolve(
        _input(
            {
                "ana": [_box("a1", CAT, 10, 10, 40, 30)],
                "bia": [_box("b1", DOG, 10, 10, 40, 30)],
            }
        )
    )
    [tied] = first.candidates
    review = Source(
        kind="review",
        id="r-caio",
        annotator_id="caio",
        annotator_index=2,
        content_hash="h",
        candidate_key=tied.key,
        evidence={
            "decision": "object",
            "class_id": CAT,
            "geometry": {"type": "rectangle", "coordinates": [13, 10, 40, 30]},
        },
    )
    second = detection.resolve(
        _input(
            {
                "ana": [_box("a1", CAT, 10, 10, 40, 30)],
                "bia": [_box("b1", DOG, 10, 10, 40, 30)],
            },
            candidates=[entry.model_dump(mode="json") for entry in first.candidates],
            reviews=[review],
        )
    )

    [candidate] = second.candidates
    assert candidate.key == tied.key
    assert candidate.passed is True
    assert candidate.metrics["outcome"] == CAT
    assert candidate.objects[0]["geometry"]["coordinates"] == [10.0, 10.0, 40.0, 30.0]
    assert candidate.metrics["supporting_boxes"] == 3


def test_replay_is_byte_identical() -> None:
    documents = {
        "ana": [_box("a1", CAT, 10, 10, 40, 30), _box("a2", DOG, 120, 40, 30, 30)],
        "bia": [_box("b1", CAT, 12, 11, 39, 30), _box("b2", CAT, 121, 40, 30, 31)],
        "caio": [_box("c1", CAT, 11, 10, 40, 29)],
    }
    first = detection.resolve(_input(documents))
    again = detection.resolve(_input(documents))

    assert protocol.fingerprint(first.model_dump(mode="json")) == protocol.fingerprint(
        again.model_dump(mode="json")
    )
