"""Validation of count and percentage split definitions."""

import pytest
from pydantic import ValidationError

from dada_api.schemas.project import ProjectCreate
from dada_api.services.projects import resolve_split_size


def _project_request(**overrides: object) -> dict[str, object]:
    return {
        "name": "Road defects",
        "task_type": "detection",
        "initial_training_size": 5,
        "test_set_size": 4,
        "validation_set_size": 2,
        "iteration_batch_size": 3,
        **overrides,
    }


def test_percentage_resolution_rounds_up_to_a_whole_image() -> None:
    assert resolve_split_size(12, None, 20) == 3
    assert resolve_split_size(12, 4, None) == 4


def test_project_accepts_percentage_held_out_sizes() -> None:
    request = ProjectCreate.model_validate(
        _project_request(
            test_set_size=None,
            test_set_percentage=25,
            validation_set_size=None,
            validation_set_percentage=20,
        )
    )

    assert request.test_set_percentage == 25
    assert request.validation_set_percentage == 20


def test_project_rejects_count_and_percentage_for_the_same_split() -> None:
    with pytest.raises(ValidationError):
        ProjectCreate.model_validate(_project_request(test_set_percentage=25))


def test_old_project_request_gets_one_image_validation_default() -> None:
    data = _project_request()
    del data["validation_set_size"]

    assert ProjectCreate.model_validate(data).validation_set_size == 1
