"""Deterministic initial and candidate-review cohort selection."""

import pytest

from dada_api.services import cohort_selection


def test_initial_cohorts_are_stable_distinct_and_balanced() -> None:
    pool = ["a", "b", "c", "d"]

    first = [cohort_selection.initial_cohort(pool, index, 2) for index in range(8)]
    repeated = [cohort_selection.initial_cohort(pool, index, 2) for index in range(8)]

    assert first == repeated
    assert first[:4] == [
        ["a", "b"],
        ["b", "c"],
        ["c", "d"],
        ["d", "a"],
    ]
    assert all(len(cohort) == len(set(cohort)) == 2 for cohort in first)
    assert {member: sum(member in cohort for cohort in first) for member in pool} == {
        "a": 4,
        "b": 4,
        "c": 4,
        "d": 4,
    }


def test_review_cohort_uses_ordinal_and_never_reuses_evidence_authors() -> None:
    pool = ["a", "b", "c", "d", "e"]

    selected = cohort_selection.review_cohort(
        pool,
        item_position=1,
        initial_annotator_ids=["b", "c"],
        candidate_ordinal=2,
        required=1,
        earlier_reviewer_ids=["a"],
    )
    repeated = cohort_selection.review_cohort(
        pool,
        item_position=1,
        initial_annotator_ids=["b", "c"],
        candidate_ordinal=2,
        required=1,
        earlier_reviewer_ids=["a"],
    )

    assert selected == repeated == ["d"]
    assert set(selected).isdisjoint({"a", "b", "c"})


def test_review_cohort_refuses_to_reuse_a_reviewer() -> None:
    with pytest.raises(ValueError, match="do not fit"):
        cohort_selection.review_cohort(
            ["a", "b", "c"],
            item_position=0,
            initial_annotator_ids=["a", "b"],
            candidate_ordinal=0,
            required=1,
            earlier_reviewer_ids=["c"],
        )
