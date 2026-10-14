"""Deterministic fake pipeline that scripts every worker outcome for tests."""

from dada_api.consensus.protocol import (
    Candidate,
    PipelineError,
    PipelineOutput,
    ResolverInput,
)

OUTCOMES = (
    "accept",
    "review",
    "review_two",
    "disagree",
    "invalid",
    "timeout",
    "unavailable",
    "error",
)


class ScriptedPipeline:
    """An adapter that returns or raises the next scripted outcome.

    ``accept`` passes one image case built from the first source's objects.
    ``review`` fails one candidate on a first round and passes it once review
    evidence is present; ``review_two`` does the same with two candidates.
    ``disagree`` fails one candidate whatever the evidence. ``invalid``
    returns geometry outside the image,
    ``timeout`` and ``unavailable`` raise typed permanent failures, and
    ``error`` raises an unexpected exception.

    Attributes:
        outcomes: Remaining outcomes, consumed in order; ``accept`` once empty.
        calls: Every input received, for assertions.
    """

    def __init__(self, *outcomes: str) -> None:
        unknown = set(outcomes) - set(OUTCOMES)
        if unknown:
            raise ValueError(f"unknown fake outcomes: {sorted(unknown)}")
        self.outcomes = list(outcomes)
        self.calls: list[ResolverInput] = []

    def __call__(self, resolver_input: ResolverInput) -> PipelineOutput:
        """Resolve one input according to the next scripted outcome."""
        self.calls.append(resolver_input)
        outcome = self.outcomes.pop(0) if self.outcomes else "accept"
        if outcome == "timeout":
            raise PipelineError("resource_limit", "scripted timeout")
        if outcome == "unavailable":
            raise PipelineError("resolver_unavailable", "scripted unavailability")
        if outcome == "error":
            raise RuntimeError("scripted resolver crash")

        objects = list(resolver_input.sources[0].objects)
        if outcome == "invalid":
            objects = [
                {
                    "id": "outside",
                    "class_id": resolver_input.class_ids[0],
                    "geometry": {
                        "type": "rectangle",
                        "coordinates": [0.0, 0.0, resolver_input.width * 2, 10.0],
                    },
                    "attributes": {},
                }
            ]
        if outcome in ("review", "review_two", "disagree"):
            reviewed = outcome != "disagree" and any(
                source.kind == "review" for source in resolver_input.sources
            )
            count = 2 if outcome == "review_two" else 1
            return PipelineOutput(
                candidates=[
                    Candidate(
                        key=f"c-fake-{ordinal}",
                        ordinal=ordinal,
                        scope="candidate",
                        passed=reviewed,
                        reasons=[] if reviewed else ["class_tie"],
                        objects=objects[ordinal : ordinal + 1] if reviewed else [],
                        region=[0.0, 0.0, 10.0, 10.0],
                    )
                    for ordinal in range(count)
                ],
                diagnostics={"fake": outcome},
                versions={"fake": "1.0.0"},
            )
        return PipelineOutput(
            candidates=[
                Candidate(
                    key="image",
                    ordinal=0,
                    scope="image",
                    passed=True,
                    objects=objects,
                )
            ],
            diagnostics={"fake": outcome},
            versions={"fake": "1.0.0"},
        )
