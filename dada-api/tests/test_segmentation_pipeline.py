"""The ``two_stage_segmentation_consensus`` pipeline on the segmentation annex
cases."""

import pytest

pytest.importorskip("scipy")
pytest.importorskip("cv2")

from dada_api.consensus import catalog, protocol, segmentation  # noqa: E402
from dada_api.consensus.protocol import ResolverInput, Source  # noqa: E402

CAT, DOG = "class-cat", "class-dog"
WIDTH, HEIGHT = 120, 80


def _square(x: float, y: float, size: float) -> list[float]:
    """Return one square ring."""
    return [x, y, x + size, y, x + size, y + size, x, y + size]


def _instance(object_id: str, class_id: str, *rings: list[float]) -> dict:
    """Return one polygon object."""
    return {
        "id": object_id,
        "class_id": class_id,
        "geometry": {"type": "polygon", "coordinates": list(rings)},
        "attributes": {},
    }


def _input(
    documents: dict[str, list[dict]],
    *,
    parameters: dict | None = None,
    candidates: list[dict] | None = None,
    reviews: list[Source] = (),
) -> ResolverInput:
    """Return a segmentation input with one submission per rater."""
    normalized, gates = catalog.normalize("segmentation", parameters or {}, {})
    return ResolverInput(
        pipeline="two_stage_segmentation_consensus",
        pipeline_version="1.0.0",
        task_type="segmentation",
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


def test_agreeing_masks_produce_one_traced_instance() -> None:
    output = segmentation.resolve(
        _input(
            {
                "ana": [_instance("a1", CAT, _square(10, 10, 20))],
                "bia": [_instance("b1", CAT, _square(11, 10, 20))],
            }
        )
    )

    [candidate] = output.candidates
    assert candidate.passed is True
    [entry] = candidate.objects
    assert entry["class_id"] == CAT
    assert entry["geometry"]["type"] == "polygon"
    assert len(entry["geometry"]["coordinates"]) == 1
    assert candidate.metrics["median_overlap"] > 0.5
    assert candidate.metrics["refinement"]["strategy"] == "segmentation_majority_vote"


def test_the_same_instance_with_different_classes_is_tied() -> None:
    output = segmentation.resolve(
        _input(
            {
                "ana": [_instance("a1", CAT, _square(10, 10, 20))],
                "bia": [_instance("b1", DOG, _square(10, 10, 20))],
            }
        )
    )

    [candidate] = output.candidates
    assert (candidate.passed, candidate.reasons) == (False, ["class_tie"])


def test_an_omitted_instance_and_a_false_positive_are_measured() -> None:
    omitted = segmentation.resolve(
        _input(
            {
                "ana": [
                    _instance("a1", CAT, _square(10, 10, 20)),
                    _instance("a2", CAT, _square(70, 10, 20)),
                ],
                "bia": [_instance("b1", CAT, _square(10, 10, 20))],
            }
        )
    )
    rejected = segmentation.resolve(
        _input(
            {
                "ana": [_instance("a1", CAT, _square(70, 10, 20))],
                "bia": [],
                "caio": [],
            }
        )
    )

    lonely = next(entry for entry in omitted.candidates if len(entry.members) == 1)
    assert lonely.reasons == ["class_tie"]
    [false_positive] = rejected.candidates
    assert false_positive.passed is True
    assert false_positive.metrics["outcome"] == "no_object"
    assert false_positive.objects == []


def test_touching_instances_stay_separate() -> None:
    output = segmentation.resolve(
        _input(
            {
                "ana": [
                    _instance("a1", CAT, _square(10, 10, 20)),
                    _instance("a2", CAT, _square(30, 10, 20)),
                ],
                "bia": [
                    _instance("b1", CAT, _square(10, 10, 20)),
                    _instance("b2", CAT, _square(30, 10, 20)),
                ],
            }
        )
    )

    assert len(output.candidates) == 2
    assert all(entry.passed for entry in output.candidates)


def test_holes_and_disconnected_regions_survive_tracing() -> None:
    holed = _instance("h", CAT, _square(10, 10, 40), _square(20, 20, 20))
    split = _instance("s", CAT, _square(60, 10, 15), _square(90, 10, 15))
    output = segmentation.resolve(
        _input({"ana": [holed, split], "bia": [holed, split]})
    )

    by_area = sorted(output.candidates, key=lambda entry: entry.metrics["area"])
    assert all(entry.passed for entry in output.candidates)
    split_rings = by_area[0].objects[0]["geometry"]["coordinates"]
    holed_rings = by_area[1].objects[0]["geometry"]["coordinates"]
    assert len(split_rings) == 2
    assert len(holed_rings) == 2


def test_a_thin_structure_is_kept() -> None:
    line = _instance("l", CAT, [10, 10, 100, 10, 100, 13, 10, 13])
    output = segmentation.resolve(_input({"ana": [line], "bia": [line]}))

    [candidate] = output.candidates
    assert candidate.passed is True
    assert candidate.objects[0]["geometry"]["coordinates"]


def test_low_mask_agreement_needs_review() -> None:
    output = segmentation.resolve(
        _input(
            {
                "ana": [_instance("a1", CAT, _square(10, 10, 30))],
                "bia": [_instance("b1", CAT, _square(22, 10, 30))],
            },
            parameters={"matching_threshold": 0.3},
        )
    )

    [candidate] = output.candidates
    assert candidate.passed is False
    assert "geometry_below_threshold" in candidate.reasons


@pytest.mark.parametrize(
    "mask_refinement",
    [
        {"strategy": "segmentation_majority_vote"},
        {"strategy": "segmentation_em"},
        {"strategy": "segmentation_rasa"},
        {"strategy": "staple", "pixel_threshold": 0.5},
    ],
)
@pytest.mark.parametrize(
    "class_strategy",
    [
        {"strategy": "categorical_vote", "decision_rule": "supermajority"},
        {"strategy": "dirichlet_vote", "alpha": 0.5},
    ],
)
def test_every_refinement_runs_after_the_class_decision(
    mask_refinement: dict, class_strategy: dict
) -> None:
    if mask_refinement["strategy"] != "staple":
        pytest.importorskip("crowdkit")
    output = segmentation.resolve(
        _input(
            {
                "ana": [_instance("a1", CAT, _square(10, 10, 20))],
                "bia": [_instance("b1", CAT, _square(11, 10, 20))],
                "caio": [_instance("c1", CAT, _square(10, 11, 20))],
            },
            parameters={
                "class_strategy": class_strategy,
                "mask_refinement": mask_refinement,
            },
        )
    )

    [candidate] = output.candidates
    assert candidate.passed is True
    assert candidate.objects[0]["class_id"] == CAT
    assert output.versions[mask_refinement["strategy"]] == "1.0.0"


def test_a_material_post_processing_change_needs_review() -> None:
    output = segmentation.resolve(
        _input(
            {
                "ana": [_instance("a1", CAT, _square(10, 10, 30), _square(60, 10, 4))],
                "bia": [_instance("b1", CAT, _square(10, 10, 30), _square(60, 10, 4))],
            },
            parameters={
                "post_processing": {
                    "remove_components_below": {"pixels": 2000, "image_ratio": 0.5}
                }
            },
        )
    )

    [candidate] = output.candidates
    assert "topology_invalid" in candidate.reasons
    assert candidate.objects == []


def test_a_second_round_adds_the_reviewer_mask() -> None:
    documents = {
        "ana": [_instance("a1", CAT, _square(10, 10, 20))],
        "bia": [_instance("b1", DOG, _square(10, 10, 20))],
    }
    first = segmentation.resolve(_input(documents))
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
            "geometry": {"type": "polygon", "coordinates": [_square(10, 10, 20)]},
        },
    )
    second = segmentation.resolve(
        _input(
            documents,
            candidates=[entry.model_dump(mode="json") for entry in first.candidates],
            reviews=[review],
        )
    )

    [candidate] = second.candidates
    assert candidate.passed is True
    assert candidate.metrics["supporting_masks"] == 3


def test_replay_is_byte_identical() -> None:
    documents = {
        "ana": [_instance("a1", CAT, _square(10, 10, 20), _square(14, 14, 6))],
        "bia": [_instance("b1", CAT, _square(11, 10, 20))],
        "caio": [_instance("c1", CAT, _square(10, 12, 19))],
    }
    first = segmentation.resolve(_input(documents))
    again = segmentation.resolve(_input(documents))

    assert protocol.fingerprint(first.model_dump(mode="json")) == protocol.fingerprint(
        again.model_dump(mode="json")
    )
