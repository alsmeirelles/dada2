"""The ``statistical_class_consensus`` pipeline on hand-built inputs."""

import pytest
from pydantic import ValidationError

pytest.importorskip("scipy")

from dada_api.consensus import catalog, classification  # noqa: E402
from dada_api.consensus.protocol import (  # noqa: E402
    PipelineError,
    ResolverInput,
    Source,
)

CAT, DOG = "class-cat", "class-dog"


def _labels(*class_ids: str) -> list[dict]:
    """Return a classification document with the given classes."""
    return [
        {"id": f"l{index}", "class_id": class_id, "geometry": None, "attributes": {}}
        for index, class_id in enumerate(class_ids)
    ]


def _input(
    documents: dict[str, list[str]],
    reviews: dict[str, list[str]] | None = None,
    parameters: dict | None = None,
) -> ResolverInput:
    """Return a classification input with one submission per rater."""
    normalized, thresholds = catalog.normalize("classification", parameters or {}, {})
    sources = [
        Source(
            kind="submission",
            id=f"s-{rater}",
            annotator_id=rater,
            annotator_index=index,
            content_hash="h",
            objects=_labels(*classes),
        )
        for index, (rater, classes) in enumerate(documents.items())
    ]
    sources += [
        Source(
            kind="review",
            id=f"r-{rater}",
            annotator_id=rater,
            annotator_index=len(documents) + index,
            content_hash="h",
            candidate_key="image",
            evidence={"class_ids": classes},
        )
        for index, (rater, classes) in enumerate((reviews or {}).items())
    ]
    return ResolverInput(
        pipeline="statistical_class_consensus",
        pipeline_version="1.0.0",
        task_type="classification",
        configuration={"parameters": normalized, "review_thresholds": thresholds},
        width=640,
        height=480,
        class_ids=[CAT, DOG],
        sources=sources,
    )


def test_unanimous_labels_pass_as_one_image_case() -> None:
    output = classification.resolve(_input({"ana": [CAT], "bia": [CAT]}))

    [candidate] = output.candidates
    assert (candidate.key, candidate.scope, candidate.passed) == (
        "image",
        "image",
        True,
    )
    assert [entry["class_id"] for entry in candidate.objects] == [CAT]
    assert all(entry["geometry"] is None for entry in candidate.objects)
    classes = candidate.metrics["classes"]
    assert classes[CAT]["outcome"] == "positive"
    assert classes[DOG]["outcome"] == "negative"
    assert output.diagnostics["observation_matrix"] == {
        CAT: {"ana": "positive", "bia": "positive"},
        DOG: {"ana": "negative", "bia": "negative"},
    }


def test_partial_multilabel_agreement_needs_review() -> None:
    output = classification.resolve(_input({"ana": [CAT], "bia": [CAT, DOG]}))

    [candidate] = output.candidates
    assert candidate.passed is False
    assert candidate.reasons == ["class_tie"]
    assert [entry["class_id"] for entry in candidate.objects] == [CAT]
    assert candidate.metrics["classes"][DOG]["outcome"] is None


def test_an_image_with_no_supported_class_goes_to_review() -> None:
    output = classification.resolve(
        _input({"ana": [CAT], "bia": [DOG], "caio": ["class-bird"]})
    )

    [candidate] = output.candidates
    assert candidate.passed is False
    assert candidate.objects == []
    assert "support_below_threshold" in candidate.reasons


def test_review_evidence_adds_votes_in_the_second_round() -> None:
    output = classification.resolve(
        _input({"ana": [CAT], "bia": [CAT, DOG]}, reviews={"caio": [CAT]})
    )

    [candidate] = output.candidates
    assert candidate.passed is True
    assert [entry["class_id"] for entry in candidate.objects] == [CAT]
    assert output.diagnostics["observation_matrix"][DOG]["caio"] == "negative"


def test_the_dirichlet_strategy_uses_the_posterior_gate() -> None:
    output = classification.resolve(
        _input(
            {"ana": [CAT], "bia": [CAT]},
            parameters={"class_strategy": {"strategy": "dirichlet_vote", "alpha": 10}},
        )
    )

    [candidate] = output.candidates
    assert candidate.passed is False
    assert "posterior_below_threshold" in candidate.reasons
    assert output.versions["dirichlet_vote"] == "1.0.0"


def test_a_conditional_strategy_without_its_snapshot_is_unavailable() -> None:
    with pytest.raises(PipelineError) as raised:
        classification.resolve(
            _input(
                {"ana": [CAT], "bia": [CAT]},
                parameters={"class_strategy": {"strategy": "dawid_skene"}},
            )
        )
    assert raised.value.code == "resolver_unavailable"


def test_model_derived_evidence_cannot_enter_a_run() -> None:
    with pytest.raises(ValidationError):
        Source(
            kind="model_prediction",
            id="m",
            annotator_id="model",
            annotator_index=0,
            content_hash="h",
        )


def test_replay_is_deterministic_and_order_independent() -> None:
    first = classification.resolve(_input({"ana": [CAT, DOG], "bia": [DOG]}))
    again = classification.resolve(_input({"ana": [CAT, DOG], "bia": [DOG]}))
    swapped = classification.resolve(_input({"bia": [DOG], "ana": [DOG, CAT]}))

    assert first == again
    assert first.candidates[0].model_dump() == swapped.candidates[0].model_dump()
