"""Packaged health fixtures an operator must pass to release a quarantined pipeline."""

from typing import Any

from dada_api.consensus import catalog, pipeline
from dada_api.consensus.protocol import ResolverInput, Source, fingerprint

CLASS_ID = "health-class"
GEOMETRIES: dict[str, dict[str, Any] | None] = {
    "classification": None,
    "detection": {"type": "rectangle", "coordinates": [10.0, 10.0, 40.0, 30.0]},
    "segmentation": {
        "type": "polygon",
        "coordinates": [[10.0, 10.0, 50.0, 10.0, 50.0, 40.0, 10.0, 40.0]],
    },
}
EXPECTED: dict[str, dict[str, Any] | None] = {
    **GEOMETRIES,
    "segmentation": {
        "type": "polygon",
        "coordinates": [[50.0, 10.0, 50.0, 40.0, 10.0, 40.0, 10.0, 10.0]],
    },
}


def fixture(task_type: str) -> ResolverInput:
    """Return three raters' identical documents for a task's pipeline.

    Args:
        task_type: Task type whose pipeline is checked.

    Returns:
        A first-round input with the pipeline's default configuration.
    """
    parameters, thresholds = catalog.normalize(task_type, {}, {})
    document = [
        {
            "id": "o1",
            "class_id": CLASS_ID,
            "geometry": GEOMETRIES[task_type],
            "attributes": {},
        }
    ]
    return ResolverInput(
        pipeline=catalog.pipeline_for(task_type).id,
        pipeline_version=catalog.VERSION,
        task_type=task_type,
        configuration={"parameters": parameters, "review_thresholds": thresholds},
        width=64,
        height=48,
        class_ids=[CLASS_ID],
        sources=[
            Source(
                kind="submission",
                id=f"health-{index}",
                annotator_id=f"health-rater-{index}",
                annotator_index=index,
                content_hash="health",
                objects=document,
            )
            for index in range(3)
        ],
    )


def passes(task_type: str) -> bool:
    """Return whether a task's pipeline accepts unanimous documents
    deterministically.

    A healthy pipeline turns three identical documents into passing decisions
    whose canonical document is exactly the known answer, and returns the same
    output twice. The segmentation answer is the shared square as re-traced
    from its mask.

    Args:
        task_type: Task type whose pipeline is checked.

    Returns:
        True when the fixture passes.
    """
    resolver_input = fixture(task_type)
    first, second = pipeline.run(resolver_input), pipeline.run(resolver_input)
    decided = [
        (entry["class_id"], entry["geometry"])
        for candidate in first.candidates
        for entry in candidate.objects
    ]
    return (
        fingerprint(first.model_dump(mode="json"))
        == fingerprint(second.model_dump(mode="json"))
        and all(candidate.passed for candidate in first.candidates)
        and decided == [(CLASS_ID, EXPECTED[task_type])]
    )
