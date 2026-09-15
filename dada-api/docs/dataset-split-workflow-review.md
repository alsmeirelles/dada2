# Dataset split workflow review

This report records the Phase 4 dataset workflow after the decisions made on
2026-09-15. It should be read with the [Phase 4 delivery
notes](phases/phase_4.md) and the [API implementation
plan](api-implementation-plan.md).

## Implemented workflow

Activation now creates a permanent three-way `train`/`validation`/`test`
split before annotation begins. Test is selected first from the deterministic
media inventory, validation is selected from the remainder, and train receives
everything left. The three memberships are committed atomically with project
activation and are not changed by a supported API operation.

Activation also creates three `preparing` annotation batches. Each batch
covers one complete split:

| Batch purpose | Membership | Size |
| --- | --- | --- |
| `initial_training` | Every image in `train` | Total media minus validation and test |
| `validation` | Every image in `validation` | Resolved validation size |
| `test` | Every image in `test` | Resolved test size |

Consequently, every image present at activation belongs to exactly one split
and exactly one initial annotation batch. A reusable
`first_acquisition_ready` service guard returns true only after all three
batches have assignments and none of those assignments remains `pending`.
The acquisition producer remains deferred, but it must call this guard before
opening the first acquisition round.

## Size definitions

`initial_training_size` remains an absolute minimum train capacity checked at
activation. It no longer truncates the initial training batch: that batch
covers the whole train split so acquisition cannot begin with unannotated
activation media.

Test and validation accept either an absolute item count or a percentage:

| Split | Absolute field | Percentage field |
| --- | --- | --- |
| Test | `test_set_size` | `test_set_percentage` |
| Validation | `validation_set_size` | `validation_set_percentage` |

Exactly one field in each row may be supplied. Percentages are greater than 0,
less than 100, and are converted at activation with
`ceil(total_media * percentage / 100)`. The resolved absolute counts are saved
in `test_set_size` and `validation_set_size`; later dataset changes do not
recalculate them. Requests from clients built before this adjustment receive a
one-image validation default, while new clients should send their choice
explicitly.

Activation requires enough media for the resolved validation and test counts
plus `initial_training_size`. `iteration_batch_size` remains an absolute count
and remains unused until acquisition is implemented.

## Activation sequence

```text
create draft project with count or percentage held-out sizes
    -> ingest media and create at least one class
    -> POST /projects/{id}/activate
       -> resolve percentage sizes against the current media total
       -> select test, then validation, then assign the remainder to train
       -> write one permanent DatasetSplit row per image
       -> create full train, validation, and test annotation batches
       -> snapshot the annotation policy on all three batches
       -> set project status to active and commit atomically
    -> start and complete all three batches
    -> first acquisition may start only when first_acquisition_ready is true
```

There is still no annotation before activation. This is intentional under the
revised decision: the earlier requested pre-split initial annotation sequence
is not being introduced.

## Reproducibility

Batch selection continues to record the random strategy, seed, deterministic
input fingerprint, requested size, and materialized items. The original seeds
used to choose split membership are still not stored separately. Durable rows
preserve the selected membership, but the original held-out draws cannot be
recomputed from full provenance. This known limitation is unchanged.

## Unchanged limitations and deferred work

- No API operation enlarges test or validation after activation.
- Uploads remain possible after activation and produce media without split or
  initial-batch membership.
- Split immutability remains an application convention rather than a database
  trigger.
- Iterations, acquisition production, training runs, model evaluation, minor
  evaluation configuration, and broader evaluation cadence remain deferred.
- Validation is now structurally available, but no model-run implementation
  consumes it yet.

## Adherence after the adjustment

| Required behavior | Current state |
| --- | --- |
| Fixed train/validation/test membership | Implemented atomically at activation |
| Absolute or percentage held-out sizes | Implemented; percentages resolve to saved absolute counts at activation |
| Annotation work includes all three sets | Implemented as three full-coverage batches |
| First acquisition waits for all initial annotations | Guard implemented; acquisition producer remains deferred |
| Pre-split initial annotation | Deliberately unsupported under the revised decision |
| Test or validation enlargement | Unsupported, unchanged |
| Reproducible original split draw | Membership is durable; original split-selection seeds remain unstored |
| Evaluation timing and cadence | Deferred |

Phase 4 now establishes the three fixed annotated sets and the acquisition
precondition. It does not implement the later learning or evaluation lifecycle.
