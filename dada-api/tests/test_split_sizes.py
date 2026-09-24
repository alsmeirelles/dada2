"""Validation of dataset layouts, split definitions, and first-batch sizing."""

import pytest
from pydantic import ValidationError

from dada_api.models.project import Project
from dada_api.schemas.project import ProjectCreate
from dada_api.services.datasets import resolve_split_size, resolved_first_training_size


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


def test_split_defaults_to_random_acquisition_and_an_optional_first_batch() -> None:
    data = _project_request()
    del data["initial_training_size"]

    request = ProjectCreate.model_validate(data)

    assert request.dataset_layout == "split"
    assert request.acquisition_strategy == "random"
    assert request.initial_training_size is None


def test_split_requires_an_iteration_batch_size() -> None:
    data = _project_request()
    del data["iteration_batch_size"]

    with pytest.raises(ValidationError):
        ProjectCreate.model_validate(data)


def test_single_batch_takes_no_sizes() -> None:
    request = ProjectCreate.model_validate(
        {"name": "Static", "task_type": "detection", "dataset_layout": "single_batch"}
    )

    assert request.iteration_batch_size is None
    assert request.validation_set_size is None

    with pytest.raises(ValidationError):
        ProjectCreate.model_validate(
            {
                "name": "Static",
                "task_type": "detection",
                "dataset_layout": "single_batch",
                "iteration_batch_size": 3,
            }
        )


def test_single_batch_rejects_active_learning() -> None:
    with pytest.raises(ValidationError):
        ProjectCreate.model_validate(
            {
                "name": "Static",
                "task_type": "detection",
                "dataset_layout": "single_batch",
                "acquisition_strategy": "active_learning",
            }
        )


def test_the_first_training_batch_falls_back_to_the_iteration_size() -> None:
    assert (
        resolved_first_training_size(
            Project(initial_training_size=None, iteration_batch_size=3)
        )
        == 3
    )
    assert (
        resolved_first_training_size(
            Project(initial_training_size=7, iteration_batch_size=3)
        )
        == 7
    )
