"""Consensus resolver identifiers the API advertises and accepts per task.

These identifiers are provisional. The plan assigns the final vocabulary,
parameter schemas, and package versions to Phase 6, so this registry exists in
one place to keep renaming it a single edit plus a data migration.
"""

RESOLVERS_BY_TASK: dict[str, tuple[str, ...]] = {
    "classification": ("majority_vote",),
    "detection": ("two_stage_box_fusion",),
    "segmentation": ("two_stage_mask_fusion",),
}


def resolvers_for_task(task_type: str) -> tuple[str, ...]:
    """Return the resolver identifiers valid for a task type.

    Args:
        task_type: Project task type.

    Returns:
        The advertised identifiers, empty when the task is unknown.
    """
    return RESOLVERS_BY_TASK.get(task_type, ())


def supports(task_type: str, resolver: str) -> bool:
    """Return whether a resolver is advertised for a task type.

    Args:
        task_type: Project task type.
        resolver: Requested resolver identifier.

    Returns:
        True when the identifier is advertised for that task.
    """
    return resolver in resolvers_for_task(task_type)
