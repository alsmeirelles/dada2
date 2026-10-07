"""Versioned deterministic selectors for initial and review cohorts."""

INITIAL_ALGORITHM = "initial_round_robin_v1"
REVIEW_ALGORITHM = "review_round_robin_v1"
REASSIGNMENT_ALGORITHM = "manager_reassignment_v1"


def initial_cohort(
    ordered_pool: list[str], item_position: int, required: int
) -> list[str]:
    """Select consecutive pool members, rotating once per item."""
    if required < 1 or required > len(ordered_pool):
        raise ValueError("required must fit the ordered pool")
    start = item_position % len(ordered_pool)
    return [
        ordered_pool[(start + offset) % len(ordered_pool)] for offset in range(required)
    ]


def review_cohort(
    ordered_pool: list[str],
    *,
    item_position: int,
    initial_annotator_ids: list[str],
    candidate_ordinal: int,
    required: int,
    earlier_reviewer_ids: list[str] | None = None,
) -> list[str]:
    """Select independent reviewers while deterministically skipping exclusions."""
    excluded = set(initial_annotator_ids) | set(earlier_reviewer_ids or [])
    if required < 1 or len(ordered_pool) - len(excluded) < required:
        raise ValueError("required reviewers do not fit after exclusions")

    start = (item_position + len(initial_annotator_ids) + candidate_ordinal) % len(
        ordered_pool
    )
    selected: list[str] = []
    for offset in range(len(ordered_pool)):
        candidate = ordered_pool[(start + offset) % len(ordered_pool)]
        if candidate not in excluded:
            selected.append(candidate)
            if len(selected) == required:
                return selected
    raise ValueError("unable to select the required review cohort")
