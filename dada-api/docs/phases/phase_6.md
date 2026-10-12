# Phase 6 pending decisions

This is the canonical register for all Phase 6 decisions. The API
implementation plan and App adaptation plan link here rather than duplicating
these entries.

Text labeled **pending confirmation** is a recommended decision, not an
approved one. On confirmation, replace that label with the approver and date
and merge the recommendation into the corresponding decision.

## API decisions

| ID | Decision area | Required documented outcome |
| --- | --- | --- |
| `P6-01` | Resolver/package catalog | Native statistical class-resolution algorithms, crowd-kit mask-refinement versions, resolver versions, pipeline IDs, dependency isolation, compatibility policy, applicability gates, and capability fallback behavior |
| `P6-02` | Resolver configuration and quality gates | Typed parameters, defaults/bounds, task-specific thresholds, calibration dataset and approval evidence, tie/ambiguity rules, and migration from provisional policy IDs |
| `P6-03` | Segmentation refinement implementation | Maintained STAPLE dependency or approved internal implementation, supported crowd-kit strategies, rasterization/polygonization libraries, and reference fixtures |
| `P6-04` | Adjudicator independence | Whether a contributor may adjudicate the same item, conflict disclosure, role restrictions, optional independent-adjudicator mode, and audit fields |
| `P6-05` | Resolution job execution | Worker/queue topology, command/result envelopes, timeouts, retry/backoff limits, cancellation, stale/duplicate result handling and permanent-failure recovery |
| `P6-06` | Resolution acceptance/versioning | Automatic acceptance criteria, proposal vs. accepted states, retry configuration/version conflicts, supersession, one-active-result invariant, and adjudication precedence |
| `P6-07` | Evidence and performance policy | Raw evidence retention/access, raw-to-canonical mapping rules, observation eligibility, privacy/minimum-sample rules, and behavior when a resolution is superseded |
| `P6-08` | Resolution work-item and lease policy | Image-case versus derived object/instance work-item identity; creation, closure, and provenance; which manual review actions require a resolution lease; lease duration/renewal/revocation; and concurrent-adjudication conflict handling |

### P6-01 decision

Class and existence resolution is model-free for classification, detection, and
segmentation. It uses versioned DADA implementations over human annotation
observations only. A class resolver must not import Cleanlab/CROWDLAB or accept
model predictions, predicted probabilities, embeddings, or model seeds as
evidence. The same rule applies when `no_object` is included as a categorical
observation for detection and segmentation candidates.

The target top-level pipeline identifiers are
`statistical_class_consensus`, `two_stage_detection_consensus`, and
`two_stage_segmentation_consensus`. Their class-resolution sub-strategies are
advertised as a typed discriminated union through capabilities. The catalog is
approved for Phase 6 implementation:

| Strategy | Applicability | Eligibility and behavior |
| --- | --- | --- |
| `categorical_vote` | Single-label classification and candidate class/existence | Deterministic plurality, strict-majority, or configured supermajority; a tie or failed support gate requires review. |
| `multilabel_binary_vote` | Multi-label classification | Runs an explicit positive/negative decision per class with independently recorded support and thresholds. |
| `dirichlet_vote` | Single-label and per-class binary decisions | Uses a frozen prior and human vote counts to produce a posterior decision and uncertainty diagnostics. |
| `reliability_weighted_vote` | Single-label and per-class binary decisions | Available only with frozen annotator weights derived from independent gold or expert-adjudicated evidence; the current item and self-reinforcing automated consensus cannot establish its weights. |
| `dawid_skene` | Single-label and per-class binary decisions | Available only with a sufficient multi-item human-label corpus and a frozen, versioned parameter snapshot; it is unavailable when identifiability, coverage, or convergence gates fail. |

GLAD and independent Bayesian classifier combination are candidates for a later
native adapter after their identifiability, corpus-size, convergence, and
operational costs are specified. They are not advertised until approved.
There is no silent fallback between strategies.

Phase 6 implements `categorical_vote`, `multilabel_binary_vote`, and
`dirichlet_vote` as the initial strategies. It also implements
`reliability_weighted_vote` and `dawid_skene` as conditional strategies whose
project/batch eligibility is validated before dispatch. A conditional strategy
that lacks the required evidence remains unavailable; this does not defer its
implementation or permit fallback to an initial strategy.

crowd-kit remains an optional dependency only for Stage 2 segmentation mask
refinement. It does not resolve class labels or candidate existence. Version
`1.4.2` is the current compatibility baseline; production uses an exact pinned
and fixture-validated version, and a newer version requires explicit
compatibility validation before it is advertised.



- Release the three top-level pipelines at resolver version `1.0.0`. Record the
  pipeline, strategy, and implementation versions separately so a new strategy
  does not obscure which algorithm produced an older result.
- Pin crowd-kit to `==1.4.2` in the isolated consensus-worker dependency group.
  Accept an upgrade only after all compatibility and golden fixtures pass; do
  not use an open-ended `or newer` production constraint.
- Apply semantic versioning to native resolver implementations. A configuration
  break increments the major version, a backward-compatible strategy addition
  increments the minor version, and a compatible correction increments the
  patch version. Every output records the exact version, including patches.
- Keep an installed but quarantined or project-ineligible strategy visible in
  capabilities with a typed unavailable reason. Never substitute a different
  strategy or dependency version.

This keeps policies stable while allowing old results to remain replayable.

### P6-02 decision

Outputs pass automatically only when every project-defined, task-specific
criterion and threshold in the frozen batch policy is met. The policy records
`required_consensus_annotations`, `required_consensus_reviewers`, registered
resolver settings, and typed quality gates. The initial worker run evaluates
the selected initial cohort; a candidate that falls short receives the frozen
reviewer count and is evaluated again with the original and review evidence.

Class quality gates use only diagnostics derived from the submitted human
observations and the selected statistical algorithm, such as support ratio,
vote margin, normalized entropy, posterior probability, or posterior credible
bounds. Algorithm-specific parameters and applicability gates are a closed,
typed schema. Cross-item algorithms also record the immutable calibration
corpus and parameter-snapshot identity. An ineligible strategy returns
`resolver_unavailable` and never substitutes another algorithm. A model output
cannot satisfy or increase a class quality gate.

The algorithm catalog and implementation phase are decided. P6-02 must still
freeze each strategy's numeric defaults and bounds, Dirichlet priors, minimum
sample and class-coverage rules, reliability-weight derivation, Dawid-Skene
initialization/convergence limits, and threshold calibration evidence before
the resolver catalog is approved for production use.

Use these first-release defaults and bounds:

- Express vote thresholds as exact integer ratios and compare by cross
  multiplication. Default `minimum_support` to `2/3`, inclusive; allow project
  values strictly greater than `1/2` and at most `1`. A tie always requires
  review. Entropy and vote margin remain diagnostics by default rather than
  additional gates.
- Default `categorical_vote` to `supermajority`. `plurality` may be selected
  only with the common support gate, so a unique but weak plurality cannot pass
  automatically. Default `multilabel_binary_vote` to the same `2/3` positive
  and negative thresholds per class; a class meeting neither threshold
  requires review.
- Use a symmetric Jeffreys prior (`alpha = 0.5` per outcome) for
  `dirichlet_vote`. Require both raw support of at least `2/3` and posterior
  probability that the selected outcome has the largest latent response
  probability of at least `0.90`; expose both values. Allow `alpha` in
  `[0.1, 10]` and the posterior gate in `[0.5, 0.999]`.
- Derive `reliability_weighted_vote` weights only from independent gold or
  expert-adjudicated outcomes. Require at least 30 eligible decisions per
  annotator and at least 5 observations for every outcome used by the weight;
  apply a `Beta(2,2)` smoothing prior, normalize mean weight to `1`, and clip
  individual weights to `[0.5, 2.0]`. Automatic acceptance also requires an
  unweighted strict majority so one historical weight cannot override all
  current human votes.
- Make `dawid_skene` eligible only with at least 50 calibration items, at least
  3 independent raters per calibration item, at least 20 eligible observations
  per included annotator, and at least 5 observations per class/outcome.
  Initialize deterministically from majority vote, use additive smoothing of
  `1`, stop at log-likelihood change below `1e-6` or 100 iterations, and require
  posterior probability of at least `0.90` plus an unweighted strict majority.
- Default detection candidate matching and accepted-box median pairwise IoU to
  `0.50`. Default segmentation matching to either IoU `0.50` or Dice `2/3`,
  chosen explicitly by the policy, and the output pixel threshold to `0.50`.
  Do not average IoU and Dice implicitly.
- Compare continuous metrics after deterministic quantization to six decimal
  places, with equality passing an inclusive threshold. Reject non-finite
  values before comparison.

Validate these defaults against committed synthetic edge fixtures and a
versioned, representative adjudicated calibration set before production
approval. Project overrides create a new policy version and cannot weaken the
hard majority, evidence-independence, or eligibility rules above.

Owners/managers may change thresholds or metrics only for a later policy
version and batches still in `preparing`. A change never alters an active
cohort, worker input snapshot, or accepted resolution. Refer to the
[Consensus Engine Requirements](../consensus-engine-requirements.md), task
annexes, and [Phase 5.1](phase_5.1.md).

### P6-03 decision

The user should be able to choose from simple IoU or Dice with specified thresholds to keep overlapping regions or use provided
crowd-kit functionalities for segmentation mask refinement. These strategies run only after native statistical resolution has
accepted an instance's existence and class; they do not contribute class votes or class confidence. Refer to decision P6-02 and
specific consensus documents in docs/consensus.


- Advertise crowd-kit's `SegmentationMajorityVote` and `SegmentationEM` in the
  first release. Advertise `SegmentationRASA` only after its resource profile
  and reference fixtures pass the Phase 6 limits; otherwise return a typed
  unavailable reason.
- Implement STAPLE as a versioned native DADA mask-refinement strategy using
  NumPy/SciPy, rather than adding another opaque runtime dependency. Validate it
  against published-formula reference fixtures and independent golden masks.
- Put rasterization and polygonization in the isolated consensus-worker group
  with an exact pinned OpenCV-headless version. Use original-image dimensions,
  an even-odd polygon fill rule, explicit ring orientation, and contour
  hierarchy that preserves holes. Record the library and algorithm versions.
- Disable component removal, hole filling, and polygon simplification by
  default. When enabled, express area thresholds in both pixels and image-area
  ratio, preserve the raw aggregate-mask checksum, and require review when
  topology or area changes by more than 20%.
- Keep matching metric, aggregation strategy, pixel threshold, and
  post-processing as separate typed settings. No geometry strategy may change
  the class/existence decision from Stage 1.

### P6-04 decision
Only managers and owners can adjudicate on their own annotations or over annotator's data. Annotators have no way to resolve
annotations without passing through consensus, and they don't see the consensus data while it's still being decided. Annotator's
can see the final annotations after consensus is reached.


- Add `require_independent_adjudicator`, default `false`, to the project policy.
  With the default, an owner or manager who contributed evidence may adjudicate,
  but the UI must disclose the conflict and require a rationale. When enabled,
  any contributor to the item is blocked from accepting, editing, replacing, or
  adjudicating it; the case remains pending until an eligible owner/manager is
  available.
- Never permit an annotator-only role to adjudicate. Promotion to manager does
  not erase contribution history for the item.
- Audit adjudicator role, contribution submission IDs, conflict boolean,
  independence-policy version, action, rationale, and resulting resolution
  version. Do not add a hidden emergency override to strict independence.

### P6-05 decision

The consensus dispatch sequence is decided. When all members of an image's
frozen initial cohort submit, Phase 5.1 atomically writes exactly one
`consensus.initial_evidence_ready.v1` domain event for the batch item and cohort
generation. Phase 6 consumes that event and creates an idempotent worker command
that resolves every candidate in the image. If all automatic gates pass, the
image resolves. If a classification result or detection/segmentation candidate
falls short, create
the configured number of independent scoped review assignments; after all
review submissions arrive, dispatch a second worker command over the original
and review evidence. Candidates still below threshold require expert
adjudication. The batch resolves only after every non-cancelled image resolves.

- Use at-least-once delivery. Commands and results carry a protocol version,
  job/run IDs, input and configuration fingerprints, attempt number,
  pipeline/adapter/dependency versions, outcome, diagnostics/artifact
  references, output checksum, timings, and typed failure code. They carry IDs
  and hashes, never ORM objects.
- Allow one active job per item/configuration fingerprint through a database
  constraint. Duplicate delivery is harmless; duplicate or stale results never
  change state.
- Retry only transient failures: worker crash, broker/transport failure, or
  database connectivity loss. Use three total attempts with 1-minute and
  5-minute backoff. Invalid inputs, invalid resolver output, unavailable
  capability, and resource-limit failures become permanent failures
  immediately.
- A manager may cancel a queued/running run. Cancellation is cooperative, then
  force-stops after a short grace period; it preserves evidence and moves the
  case to manual review or an explicit retry.
- A permanent failure preserves the run, error classification, and provenance.
  A manager may retry with a currently registered configuration and expected
  version, or adjudicate manually. Operators may quarantine a faulty adapter
  version.
- The worker returns a proposal or `review_required`; the API transaction
  decides automatic acceptance from the frozen configuration gates. This
  preserves the proposal/accepted distinction required by P6-06.


- Use dedicated Celery queues: `consensus.standard` for classification and
  detection, and `consensus.mask` for segmentation. Keep them separate from
  Phase 7 learning workers. Redis transports commands; PostgreSQL remains the
  authoritative job and state store.
- Default standard jobs to a 5-minute hard timeout and 1 GiB memory limit, and
  mask jobs to a 15-minute hard timeout and 4 GiB. Send cooperative cancellation
  30 seconds before the hard limit. Make deployment limits configurable only
  within operator-set ceilings and record the effective values per run.
- Default worker concurrency to at most four standard jobs and one mask job per
  worker host, with per-project caps of two standard jobs and one mask job.
  Queueing above those caps is normal and does not create another active run.
- Retain inputs, normalized-input hashes, proposals, accepted/superseded
  outputs, required replay artifacts, and failure diagnostics for the project
  lifetime. Delete disposable temporary files within 24 hours. Operational
  logs follow the Phase 8 retention policy and never substitute for provenance.
- Automatically quarantine one pipeline/strategy version after five invalid
  outputs or resource-limit failures in ten minutes. In-flight result ingestion
  remains fingerprint-checked; new dispatches fail with `resolver_unavailable`.
  Operator re-enable requires an audit reason and a passing health fixture.

### P6-06 decision
Automatic acceptance is the default when the relevant initial or review run
meets every frozen threshold. The resolver output is persisted as a
**resolution proposal** and the acceptance transaction creates the immutable
canonical resolution, preserving both states and provenance. A resolution
proposal is produced only by the consensus worker after the evidence snapshot has been
evaluated, and is accepted or adjudicated only by an authorized expert.

A **model seed** is separate Phase 7 preparation work. After active learning
selects the next batch, a completed model run may create an optional starting
annotation in each selected annotator's draft during batch preparation. It does
not count as a submission, consensus vote, resolution proposal, or canonical resolution;
only the annotator's saved submission enters the normal consensus flow.


- Persist every valid worker proposal before evaluating automatic acceptance,
  then create the accepted immutable resolution in the same transaction as the
  threshold decision and events. The system actor performs automatic
  acceptance; owners/managers perform manual acceptance or adjudication.
- A retry always creates a new run and proposal. A failed or review-required
  retry does not displace the current accepted resolution. A successful
  accepted retry atomically supersedes the previous accepted version while
  preserving its history and observations.
- Require expected evidence generation, configuration version, and accepted
  resolution version on retry, acceptance, and adjudication. Return `409` for
  any mismatch. Repeating an idempotency key returns the original result.
- Manual adjudication has precedence over automation. A later automatic run may
  produce diagnostics and a proposal, but it cannot supersede an adjudicated
  version without an explicit owner/manager acceptance and rationale.
- Exactly one accepted version is current per image. Derived candidate work
  items close into one new parent-image resolution version; the parent becomes
  accepted only when every blocking work item is closed.

### P6-07 decision

Retain all raw evidence indefinitely (as long as the project is not deleted). Annotators can see if an annotation was reached
through natural consensus, defined by the expert, adjudicated by manager/owner.


- Retain raw submissions, proposals, canonical versions, mappings, required
  replay artifacts, and audit/provenance for the project lifetime. Project
  deletion follows the existing deletion policy; no independent evidence purge
  may leave a canonical resolution without its provenance.
- Give every source object an explicit mapping outcome: retained, class-changed,
  false-positive, missed-object, duplicate, ambiguous, invalid, or not
  applicable. Never infer a zero geometry score for an unmatched object.
- Keep superseded performance observations immutable. Mark their summary
  eligibility closed when the resolution is superseded, then rebuild current
  summaries idempotently from the new accepted version.
- Use only independent gold and expert-adjudicated observations for
  reliability weights in Phase 6. Automated-consensus observations remain
  descriptive and cannot weight any contributor to that same result.
- Restrict named performance evidence to owners/managers and authorized global
  administrators. Suppress named aggregates below 30 eligible decisions
  overall or below 5 observations for a displayed class/outcome. Annotators may
  see the final canonical annotation and whether it was automatic consensus or
  expert adjudication, but not peer identities, votes, diagnostics, or named
  rankings.

### P6-08 decision

Reviews are image-level for classification and candidate-level for detection
and segmentation. A classification result or detection/segmentation candidate
that misses an automatic gate creates a `resolution_work_item`; candidate work
items contain only that candidate's context and the source image, so reviewers
do not re-annotate unrelated objects. Their immutable review submissions are
additional independent evidence for the second consensus run. An expert
adjudication is a final canonical decision, not another consensus vote. Metrics
and evidence mappings retain this image/candidate granularity.

The optional review-lease scope, duration, renewal, revocation, and concurrent
expert-edit conflict behavior remain pending.


- Require an exclusive resolution lease only for editable expert actions:
  editing a proposal, editing a raw submission, or creating a replacement.
  Read-only evidence viewing and retry do not require a lease. Accepting an
  unedited proposal does not require one, but returns `409` while another user
  holds an edit lease on the same work item.
- Scope a lease to exactly one `resolution_work_item`. Use a 15-minute duration,
  renew every 5 minutes while the edit screen is active, and cap one continuous
  lease at 2 hours before explicit reacquisition.
- Release on successful submission or explicit exit; expire on missed renewal.
  An owner/manager may revoke an abandoned lease with a mandatory reason and
  audit entry. Revocation never deletes the holder's local recovery draft.
- A lease is advisory concurrency control, not authority to overwrite. Every
  submit still carries the base work-item/evidence/resolution versions; stale
  submissions return `409`, preserve local recovery, and require explicit
  reconciliation. Retry, acceptance, cancellation, and adjudication are blocked
  while an incompatible edit lease is active.


## App decisions

| ID | Pending App decision | Required documented outcome |
| --- | --- | --- |
| `A6-01` | Review queue information design | Default filters/sort, row diagnostics, pagination, lazy image/evidence loading, reason vocabulary, and aggregate vs. named evidence visibility |
| `A6-02` | Evidence comparison interaction | Overlay colors/patterns, side-by-side breakpoint, keyboard controls, task-specific metrics, large-object handling, and nonvisual equivalents |
| `A6-03` | Adjudication editing and confirmation | Starting source, draft/recovery key, accept/edit/replace/retry confirmations, unsaved-navigation behavior, and stale-version reconciliation |
| `A6-04` | Resolver configuration UX | Editable approved parameters, advanced-control disclosure, defaults/help text, threshold warnings, conditional-strategy eligibility and unavailable reasons, and provenance/history presentation |


### A6-01 decision

- Default the manager queue to unresolved `review_required` and `failed` work,
  sorted by severity and then oldest first. Provide server-side cursor
  pagination with a default page size of 50 and filters for batch, purpose,
  task, state, resolver strategy, reason, and age.
- Show thumbnail/path, task, image or candidate scope, submission/review counts,
  reason, concise task metrics, resolver state/version, age, and lease holder
  state. Do not load full images, masks, or raw documents until an item opens.
- Use a closed reason vocabulary: `class_tie`, `support_below_threshold`,
  `posterior_below_threshold`, `ambiguous_match`, `geometry_below_threshold`,
  `topology_invalid`, `resolver_unavailable`, `resolver_output_invalid`,
  `worker_failed`, and `expert_required`.
- Keep the queue aggregate. Authorized owners/managers may reveal named evidence
  only inside the opened evidence view; ordinary reviewers and annotators never
  receive peer identity or unrelated candidates.

### A6-02 decision


- Assign each evidence source a stable color plus line/fill pattern within the
  item. Provide toggles for each source and the proposal, an all-off reset, and
  keyboard focus/visibility controls. Never encode identity or state by color
  alone.
- Default to overlays for at most four visible sources. Offer side-by-side view
  always and switch to it by default on narrower than 1200 px layouts or when
  more than four sources are visible.
- Show classification votes as a table and bar chart; detection as candidate
  groups with class/support and pairwise IoU; segmentation as candidate groups
  with Dice/IoU, translucent masks, contours, and topology diagnostics. Metrics
  are computed by the API from original-resolution geometry.
- Use tiled/downsampled previews for large images and masks while clearly
  labeling preview scale. Provide a nonvisual evidence table containing every
  source, class decision, match outcome, metric, exclusion reason, and proposal
  contribution.
- When overlaying masks use a configurable alpha channel for translucent masks. Let the user increase/reduce alpha 
on-the-fly.

### A6-03 decision


- Default an edit to the current valid resolution proposal. Allow an authorized
  manager to choose a raw submission or blank replacement explicitly; record
  the chosen source.
- Key local recovery by project, work-item, actor, and base version. Autosave
  locally, warn on navigation, and clear recovery only after the server confirms
  the accepted/adjudicated version.
- Require confirmation for accept, edit-submit, replace, retry, and lease
  revocation. Require a rationale for edits, replacements, retries, lease
  revocation, and conflicted self-adjudication; an unedited proposal acceptance
  may use an optional note.
- On `409`, preserve the draft, refetch authoritative evidence, and show a
  source/base/new-version comparison. Never auto-rebase geometry. Let the user
  copy the draft onto the new version only after obtaining a valid lease and
  explicitly confirming reconciliation.

### A6-04 decision


- Drive the complete form from typed capability descriptors. Show pipeline,
  class strategy, common support thresholds, and task geometry strategy in the
  main form; keep priors, convergence, post-processing, and resource-sensitive
  controls in a collapsed advanced section.
- Initialize server defaults and show units, bounds, inclusivity, and concise
  help beside every control. Do not provide a generic JSON editor.
- Disable conditional strategies when eligibility fails and show the exact
  missing sample, overlap, class-coverage, or convergence prerequisite. Do not
  offer silent fallback.
- Warn before a configuration would increase review volume, before enabling
  topology-changing post-processing, and when editing defaults affects only
  future `preparing` batches. Reject thresholds at or below the hard majority
  floor.
- Present a read-only history with policy/configuration version, strategy and
  dependency versions, actor, time, changed fields, calibration evidence, and
  affected future batches. Model seeds and learning runs never appear as class
  consensus inputs.


