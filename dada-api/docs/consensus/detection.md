# Detection Consensus Strategy

## Scope

Detection consensus is deliberately a two-stage process. It must first decide
which real-world objects are represented and which class each represents; only
then can it refine box coordinates. Directly averaging every box of one class
is unsafe because it turns class disagreement, duplicate boxes, and nearby
objects into corrupted geometry.

The API worker resolves a batch item from immutable raw submissions. It stores
both stages' diagnostics and creates an accepted canonical document only after
all configured quality gates pass.

## Stage 0: normalize submissions

Validate source image dimensions, class membership, finite coordinates,
positive rectangle width/height, and bounds. Convert each rectangle to
`[x1, y1, x2, y2]` in original-image pixels while retaining its source object
ID, source submission ID, annotator index, and original class.

Do not silently discard invalid objects. A malformed submission fails normal
annotation validation; an object rejected by the consensus matcher is preserved
as an unmatched diagnostic.

## Stage 1: object identification and class disambiguation

### Identify candidate objects without assuming a class

Match boxes **class-agnostically** across different annotators using an
image-size-normalized IoU gate configured by the policy. Use a one-to-one
maximum-weight bipartite match for each annotator pair, then create candidate
object groups only when their members satisfy a complete-link or equivalent
anti-bridge rule. This prevents one large box from transitively merging two
nearby objects through a third box.

Each candidate group may contain at most one box from a particular annotator.
Same-annotator duplicate boxes are retained as a quality diagnostic and do not
become independent votes. Boxes with no sufficient cross-rater support remain
unmatched candidates; their existence is resolved explicitly rather than
discarded just because they lack a group.

### Resolve object existence and class

For every candidate object, construct a class-observation matrix over the
configured annotator group. An annotator matched to the group supplies its
chosen class. An annotator who submitted a valid image document but had no
matching box supplies a `no_object` observation. Missing assignments remain
missing values and block first-release resolution.

Run the user-selected, registered Cleanlab classification adapter described in
[classification.md](classification.md). The adapter resolves the class from
the candidate's observations and records quality/confidence. It may use an
approved model-run probability vector only when its provenance matches the
media/model version.

Accept a candidate object only when:

- the configured existence/support threshold is met;
- the selected class is not `no_object`;
- class quality is at or above the policy threshold; and
- the group did not violate matching ambiguity rules.

Ties, low class quality, object-count disagreement outside configured limits,
or ambiguous matches send the whole image to manual review. The worker must
not let a box's original class decide matching before class disambiguation.

## Stage 2: box refinement

For each accepted object/class pair, refine only the matched boxes that support
that resolved object. The user selects one registered box-refinement strategy
from API capabilities, with typed parameters. The first adapters are:

- `weighted_box_fusion` for confidence/support-weighted coordinate fusion;
- `coordinate_median` for robust per-coordinate median boxes; and
- `trimmed_mean_box` for configurable outlier trimming.

Package-free box refinement is intentional: crowd-kit segmentation algorithms
are not box aggregators, and Cleanlab's role here is class resolution. Every
adapter returns a rectangle that is clipped to original dimensions and rejected
for non-positive area or failed geometry validation.

Record supporting source boxes, IoU distribution, selected strategy/version,
parameters, resulting coordinates, and any excluded outlier boxes. Low
geometric agreement (for example median pairwise IoU below policy threshold)
requires review even when class agreement is high.

## Outputs, review, and tests

The resolved document contains one object for each accepted object candidate.
Its object ID is new and stable for the resolution version; it must not reuse a
raw annotator's client object ID. Store Stage 1 and Stage 2 diagnostics
separately so a manager can see whether review was caused by identity, class,
or geometry disagreement.

## Per-annotator performance observations

After an accepted resolution, use the persisted Stage 1/Stage 2 mapping to
write immutable project-scoped observations for each source box. A raw box
mapped to a kept canonical object records submitted class, canonical class,
`class_retained`, and its box IoU with that canonical box. A source box without
a canonical match records an explicit `false_positive`, `duplicate`, or
`ambiguous_match` outcome rather than an invented IoU of zero. Conversely, a
canonical object with no box from an otherwise valid annotator records a
`missed_object` observation for that annotator.

This permits later summaries of class confusion, class retention, box-IoU
distribution, false-positive rate, and miss rate by project, class, and
evaluation source. The observations reference the accepted resolution version;
they do not make the same consensus-influenced result immediately eligible for
that annotator's own confidence weight.

Golden fixtures must cover: same object/different class; two adjacent objects;
duplicate same-rater boxes; one omitted object; unmatched false positive;
transitive-overlap bridge prevention; class tie; low-IoU geometry; clipped
boxes; each refinement strategy; and an adjudicated replacement. Concurrency
tests must prove a duplicate worker result cannot create two accepted
resolutions.
