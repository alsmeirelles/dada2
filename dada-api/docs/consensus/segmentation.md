# Segmentation Consensus Strategy

## Scope

Segmentation consensus also has two stages: object identification/class
disambiguation followed by mask refinement. STAPLE or a pixel-vote applied to
all masks at once is incorrect when annotators disagree about which instances
exist or how they should be classified.

The API worker is responsible for rasterization, crowd-kit invocation,
polygonization, validation, and provenance. The browser renders the results
but never computes a canonical mask.

## Stage 0: normalize submissions

Validate polygon rings in original-image pixel coordinates and rasterize each
instance at the source image dimensions using a documented fill rule. Retain
the original polygon, binary mask checksum, source object ID, source submission
ID, annotator index, and source class. Rasterization implementation/version and
image dimensions are part of resolver provenance because they can affect the
result.

Reject invalid geometry at annotation submission time. Do not resize masks to a
shared arbitrary canvas: all masks for an item use its original dimensions.

## Stage 1: object identification and class disambiguation

### Identify instance candidates class-agnostically

Match masks across annotators without using their class as a precondition. Use
mask IoU, Dice, or a configured combination, with one-to-one maximum-weight
matching per annotator pair. Form candidate instance groups using a complete-
link/anti-bridge rule and permit no more than one instance per annotator in a
group.

The matching gate may use a coarse bounding-box prefilter for performance, but
the final instance decision uses mask overlap. Same-annotator overlaps and
unmatched masks are diagnostics, not automatic canonical instances.

### Resolve existence and class

For each instance candidate, build a class-observation matrix. Matched masks
contribute their selected class; a valid submission with no matching instance
contributes `no_object`; missing assignments remain missing. Resolve class and
existence with the user-selected registered Cleanlab adapter defined in
[classification.md](classification.md).

Only candidates meeting configured support/existence and class-quality
thresholds proceed to mask refinement. Ambiguous instance matches, class ties,
or unsupported object-count disagreement require manual review. This first
stage ensures that crowd-kit only receives masks believed to belong to the same
resolved instance and class.

## Stage 2: mask refinement with crowd-kit

For each accepted instance, create the rater-by-pixel mask inputs from only the
supporting masks. The user selects a registered crowd-kit segmentation adapter
from `GET /api/v1/capabilities`; the API validates the choice and parameters
against the installed crowd-kit version. Initial supported adapters should be
registered explicitly from crowd-kit's segmentation aggregation family, such
as:

- `SegmentationMajorityVote` for a thresholded pixel majority;
- `SegmentationEM` for expectation-maximization aggregation; and
- `SegmentationRASA` when its assumptions and resource profile are suitable.

An optional `staple` adapter may be provided by DADA's own segmentation
resolver when validated against reference fixtures. It is separate from
crowd-kit and must be labeled as such in capabilities and provenance.

The selected adapter returns a binary probability/label mask. Apply the
configured threshold, remove only explicitly configured tiny components/fill
holes, polygonize with the recorded algorithm/version, and validate the final
rings. If post-processing changes topology materially, retain both the raw
aggregated mask checksum and final polygon checksum.

The configuration must record the crowd-kit strategy identifier, crowd-kit
package version, adapter version, all strategy parameters, pixel threshold,
post-processing thresholds, and source mask checksums. A user may choose only
strategies exposed by capabilities; names are not accepted as arbitrary code.

## Quality gates, output, and tests

Record per-instance pairwise Dice/IoU, support count, pixel agreement,
resolver diagnostics, and final area. Require manual review for low overlap,
empty/degenerate output, severe topology changes, or any Stage 1 ambiguity.

The resolved annotation document contains new canonical polygon objects with
the class decided in Stage 1. It never mutates source polygons.

## Per-annotator performance observations

After an accepted resolution, use the persisted instance mapping to write one
immutable project-scoped observation for each source mask. A raw mask mapped to
a kept canonical instance records submitted class, canonical class,
`class_retained`, mask IoU, and Dice score against the canonical raster mask.
An unmatched source mask records a distinct `false_positive`, `duplicate`, or
`ambiguous_match` outcome. A canonical instance absent from an otherwise valid
annotator submission records a `missed_object` observation. Empty masks and
post-processing topology failures are explicit outcomes, not silently coerced
to zero IoU.

Summaries can therefore report project/class-specific class retention and
mask-IoU/Dice distributions alongside false-positive and miss rates. Each
observation references the accepted resolution version and evaluation source;
automated-consensus observations require a later bias-safe policy before they
can influence that annotator's confidence weight.

Golden fixtures must cover same instance/different class; adjacent touching
instances; omitted instance; unmatched false positive; class tie; thin
structures; holes; disconnected regions; low-Dice masks; each registered
crowd-kit strategy; optional STAPLE; deterministic rasterize/polygonize replay;
and manual adjudication. Include package-version compatibility tests so an
upstream crowd-kit API change cannot silently alter consensus output.
