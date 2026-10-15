"""Versioned command, input, and result envelopes of the consensus worker."""

import hashlib
import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

PROTOCOL_VERSION = "consensus.v1"
FailureCode = Literal[
    "invalid_input",
    "resolver_output_invalid",
    "resolver_unavailable",
    "resource_limit",
    "worker_failed",
    "cancelled",
]


def fingerprint(value: Any) -> str:
    """Return the SHA-256 of a JSON value in DADA's canonical encoding.

    Args:
        value: Any JSON-serializable value.

    Returns:
        The hex digest of its sorted, compact JSON form.
    """
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


class Envelope(BaseModel):
    """A frozen protocol message that rejects unknown fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Command(Envelope):
    """What the broker transports: identifiers and fingerprints only.

    The worker loads every document itself and refuses to run when a
    fingerprint no longer matches what the database holds.
    """

    protocol_version: Literal["consensus.v1"] = PROTOCOL_VERSION
    run_id: str
    attempt: int
    configuration_fingerprint: str
    input_fingerprint: str


class Source(Envelope):
    """One human document entering a run.

    ``annotator_id`` is internal provenance used only by conditional
    strategies; nothing derived from it is returned to annotators.
    """

    kind: Literal["submission", "review"]
    id: str
    annotator_id: str
    annotator_index: int
    content_hash: str
    objects: list[dict[str, Any]] = []
    candidate_key: str | None = None
    evidence: dict[str, Any] | None = None


class ResolverInput(Envelope):
    """Everything a pure pipeline needs to resolve one image.

    ``candidates`` holds the frozen first-round candidates when the run
    evaluates review evidence; it is None for a first round.
    """

    pipeline: str
    pipeline_version: str
    task_type: Literal["classification", "detection", "segmentation"]
    configuration: dict[str, Any]
    width: int
    height: int
    class_ids: list[str]
    sources: list[Source]
    candidates: list[dict[str, Any]] | None = None
    calibration: dict[str, Any] | None = None


class Candidate(Envelope):
    """The decision a pipeline reached for one image-level or object-level case.

    ``objects`` is what the candidate contributes to the canonical document:
    the label objects of an image case, one object for an accepted candidate,
    or none when the decision is that nothing exists there.
    """

    key: str
    ordinal: int
    scope: Literal["image", "candidate"]
    passed: bool
    reasons: list[str] = []
    objects: list[dict[str, Any]] = []
    region: list[float] | None = None
    members: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {}


class PipelineOutput(Envelope):
    """A pipeline's proposal: one decision per candidate plus diagnostics."""

    candidates: list[Candidate]
    diagnostics: dict[str, Any] = {}
    versions: dict[str, str] = {}


class Result(Envelope):
    """What the worker hands back for one attempt of one run."""

    protocol_version: Literal["consensus.v1"] = PROTOCOL_VERSION
    run_id: str
    attempt: int
    configuration_fingerprint: str
    input_fingerprint: str
    outcome: Literal["proposal", "failed"]
    output: PipelineOutput | None = None
    output_checksum: str | None = None
    failure_code: FailureCode | None = None
    failure_detail: str | None = None
    started_at: datetime
    finished_at: datetime


class PipelineError(Exception):
    """A typed, permanent pipeline failure such as an unavailable strategy."""

    def __init__(self, code: FailureCode, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail
