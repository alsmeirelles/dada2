"""The packaged health fixtures that gate an operator's quarantine release."""

import pytest

pytest.importorskip("scipy")
pytest.importorskip("cv2")
pytest.importorskip("crowdkit")

from dada_api.consensus import health, pipeline  # noqa: E402
from dada_api.consensus.fake import ScriptedPipeline  # noqa: E402


@pytest.mark.parametrize("task_type", ["classification", "detection", "segmentation"])
def test_every_installed_pipeline_passes_its_health_fixture(task_type: str) -> None:
    assert health.passes(task_type)


@pytest.mark.parametrize("outcome", ["disagree", "invalid"])
def test_a_pipeline_that_rejects_unanimity_fails_its_health_fixture(
    outcome: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline, "run", ScriptedPipeline(outcome, outcome))

    assert not health.passes("detection")
