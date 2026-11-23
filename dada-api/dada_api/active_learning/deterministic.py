"""Deterministic development solution that exercises the loop without a model.

It is registered only in the development and test environments (D11). It
ranks the pool by a hash of the seed and each media id, and reports a
synthetic metric equal to the share of known images already labelled, so the
same request always gives the same answer and the metric grows with every
iteration.
"""

import hashlib
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from dada_api.active_learning.contract import (
    MANIFEST_SCHEMA,
    BaseModelAdapter,
    BatchRequest,
    BatchResult,
    Evaluation,
    StageReporter,
    read_manifest,
)

SOLUTION_ID = "deterministic"
SOLUTION_VERSION = "1.0.0"


class DeterministicConfiguration(BaseModel):
    """Settings of the deterministic solution."""

    model_config = ConfigDict(extra="forbid")

    retain_helper_models: bool = Field(
        default=False,
        description="Keep the per-attempt artifact folders after a success.",
    )


def _rank(seed: int, media_id: str) -> str:
    """Return the stable sort key of one candidate."""
    return hashlib.sha256(f"{seed}:{media_id}".encode()).hexdigest()


class DeterministicAdapter(BaseModelAdapter):
    """Reproducible selection and evaluation for development and tests."""

    def select_batch(
        self, request: BatchRequest, report_stage: StageReporter | None = None
    ) -> BatchResult:
        """Evaluate synthetically and choose the first ranked candidates.

        Args:
            request: Immutable request of one attempt.
            report_stage: Optional progress callback.

        Returns:
            The evaluations and the chosen batch.
        """
        report = report_stage or (lambda _: None)
        report("training")
        training = read_manifest(request.media_root, request.training)
        pool = (
            read_manifest(request.media_root, request.pool)
            if request.pool is not None
            else None
        )
        labelled = len(training["images"])
        unlabelled = len(pool["images"]) if pool is not None else 0
        value = round(labelled / max(labelled + unlabelled, 1), 6)

        evaluations: list[Evaluation] = []
        plan = request.evaluation
        stop = False
        if plan is not None:
            report("evaluating")
            evaluations.append(self._evaluation("validation", plan.metric, value))
            stop = plan.target is not None and value >= plan.target
            if plan.final or stop:
                evaluations.append(self._evaluation("test", plan.metric, value))

        if request.purpose == "final_evaluation" or stop or pool is None:
            return self._result(request, None, None, evaluations, stop)

        report("selecting")
        ranked = sorted(
            pool["images"], key=lambda image: _rank(request.seed, image["id"])
        )
        chosen = ranked[: request.requested_size]
        selection = {
            "info": {**pool["info"], "role": "selection", "schema": MANIFEST_SCHEMA},
            "categories": pool["categories"],
            "images": chosen,
            "annotations": [],
        }
        shortfall = (
            "insufficient_candidates" if len(chosen) < request.requested_size else None
        )
        return self._result(request, selection, shortfall, evaluations, False)

    @staticmethod
    def _evaluation(split: str, metric: str, value: float) -> Evaluation:
        """Build one synthetic evaluation."""
        return Evaluation(
            split=split,
            metric=metric,
            value=value,
            metrics={metric: value},
            model={"name": SOLUTION_ID, "version": SOLUTION_VERSION},
        )

    @staticmethod
    def _result(
        request: BatchRequest,
        selection: dict[str, Any] | None,
        shortfall: str | None,
        evaluations: list[Evaluation],
        stop: bool,
    ) -> BatchResult:
        """Build the result envelope."""
        return BatchResult(
            request_id=request.request_id,
            solution_id=SOLUTION_ID,
            solution_version=SOLUTION_VERSION,
            selection=selection,
            shortfall_reason=shortfall,
            stop_reason="metric_target" if stop else None,
            evaluations=evaluations,
            provenance={"ranking": "sha256(seed:media_id)", "seed": request.seed},
        )
