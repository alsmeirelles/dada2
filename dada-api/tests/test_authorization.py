"""Project role and action authorization matrix tests."""

import pytest

from dada_api.models.project import ProjectRole
from dada_api.services.authorization import ProjectAction, role_allows

EXPECTED_MATRIX = {
    (ProjectRole.owner, ProjectAction.read_project): True,
    (ProjectRole.owner, ProjectAction.update_project): True,
    (ProjectRole.owner, ProjectAction.activate_project): True,
    (ProjectRole.owner, ProjectAction.manage_classes): True,
    (ProjectRole.owner, ProjectAction.manage_members): True,
    (ProjectRole.owner, ProjectAction.annotate): True,
    (ProjectRole.owner, ProjectAction.revoke_lease): True,
    (ProjectRole.manager, ProjectAction.read_project): True,
    (ProjectRole.manager, ProjectAction.update_project): True,
    (ProjectRole.manager, ProjectAction.activate_project): False,
    (ProjectRole.manager, ProjectAction.manage_classes): True,
    (ProjectRole.manager, ProjectAction.manage_members): True,
    (ProjectRole.manager, ProjectAction.annotate): True,
    (ProjectRole.manager, ProjectAction.revoke_lease): True,
    (ProjectRole.annotator, ProjectAction.read_project): True,
    (ProjectRole.annotator, ProjectAction.update_project): False,
    (ProjectRole.annotator, ProjectAction.activate_project): False,
    (ProjectRole.annotator, ProjectAction.manage_classes): False,
    (ProjectRole.annotator, ProjectAction.manage_members): False,
    (ProjectRole.annotator, ProjectAction.annotate): True,
    (ProjectRole.annotator, ProjectAction.revoke_lease): False,
    (ProjectRole.viewer, ProjectAction.read_project): True,
    (ProjectRole.viewer, ProjectAction.update_project): False,
    (ProjectRole.viewer, ProjectAction.activate_project): False,
    (ProjectRole.viewer, ProjectAction.manage_classes): False,
    (ProjectRole.viewer, ProjectAction.manage_members): False,
    (ProjectRole.viewer, ProjectAction.annotate): False,
    (ProjectRole.viewer, ProjectAction.revoke_lease): False,
}


@pytest.mark.parametrize(("pair", "allowed"), sorted(EXPECTED_MATRIX.items()))
def test_every_role_action_pair(
    pair: tuple[ProjectRole, ProjectAction], allowed: bool
) -> None:
    role, action = pair
    assert role_allows(role, action) is allowed


def test_matrix_covers_every_pair() -> None:
    assert len(EXPECTED_MATRIX) == len(ProjectRole) * len(ProjectAction)
