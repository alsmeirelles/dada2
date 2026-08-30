"""Consensus resolver registry tests."""

from dada_api.services import resolvers


def test_every_task_type_advertises_at_least_one_resolver() -> None:
    for task_type in ("classification", "detection", "segmentation"):
        assert resolvers.resolvers_for_task(task_type)


def test_resolvers_do_not_cross_task_types() -> None:
    assert resolvers.supports("classification", "majority_vote") is True
    assert resolvers.supports("detection", "majority_vote") is False
    assert resolvers.supports("segmentation", "two_stage_box_fusion") is False


def test_unknown_task_advertises_nothing() -> None:
    assert resolvers.resolvers_for_task("video") == ()
    assert resolvers.supports("video", "majority_vote") is False
