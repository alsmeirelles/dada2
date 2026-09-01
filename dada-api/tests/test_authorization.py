"""Project role and action authorization matrix tests."""

import pytest

from dada_api.models.project import ProjectRole
from dada_api.services.authorization import ProjectAction, role_allows

MANAGER_DENIED = {ProjectAction.activate_project, ProjectAction.delete_project}
ANNOTATOR_ALLOWED = {ProjectAction.read_project, ProjectAction.annotate}
VIEWER_ALLOWED = {ProjectAction.read_project}

EXPECTED_MATRIX = {
    **{(ProjectRole.owner, action): True for action in ProjectAction},
    **{
        (ProjectRole.manager, action): action not in MANAGER_DENIED
        for action in ProjectAction
    },
    **{
        (ProjectRole.annotator, action): action in ANNOTATOR_ALLOWED
        for action in ProjectAction
    },
    **{
        (ProjectRole.viewer, action): action in VIEWER_ALLOWED
        for action in ProjectAction
    },
}


@pytest.mark.parametrize(("pair", "allowed"), sorted(EXPECTED_MATRIX.items()))
def test_every_role_action_pair(
    pair: tuple[ProjectRole, ProjectAction], allowed: bool
) -> None:
    role, action = pair
    assert role_allows(role, action) is allowed


def test_matrix_covers_every_pair() -> None:
    assert len(EXPECTED_MATRIX) == len(ProjectRole) * len(ProjectAction)


def test_delete_project_is_owner_only() -> None:
    action = ProjectAction.delete_project
    assert role_allows(ProjectRole.owner, action) is True
    assert role_allows(ProjectRole.manager, action) is False
    assert role_allows(ProjectRole.annotator, action) is False
    assert role_allows(ProjectRole.viewer, action) is False


def test_manager_actions_added_in_phase_two() -> None:
    added = {
        ProjectAction.manage_annotation_policy,
        ProjectAction.read_annotation_evidence,
        ProjectAction.run_resolution,
        ProjectAction.adjudicate,
        ProjectAction.read_annotator_performance,
    }
    assert added <= set(ProjectAction)
    for action in added:
        assert role_allows(ProjectRole.owner, action) is True
        assert role_allows(ProjectRole.manager, action) is True
        assert role_allows(ProjectRole.annotator, action) is False
        assert role_allows(ProjectRole.viewer, action) is False
