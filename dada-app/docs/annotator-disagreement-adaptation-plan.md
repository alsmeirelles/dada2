# DADA App Annotator Disagreement Adaptation Plan

## Purpose and scope

This document is the implementation plan for adapting the already implemented
DADA App to support independent redundant annotation, automated consensus, and
manual adjudication. The corresponding server domain, HTTP contract, and API
delivery order are defined in the
[combined App/API implementation plan](../../dada-api/docs/api-implementation-plan.md).

This is an adaptation of the current React/TypeScript application, not a
frontend rewrite. Existing image rendering, annotation tools, geometry,
viewport behavior, uploads, authentication, recovery, polling, and WebSocket
reconciliation should be retained and extended.

## Current App baseline

The current App assumes one annotation document and one exclusive image lease
per selected media item:

- `src/features/projects/NewProjectPage.tsx` collects project, class, learning,
  collaborator, and dataset settings, then submits them sequentially.
- `src/features/projects/project-api.ts` creates the project, classes, members,
  upload session, media, and activation request.
- `src/features/projects/types.ts` has no annotation-policy representation.
- `src/features/annotation/annotation-api.ts` reads a global image queue within
  an iteration and performs lease/draft/completion calls.
- `src/features/annotation/AnnotationWorkspacePage.tsx` hides an image leased
  by another user and keys editing state around media and lease IDs.
- `src/features/annotation/ProjectActivityPage.tsx` treats completed images as
  completed annotations and has no resolving or review state.
- `src/features/annotation/recovery.ts` stores short-lived local recovery data
  but cannot distinguish two assignments for the same media.
- `src/features/annotation/useProjectEvents.ts` invalidates queries for the
  current single-submission event vocabulary.
- `src/features/annotation/ImageStage.tsx` and the geometry/viewport utilities
  already provide most of the rendering foundation needed for a review overlay.

The API has completed Phases 0, 1, and 2. The Phase 2 project, membership, and
versioned annotation-policy contract is stable, so the corresponding App work
can proceed against its generated OpenAPI surface. Later App phases must still
wait for their matching API contract rather than inventing temporary
browser-only behavior.

## Target user journeys

### Single-annotation project

1. The owner chooses **Single annotation** during project setup.
2. Any eligible annotator may claim one assignment for a selected image.
3. Submission resolves that image immediately.
4. Existing annotation and activity behavior remains visually familiar.

### Consensus project

1. The owner adds project members and chooses **Consensus annotation**.
2. The owner selects at least two members authorized to annotate and reviews
   the total assignment cost: selected images multiplied by group size.
3. Each selected image appears independently in every configured annotator's
   queue. One annotator working on it does not block another group member.
4. Annotators work blindly: they cannot see peer names, drafts, submissions,
   agreement scores, or the proposed consensus in the ordinary workspace.
5. After the final required submission, the item enters automated resolution.
6. A successful resolution advances image progress. An ambiguous result enters
   a manager review queue.
7. An owner/manager compares evidence, accepts the proposed result, edits it,
   or replaces it with an adjudicated canonical annotation.

## App architecture changes

### Contract types and API client

Prefer generated OpenAPI types for server resources and requests. Keep local
types only for form drafts, canvas tools, and view models. Until generation is
introduced, update the handwritten types atomically with the committed
`openapi.json`.

Add these contract concepts:

- `AnnotationMode = 'single' | 'consensus'`.
- A discriminated `AnnotationPolicy` with mode, version, selected annotator
  IDs, resolver identity/version, parameters, and review thresholds.
- `AnnotationBatch` and `BatchPurpose` for initial training, test, and
  acquisition selections.
- `AnnotationAssignment` with `assignment_id`, `media_id`, caller-specific
  status, and lease information.
- Separate `SubmissionStatus` and `ResolutionStatus` values. A submission being
  complete must not imply that its image is resolved.
- Expanded iteration state including `consolidating`.
- Counts for images, resolved images, assignments, submitted assignments,
  available/leased assignments, pending resolutions, and review-required
  items.
- Manager-only evidence, resolver diagnostics, proposed/accepted resolutions,
  resolution history, and adjudication requests.

Update `src/api/types.ts` at the same time to replace the stale current-user
`role` field with the Phase 1 `is_administrator` field.

Create API client functions for:

- reading and version-updating the project policy;
- reading/updating/starting an annotation batch;
- acquiring the caller's next or specified assignment;
- saving and completing the document attached to an assignment lease;
- listing manager resolution work;
- reading one item's evidence and resolution history;
- retrying resolution with explicit configuration; and
- accepting or submitting an adjudicated document.

Keep route construction and wire DTOs in API modules. Components should consume
small query hooks or view-model adapters rather than interpreting server state
independently.

### Query keys and cache invalidation

Define query-key factories rather than scattered arrays. At minimum separate:

```text
project(projectId)
projectPolicy(projectId)
iterations(projectId)
batch(projectId, batchId)
assignmentQueue(projectId, iterationId, userId)
resolutionQueue(projectId, batchId, filters)
resolutionEvidence(projectId, batchItemId)
statistics(projectId)
```

Events invalidate only affected resources where practical. A reconnect or
sequence gap invalidates all authoritative project resources. Never place raw
peer evidence into a general annotator cache entry.

## Project setup adaptation

### Form model

Extend `ProjectDraft` in `src/features/projects/types.ts` with a browser-only
policy draft:

```ts
type AnnotationPolicyDraft =
  | { mode: 'single' }
  | {
      mode: 'consensus'
      annotatorUsernames: string[]
      resolver: string
      parameters: Record<string, number | string | boolean>
      reviewThresholds: Record<string, number>
    }
```

Usernames are acceptable only in the unsaved form. The persisted API policy
uses user IDs returned after member creation/resolution.

### Wizard UI

Adapt `src/features/projects/NewProjectPage.tsx` rather than creating a second
project wizard:

- Rename or split the existing Team step into **Team and annotation strategy**.
- Present a clear Single/Consensus choice with a short description of cost,
  independence, resolution, and possible manual review.
- In consensus mode, show a multi-select containing only members authorized to
  annotate. The owner and managers may be included because their roles have
  annotation authority.
- Require at least two distinct selected users. Explain validation failures
  inline and retain them when moving between wizard steps.
- Select a task-compatible resolver. Do not offer STAPLE for classification or
  detection. Present advanced parameters and thresholds in a collapsible
  section with server-provided/default values.
- Show an assignment estimate separately for initial training, test, and one
  acquisition iteration, plus their total. Label this as work items rather
  than images.
- Add policy mode, group size, resolver, and estimated work to the final review
  screen.

The wizard must not imply that automated consensus is guaranteed to succeed.
Its text should state that ambiguous items require owner/manager review.

### Creation workflow and recovery

Adapt `createProjectWithDataset` in `src/features/projects/project-api.ts` to
perform these resumable steps:

1. Create the project draft.
2. Create classes.
3. Add/resolve members and collect their server user IDs.
4. Translate the policy draft from usernames to IDs and save it with its
   version.
5. Create and complete the upload.
6. Activate only after the API confirms classes, media, and policy validity.

This cannot be one browser transaction. Persist the server project ID and the
last completed setup step in the existing creation state/recovery mechanism.
If a later request fails, tell the user that the project is a resumable draft
and route them to its setup screen; do not blindly create another project.
Every retryable create/complete request continues to use an idempotency key.

Add an owner/manager project-settings surface for updating the default policy.
It must send the current optimistic `version`, explain that active batches keep
their snapshots, and handle `409` by refetching before the user retries.

## Annotation workspace adaptation

### Assignment-scoped behavior

Update `src/features/annotation/types.ts`, `annotation-api.ts`, and
`AnnotationWorkspacePage.tsx` so the unit of work is an assignment:

- Queue items use `assignment_id` as their React key and action identifier.
- Lease acquisition requests an assignment, not an image.
- Draft save, renewal, release, completion, and assisted segmentation continue
  to use `lease_id`, whose response identifies the assignment.
- Completion displays **Submission received**. It must not display **Image
  resolved** unless the response explicitly reports an accepted resolution.
- The current annotator can reopen only their own draft or submitted work as
  allowed by the API. Peer assignments never appear as editable work.
- A peer leasing the same media does not disable or hide the caller's
  assignment. Remove the current global `item.status === 'leased'` filtering
  and replace it with caller-assignment status rules.
- “Next” and keyboard navigation traverse caller-eligible assignments.

The sidebar should show personal workload (`available`, `in progress`,
`submitted`) while the header may show privacy-safe aggregate image resolution
progress. Do not expose which peer is late or currently editing.

### Blindness requirements

The ordinary annotation workspace must never request or render manager evidence
endpoints. It must not show:

- peer annotator names for the same image;
- peer geometry or class choices;
- current vote counts or agreement metrics;
- proposed or accepted consensus before the caller submits; or
- events containing peer-specific evidence.

Treat an accidental evidence field in an annotator response as a contract
error in development tests rather than rendering it opportunistically.

### Draft and offline recovery

Change `src/features/annotation/recovery.ts` keys to include project,
assignment, and server draft version. A suitable logical key is:

```text
dada.annotation-recovery:{projectId}:{assignmentId}:{baseVersion}
```

Do not key only by media ID: the same browser user may receive a reassigned
work item, and multiple independent assignments exist for the same image.
Recovery remains session-scoped, expires after 24 hours, stores no image bytes
or credentials, and never overwrites a newer server draft. Clear only the
completed assignment's snapshot after successful submission.

### Existing annotation tools

Keep `ImageStage.tsx`, geometry transforms, classification controls, boxes,
polygons, zoom/pan, undo/redo, class selection, and keyboard shortcuts.
Assisted segmentation remains an aid within the current assignment and does
not count as an independent annotator or vote.

## Activity and progress adaptation

Update `src/features/annotation/ProjectActivityPage.tsx` and its types/styles:

- Add `consolidating` to iteration titles, descriptions, polling cadence, and
  status styling.
- Show two progress measures: **submissions** (`submitted assignments / total
  assignments`) and **resolved images** (`accepted resolutions / total
  images`).
- Show counts for available/in-progress personal work separately from batch
  resolution counts.
- Show resolving and review-required counts to owners/managers. Annotators may
  receive only aggregate status permitted by the API.
- Do not close an iteration from the App when assignment counts reach zero.
  Reconciliation may call the close endpoint, but the API decides whether all
  images have accepted resolutions.
- Add a manager link to the consensus review queue when items require review.
- Add quality charts only when their meaning is clear: agreement distribution,
  review rate, and resolver outcomes. Do not add named annotator rankings.

Update `ProjectsPage.tsx` cards so **Annotated** is replaced by an unambiguous
resolved-image count. Add a review badge/action for authorized users when
manual work is outstanding.

## Consensus review and adjudication feature

Create a dedicated feature folder, for example:

```text
src/features/consensus/
  ConsensusReviewQueuePage.tsx
  ConsensusReviewPage.tsx
  consensus-api.ts
  consensus-types.ts
  consensus-view-model.ts
  consensus.css
```

Add manager-protected routes such as:

```text
/projects/:projectId/consensus
/projects/:projectId/consensus/:batchItemId
```

Client-side route protection is for UX only; the API remains authoritative.

### Review queue

The queue supports server-side cursor pagination and filters for batch,
purpose, resolver status, and reason. Each row/card shows image path,
submission count, task-compatible summary metrics, review reason, and age. It
must not download full-resolution images or all annotation documents until an
item is opened.

### Evidence comparison

Reuse canvas primitives but add a review-specific read-only overlay model:

- give each raw submission a stable, accessible color/pattern;
- allow toggling individual submissions and the proposed resolution;
- show side-by-side mode where overlays would become unreadable;
- display classification vote distribution, detection match/support/IoU, or
  segmentation Dice/IoU/STAPLE diagnostics as appropriate;
- distinguish unmatched or unsupported objects visually;
- show algorithm name/version, parameters, input IDs/hashes, and run time;
- provide non-color indicators and keyboard controls.

Do not push multiple raw documents through the editable annotation document
state. Introduce a separate overlay view model so ordinary editing invariants
remain intact.

### Adjudication actions

The manager can:

1. accept the proposed resolution;
2. start from the proposal, edit it with the existing tools, and submit an
   adjudicated canonical document;
3. start from one raw submission and edit it;
4. create a replacement annotation; or
5. retry automated resolution with a new explicit configuration if authorized.

Every action requires a confirmation that states its effect and sends an
idempotency key. A stale resolution/evidence version returns `409`; retain the
local edit as recovery data and require a refetch/reconciliation decision.
Never mutate or delete raw evidence from this screen.

## Real-time and polling changes

Extend `src/features/annotation/types.ts` and `useProjectEvents.ts` for:

- `assignment.leased` and `assignment.released`;
- `annotation.submitted`;
- `resolution.started` and `resolution.completed`;
- `resolution.review_required`; and
- `resolution.adjudicated`.

Events remain invalidation hints. Do not derive counters by incrementing local
state because duplicate events and sequence gaps are expected. On reconnect or
a sequence gap, refetch iterations, relevant batches/queues, statistics, and
the open review item. Polling remains mandatory when WebSocket delivery is
unavailable.

## Error and state handling

Add user-facing handling for the revised stable error codes:

| Code | App behavior |
| --- | --- |
| `policy_locked` | Explain that the active batch has a snapshot; offer default-policy settings for future batches |
| `invalid_consensus_group` | Return to team/policy selection and identify invalid members without discarding the draft |
| `assignment_not_owned` | Lock editing, retain safe local recovery, and refresh the personal queue |
| `assignment_already_submitted` | Clear obsolete recovery only after confirming the server submission and refresh progress |
| `resolution_not_ready` | Refresh submission counts; do not offer adjudication yet |
| `resolution_config_conflict` | Preserve local form values, refetch resolver history, and require an explicit retry |
| `adjudication_required` | Route authorized users to review; show annotators only a neutral pending-review state |

Continue showing trace IDs for support. Lease loss, offline mode, and stale
versions must leave canvas work recoverable without pretending it was accepted.

## Accessibility and content requirements

- All mode, resolver, overlay, and adjudication controls must be keyboard
  reachable with visible focus.
- Agreement charts and overlay colors require text/table equivalents.
- At 200% browser zoom, the review evidence, actions, and metrics must remain
  usable without two-dimensional page scrolling where practical.
- Respect reduced motion for resolving/progress animations.
- Use **submission**, **resolution**, and **review** consistently. Avoid using
  **complete** without stating whether it refers to an assignment or image.
- Explain that consensus estimates a best annotation and can require human
  review; do not describe it as ground truth or guaranteed correctness.

## Implementation phases

These phases align with the same-numbered API phases. App code depending on a
new route begins only after that route and its generated types are stable.

### Phase 2: project policy setup — implemented 2026-08-30

- Correct the Phase 1 current-user type.
- Add policy types, wizard controls, member-ID resolution, validation, work
  estimates, resumable setup, and default-policy settings.
- Add component/unit tests for both modes and all group validation cases.

Exit gate: a user can create and resume single or consensus project setup
against the Phase 2 API, including a `409` policy-version conflict.

### Phase 3: ingestion contract alignment — next step for App and API

- Preserve the current uploader and adapt generated request/response types.
- Target the API's self-hosted persistent-volume store. The browser continues
  to use API upload routes and never receives or depends on a host filesystem
  path; a later cloud-storage migration must remain invisible to this contract.
- Ensure a failed policy/setup step resumes before upload and an interrupted
  upload resumes without repeating project or member creation.
- Add a **draft project setup editor**. A draft shown in `/projects` must offer
  an owner/manager a route back to an editable setup form populated from the
  persisted project, classes, members, and policy. The user must be able to
  correct project fields, classes, team, policy, and dataset selection, then
  continue from the first incomplete setup step. Do not route a failed setup
  back to the blank “new project” wizard or reuse a stale browser-only draft.
  Version conflicts must retain the user's unsaved values, refetch the server
  representation, and require an explicit reconciliation.
- Add **member management** to the project settings flow, using the completed
  Phase 2 API contract: list members; add an existing user by username; change
  a member role among `manager`, `annotator`, and `viewer`; and remove a
  member. Show the API's sole-owner protection rather than attempting client
  ownership transfer. Member changes must refresh the policy editor so only
  annotation-authorized members can be selected for consensus.

Exit gate: both project modes complete the existing interrupted/resumed upload
browser scenario; a failed draft can be reopened, corrected, and resumed
without creating a second project; and an owner/manager can manage members and
save a valid consensus policy using the updated membership. Cancelled uploads
and deleted projects are immediately unavailable and report the API's terminal
purge result rather than offering a restore action.

### Phase 4: batch visibility

- Add batch/policy snapshot types and manager activity presentation.
- Display selected image and generated assignment counts before annotation.

Exit gate: the UI reflects the server snapshot and never suggests that editing
the project default changes an active batch.

### Phase 5: assignment workspace

- Convert queue, lease, draft, completion, navigation, and recovery behavior to
  assignment scope.
- Revise progress language and add blindness tests.

Exit gate: two browser sessions can independently annotate the same image,
neither sees peer evidence, and their local recovery records do not collide.

### Phase 6: resolution and adjudication

- Add resolution progress and review-required states.
- Build the review queue, evidence comparison, retry, acceptance, editing, and
  adjudication flows.

Exit gate: an automatic result can be reviewed and accepted, a forced
low-agreement case can be edited/adjudicated, and stale versions preserve the
manager's local work.

### Phase 7: learning and quality metrics

- Display training/export progress only after all required resolutions exist.
- Add agreement/review statistics and assisted-segmentation contract changes.

Exit gate: unresolved submissions are never represented as training data in
the UI, and assisted segmentation remains scoped to the active assignment.

### Phase 8: real-time and production hardening

- Add the new event vocabulary, targeted invalidation, sequence-gap recovery,
  permission-safe caching, and load-friendly pagination/lazy evidence loading.

Exit gate: WebSocket and polling journeys converge on identical authoritative
state without evidence leakage.

### Phase 9: coordinated release acceptance

- Update `DESCRIPTION.md`, `docs/api-contract.md`, `docs/architecture.md`,
  `docs/testing.md`, and `README.md` to reflect the implemented behavior.
- Record the compatible API/OpenAPI and resolver versions.

Exit gate: the complete single-mode, automatic-consensus, and manual-review
journeys pass in the two latest Chrome and Firefox releases.

## Test plan

### Unit and component tests

- Policy discriminated-union parsing and task/resolver compatibility.
- Username-to-user-ID mapping, duplicate prevention, and group-size validation.
- Assignment estimates for each selected set.
- Assignment queue view-model behavior when peers lease the same media.
- Recovery isolation by assignment and stale-version reconciliation.
- Submission vs. resolution counters and iteration state presentation.
- Evidence overlay toggles, metrics formatting, and adjudication payloads.
- Error-code mapping and permission-aware content.
- Event-to-query invalidation and sequence-gap recovery.

### Browser contract scenarios

1. Create and activate a single-mode project.
2. Create a consensus project with two annotators and verify its cost summary.
3. Open the same media simultaneously in two user sessions and submit
   independent documents.
4. Verify neither annotator can discover peer evidence before submission.
5. Interrupt one assignment, restore only its recovery snapshot, and complete
   it after lease reacquisition.
6. Observe automatic classification, detection, and segmentation resolution.
7. Force each task's low-agreement path and adjudicate as a manager.
8. Exercise a stale adjudication conflict without losing local edits.
9. Disconnect WebSocket during resolution, recover through polling, reconnect,
   and reconcile a sequence gap.
10. Verify keyboard-only use, reduced motion, and 200% zoom in setup,
    annotation, activity, and review screens.

Run the existing `npm run lint`, `npm test`, and `npm run build` gates for each
App phase. The coordinated release suite must use the candidate API with no
request mocking and record its OpenAPI version.

## File-level change map

| Existing path | Planned change |
| --- | --- |
| `src/api/types.ts` | Align current user with `is_administrator`; consume generated contract types |
| `src/features/projects/types.ts` | Add local policy draft and policy/batch view models |
| `src/features/projects/NewProjectPage.tsx` | Add mode, group, resolver, thresholds, cost, and resumable setup UX |
| `src/features/projects/project-api.ts` | Resolve member IDs, save versioned policy, and resume ordered setup operations |
| `src/features/projects/ProjectSettingsPage.tsx` | Manage members and default policy; link draft projects to editable setup/recovery flow |
| `src/features/projects/ProjectsPage.tsx` | Show resolved counts and manager review badges/actions |
| `src/features/annotation/types.ts` | Add assignments, separate submission/resolution state, batches, and events |
| `src/features/annotation/annotation-api.ts` | Replace media queue calls with caller-assignment calls and add batch progress |
| `src/features/annotation/AnnotationWorkspacePage.tsx` | Use assignment identity, preserve blindness, and distinguish submission from resolution |
| `src/features/annotation/ProjectActivityPage.tsx` | Add consolidating, dual progress, resolution/review status, and quality metrics |
| `src/features/annotation/recovery.ts` | Key and reconcile snapshots per assignment/version |
| `src/features/annotation/useProjectEvents.ts` | Invalidate assignment, resolution, evidence, and statistics queries |
| `src/features/annotation/ImageStage.tsx` | Extract/reuse read-only overlay primitives without coupling review state to editing state |
| `src/app/router.tsx` | Add manager consensus queue and item review routes |
| `src/features/consensus/*` | New review queue, comparison, resolver retry, and adjudication feature |
| `src/features/projects/projects.css` | Add strategy/settings and review indicators while retaining responsive behavior |
| `src/features/annotation/annotation.css` | Adapt personal assignment queue and submission/resolution messaging |
| `src/features/annotation/activity.css` | Add consolidating/review states and dual progress layout |

Test files should stay beside their source modules. Add focused consensus
view-model/component tests under `src/features/consensus/` and extend existing
recovery, real-time, geometry, viewport, ingestion, and browser release tests
rather than duplicating their coverage.

## Explicit non-goals for this adaptation

- No frontend implementation of STAPLE, voting, object matching, or weighted
  box fusion. The App visualizes server results; it never computes canonical
  annotations.
- No peer-to-peer synchronization or browser-owned consensus state.
- No named annotator ranking or automated performance scoring.
- No partial-quorum or adaptive reliability UI in the first release.
- No replacement of the existing annotation canvas or project wizard solely
  to deliver this feature.
