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


## Decisões

Fechadas localmente em 2026-10-14, sob autorização explícita da Stephany, a
partir das decisões P6-01..08 e A6-01..04 acima. A leitura adotada é a
seguinte: todos os tópicos listados abaixo de cada decisão estão aprovados,
porque nenhum tem o rótulo **pending confirmation**. As frases "remain
pending" da P6-08 e o `[TO DECIDE: P6-05/P6-07]` dos requisitos ficam
superados pelos próprios tópicos.

O trabalho é feito na branch `phase-6`. Cada decisão registra o motivo e a
alternativa rejeitada. **Continuam sujeitas à revisão do Meirelles.** O que
segue apenas preenche o que os documentos deixaram em aberto.

### Motor e infraestrutura

#### D1 — Fronteira dos módulos

**Escolha:**

- **`dada_api/consensus/`** é um pacote puro, a porta do resolver. Contém:
  - os tipos do protocolo e da configuração tipada (Pydantic, sem FastAPI);
  - a aritmética exata;
  - as estratégias de classe, a detecção, a segmentação, o STAPLE e o adaptador falso.
  - Não importa ORM nem FastAPI. scipy, OpenCV e crowd-kit são importados
    dentro das funções, então a API nunca os carrega.
- **`dada_api/services/`** faz a orquestração com o banco.
- **`dada_api/workers/`** guarda o app Celery e a tarefa de consenso.

**Motivo:** o plano exige que objetos de FastAPI e de ORM não atravessem a
porta. Um pacote próprio torna essa fronteira visível e importável só pelo
worker.

**Rejeitada:** deixar os módulos puros em `services/`. Funciona, mas esconde a
porta.

#### D2 — O estado do job fica em `resolution_runs`

**Escolha:**

- Uma linha por rodada, com as tentativas contadas na própria linha.
- Um índice único parcial em `(batch_item_id, configuration_fingerprint)`,
  válido enquanto o status é `queued` ou `running`, garante "um job ativo por
  item e configuração" (P6-05).

**Rejeitada:** uma tabela genérica `worker_jobs`. Os jobs de aprendizado são
da Fase 7, que decide o próprio formato.

#### D3 — O relay da outbox é um processo de linha de comando

**Escolha:** `dada-api consensus-relay` executa `relay_once` a cada 2 s. Cada
passada:

1. Pega os eventos `consensus.initial_evidence_ready.v1` ainda não publicados
   (`FOR UPDATE SKIP LOCKED`).
2. Recusa as gerações obsoletas, como a 5.1 já faz.
3. Cria a entrada da rodada 1 e uma rodada `queued`, e marca o evento como
   publicado.
4. Envia as rodadas na fila ao Celery, respeitando os limites por projeto (2
   padrão e 1 máscara).
5. Reenfileira as rodadas `running` que passaram do tempo-limite mais a
   margem, o caso de um worker que caiu:
   - espera 1 min antes da segunda tentativa e 5 min antes da terceira;
   - são 3 tentativas no total; na terceira falha, a rodada vira
     `worker_failed` permanente.

**Motivo:** uma única função, fácil de testar, cobre o despacho, a entrega
"pelo menos uma vez" e a recuperação de queda.

**Rejeitada:** o Celery beat. Também é outro processo, e é mais difícil de
testar.

#### D4 — Execução no worker

**A tarefa Celery** é um envoltório fino, com `acks_late=True` e
`reject_on_worker_lost=True`:

1. Carrega a entrada em dados simples.
2. Chama o pipeline puro.
3. Entrega o resultado à ingestão, numa única transação.

**Filas:**

| Fila | Tarefas | Tempo-limite | Memória |
| --- | --- | --- | --- |
| `consensus.standard` | classificação e detecção | 5 min | 1 GiB |
| `consensus.mask` | segmentação | 15 min | 4 GiB |

**Limites:**

- O cancelamento cooperativo acontece 30 s antes do tempo-limite.
- Uma verificação prévia de complexidade (pixels × máscaras, objetos, pontos)
  falha logo, como `resource_limit` permanente.
- A memória é limitada com `RLIMIT_AS` só no Linux. Em desenvolvimento no
  Windows esse limite não vale.

**Testes:**

- Os testes chamam o corpo da tarefa diretamente, sem broker.
- O adaptador falso só é registrado com `DADA_ENVIRONMENT=test`.

#### D5 — Rodadas de evidência e rodadas de execução

**Escolha:**

- **`resolution_inputs.run_number` (5.1)** conta as rodadas de evidência: 1 é
  a coorte; 2 é a coorte mais os revisores.
- **`resolution_runs`** tem a própria sequência por item.
- **Nova tentativa do gerente:** cria uma rodada nova sobre a evidência mais
  recente.
- **Rodada 2:**
  - nasce quando todos os work items da rodada 1 estão `review_ready`;
  - reaproveita os candidatos da rodada 1, sem casar de novo, e só soma as
    observações dos revisores.
- **O que falha na rodada 2 ou numa nova tentativa** vai direto ao
  especialista, sem outra rodada de revisores.

**Motivo:** a P6-05 prevê uma única rodada de revisão. Casar de novo poderia
mudar quais caixas formam cada candidato.

#### D6 — Estados de item e de lote

**Escolha:**

- **Item:** além de `pending`, `awaiting_resolution`, `resolved` e
  `cancelled`, ganha `resolving`, `in_review` e `review_required`.
  - Não existe `failed` no item: a falha permanente leva a `review_required`,
    como pede a P6-05 ("moves the case to manual review or an explicit
    retry").
- **Lote:** o estado é derivado dos itens:
  - `resolved` quando todo item não cancelado está resolvido;
  - senão, `review_required` se algum item precisa de especialista;
  - senão, `resolving` se algum item já saiu da coleta;
  - senão, `annotating`.

#### D7 — Reabrir ou reatribuir durante a resolução

**Escolha:** quando a geração de evidência avança (5.1), a mesma transação
cancela, da geração antiga:

- as rodadas ativas;
- os work items abertos;
- as tarefas de revisão desses work items.

Resultados que cheguem depois são descartados como obsoletos. A regra da Fase
5 continua: só item não resolvido pode ser reaberto.

#### D8 — Disponibilidade das capacidades

**Escolha:**

- A API decide se uma estratégia está disponível pelos metadados de
  distribuição instalados (`importlib.metadata`) e pela tabela de quarentena.
  Ela nunca importa a biblioteca.
- Pin ausente ou incompatível vira `dependency_missing` ou
  `dependency_incompatible`.

**Suposição registrada:** API e workers rodam no mesmo ambiente ou imagem. A
topologia de implantação é a P8-04.

### Configuração

#### D9 — Configuração tipada e capacidades

**Escolha:**

- **`parameters` e `review_thresholds`** passam a ser objetos fechados e
  aninhados, discriminados pelo pipeline.
- **`resolver_version`** é gravado como `"1.0.0"`.
- **Formato dos limiares:** os de votos são frações exatas
  `{"numerator": 2, "denominator": 3}`; os contínuos são números.
- **Capacidades:** `consensus_resolvers` dá lugar a `consensus_pipelines`.
  Para cada tarefa, descreve o pipeline e as subestratégias, com versão,
  aplicabilidade, se é condicional, disponibilidade (e o motivo, quando
  indisponível) e descritores tipados de cada parâmetro.
  - Cada descritor tem: tipo, padrão, mínimo, máximo, inclusividade, opções,
    unidade, se é avançado e ajuda.
- **Pisos rígidos em todo salvamento e em toda nova tentativa:**
  - limiar de votos estritamente acima de 1/2;
  - nenhuma chave desconhecida;
  - só estratégias do catálogo.
- **Migração:**
  - Os IDs provisórios são trocados nas políticas padrão **e** nos lotes:

    | ID provisório | Pipeline definitivo |
    | --- | --- |
    | `majority_vote` | `statistical_class_consensus` |
    | `two_stage_box_fusion` | `two_stage_detection_consensus` |
    | `two_stage_mask_fusion` | `two_stage_segmentation_consensus` |

  - Os parâmetros e limiares recebem os padrões da P6-02.
  - O antigo `agreement` é descartado.

**Motivo:** a P6-02 fixa padrões e faixas que precisam de um lugar validado. A
A6-04 pede um formulário guiado por descritores tipados.

**Efeito no contrato:** muda a forma das capacidades e da política. O App é
ajustado na mesma fase.

#### D10 — A classificação continua multi-rótulo

**Escolha:** sem configuração nova, conforme a D6 da Fase 5.

- A classificação usa `multilabel_binary_vote`, que é o padrão.
- Também pode usar `dirichlet_vote`, `reliability_weighted_vote` ou
  `dawid_skene`, sempre no modo binário por classe.
- Os candidatos de detecção e segmentação usam `categorical_vote`, que é o
  padrão, sobre as classes mais `no_object`. Também podem usar
  `dirichlet_vote` e as estratégias condicionais.

**Motivo:** a Fase 5 adiou a opção "um rótulo por imagem", e o catálogo da
P6-01 continua completo sem ela.

**Rejeitada:** um campo `classification_label_mode`. Mudaria a configuração do
projeto, a política, os documentos e o assistente do App. **Ponto para o
Meirelles confirmar.**

#### D11 — Estratégias condicionais: snapshot de calibração congelado

**Quando:**

- No início do lote, se a estratégia for condicional, a API gera um snapshot
  em `resolver_calibration_snapshots` e o liga ao lote.
- Se os critérios falham, o início é recusado com
  `422 resolver_unavailable`, junto com os pré-requisitos que faltam.

**De onde vêm os dados (o corpus):** das resoluções já aceitas no projeto,
para a mesma tarefa.

- Para `dawid_skene`: as matrizes de observação persistidas.
- Para `reliability_weighted_vote`: as observações de desempenho
  `human_adjudication`.

**`reliability_weighted_vote`:**

- O peso de cada anotador é a acurácia suavizada com Beta(2,2), normalizada
  para média 1 e cortada em [0,5, 2,0].
- É elegível com 30 decisões por anotador e 5 observações por resultado. Todo
  membro do pool precisa estar incluído.
- **Leitura a confirmar:** "todo resultado usado pelo peso" é o conjunto de
  resultados do projeto, ou seja, as classes, mais `no_object` em detecção e
  segmentação.

**`dawid_skene`:**

- É elegível com 50 itens, cada um com 3 ou mais avaliadores; 20 observações
  por anotador; e 5 por resultado. Todo membro do pool precisa estar incluído.
- O ajuste começa pelo voto majoritário, usa suavização 1 e para em
  tolerância 1e-6 ou em 100 iterações. Sem convergência, a estratégia fica
  inelegível.

**Rota:** `GET /projects/{id}/resolver-eligibility` informa o que falta para
cada estratégia, como pede a A6-04.

#### D12 — Detalhes numéricos que a P6-02 deixa abertos

- **Suporte:** a contagem do vencedor sobre o número de observações válidas,
  contando `no_object`. A comparação é por produto cruzado. Empate no topo
  sempre vai para revisão.
- **Regras de decisão:**
  - `plurality`: há um único máximo;
  - `strict_majority`: o vencedor tem mais que n/2;
  - `supermajority`: o vencedor tem pelo menos `minimum_support`.
  - As três também aplicam o critério de suporte. Como ele precisa passar de
    1/2, as três só diferem nos diagnósticos, e isso fica documentado.
- **Multi-rótulo:** a classe fica positiva se o suporte positivo for pelo
  menos `minimum_support`, e negativa se o suporte negativo for pelo menos
  esse valor. Fora disso, vai para revisão.
- **Dirichlet:**
  - a distribuição a posteriori é Dir(α + contagens);
  - P(o vencedor é o máximo) é exata com Beta quando há dois resultados; com
    mais de dois, é uma integral unidimensional na representação Gama
    (scipy);
  - também exige suporte bruto de pelo menos 2/3.
- **Quantização:** `Decimal(repr(x))` com 6 casas e `ROUND_HALF_EVEN`. Valores
  não finitos são recusados antes da comparação.
- **Refinamento de caixas:**
  - o padrão é `coordinate_median`;
  - `trimmed_mean_box` tem `trim_fraction` 0,2, na faixa [0, 0,4];
  - `weighted_box_fusion` usa pesos iguais, porque caixa humana não tem
    confiança, e por isso equivale à média.
- **Limiar de pixel:** crowd-kit MV e EM já devolvem máscaras binárias, então
  o `pixel_threshold` vale só para o STAPLE. Os adaptadores do crowd-kit
  registram o 0,5 embutido.
- **Contagem de objetos:** não há critério separado. A divergência já aparece
  nos votos `no_object`.

### Algoritmos

#### D13 — Casamento, agrupamento e identidade do candidato

- **Arestas:**
  - Para cada par de anotadores, um casamento húngaro
    (`scipy.optimize.linear_sum_assignment`) maximiza a IoU quantizada.
  - Só ficam os pares com IoU no limiar de casamento ou acima.
  - Na segmentação, a medida é a IoU ou o Dice das máscaras. Os pares cujas
    caixas envolventes não se cruzam são descartados antes.
- **Agrupamento por ligação completa:**
  - Os grupos começam unitários.
  - As arestas são processadas da maior IoU para a menor. Empates são
    ordenados pelas referências canônicas, o que só ordena e nunca decide.
  - Dois grupos só se juntam se não tiverem anotador em comum **e** todo par
    cruzado estiver no limiar ou acima.
- **Ambiguidade:** se um objeto tem duas arestas de mesma pontuação para
  grupos diferentes, e as duas junções seriam possíveis, todos os candidatos
  envolvidos ficam `ambiguous_match` e vão para revisão.
- **Duplicata do mesmo anotador:** uma caixa no limiar ou acima de outra caixa
  do mesmo anotador, que está em outro grupo, vira `duplicate` e nunca forma
  um candidato votante.
- **Identidade do candidato:**
  - chave: `c-` seguido dos 32 primeiros caracteres hexadecimais do sha256
    das referências ordenadas;
  - ordinal: a posição da chave em ordem crescente.
  - A chave e o ordinal alimentam o `review_round_robin_v1`.

#### D14 — Rasterização, poligonização e tamanho do anel canônico

**Rasterização:** cada anel é preenchido com `cv2.fillPoly` no tamanho
original, e os resultados são combinados por XOR. Isso implementa par-ímpar
explicitamente, sem depender da convenção do OpenCV.

**Poligonização:**

- `cv2.findContours(RETR_CCOMP, CHAIN_APPROX_SIMPLE)`. É sem perda na grade
  de pixels: só remove pontos do meio de trechos retos.
- Os furos vêm da hierarquia de contornos.
- A orientação é explícita: o anel externo em sentido anti-horário e os furos
  em sentido horário.

**Problema:** um contorno de máscara costuma ter mais de 1.000 pontos, o
limite que a Fase 5 fixou para submissões. Uma borda inclinada vira uma
escada de pixels.

**Escolha:**

- Limite canônico de 10.000 pontos por anel, só para a saída do worker e para
  documentos de adjudicação.
- A verificação de anel simples fica mais rápida, com particionamento espacial
  em Python puro e sem dependência nova.
- Submissões continuam com 1.000.

**Rejeitadas:**

- Manter 1.000: quase toda máscara real iria para o especialista.
- Simplificar com `approxPolyDP` por padrão: contraria a P6-03 ("polygon
  simplification disabled by default").

**Ponto para o Meirelles confirmar.**

#### D15 — `SegmentationRASA`

**Escolha:** o adaptador é implementado e perfilado com uma fixture de
referência, dentro dos limites da fila de máscaras. Só é anunciado se o perfil
passar. Caso contrário, aparece como `unavailable: resource_profile_unvalidated`
(P6-03).

### Revisão e adjudicação

#### D16 — Evidência e contexto do revisor

**O que o revisor vê:**

- **Detecção e segmentação:** a imagem de origem e uma `region`, a caixa que
  cobre as geometrias do candidato, com 10% de margem e recortada aos limites
  da imagem.
- **Classificação:** a imagem inteira.
- Nunca vê classes, votos, contagens ou identidades.

**Evidência tipada** (substitui o `dict` livre da 5.1):

- revisão de imagem na classificação: `{"class_ids": [...]}`, com uma ou mais
  classes distintas;
- candidato de detecção: `{"decision": "object", "class_id": …, "geometry": {retângulo}}` ou `{"decision": "no_object"}`;
- candidato de segmentação: o mesmo, com polígono.
- A evidência é validada com as regras do documento.

**Na rodada 2:** cada revisor é mais uma observação na matriz de classes do
candidato. A geometria do revisor entra no refinamento quando o candidato é
aceito.

**Motivo:** a região é o mínimo para o revisor saber onde olhar. Votos, classes
e nomes ancorariam a resposta.

#### D17 — Composição da resolução da imagem

**A proposta:** cada rodada guarda uma proposta imutável. Ela traz a decisão de
cada candidato (classe ou existência, geometria, métricas, motivo) e o
documento da imagem.

**Composição:**

- Só acontece quando todos os candidatos estão fechados, seja por aceitação
  automática na última rodada, seja por adjudicação.
- Gera um documento canônico com os objetos em ordem de chave e novos ids
  estáveis por versão.
- O documento vira a versão n+1 de `resolved_annotations`:
  - `source` é `automatic_consensus`, ou `expert_adjudication` se algum
    candidato foi adjudicado;
  - a versão anterior recebe `superseded_at`.

**Garantias:**

- Um índice único parcial garante uma única versão vigente por imagem.
- A ingestão trava a linha da rodada e confere o status e as impressões
  digitais.
- Há uma única proposta por rodada, garantida por restrição única. Por isso,
  um resultado duplicado não tem efeito.

**Precedência:** uma rodada automática nunca substitui sozinha uma versão
adjudicada. A proposta dela espera aceite explícito, com justificativa
(P6-06).

#### D18 — Versões esperadas em nova tentativa, aceite e adjudicação

**Escolha:** os três pedidos levam:

- `expected_evidence_generation`;
- `expected_configuration_fingerprint`, a da última rodada, ou `null`;
- `expected_resolution_version`, que é 0 quando não há versão.

**Erros:**

- `409 version_conflict`, para evidência ou resolução divergente;
- `409 resolution_config_conflict`, para configuração divergente;
- `409 resolution_in_progress`, quando há rodada ativa;
- `409 resolution_not_ready`.

Os três exigem `Idempotency-Key`.

#### D19 — Configuração da nova tentativa

**Escolha:**

- O pedido pode trazer uma `configuration`; sem ela, vale o snapshot do lote.
- Passa pelos mesmos esquemas e pisos.
- Fica gravada na rodada e auditada.
- Nunca altera o snapshot do lote.

**Motivo:** a CE-F07 e o plano do App ("retry … with a new explicit
configuration").

**Rejeitada:** reutilizar sempre o snapshot. É mais simples, mas como o
algoritmo é determinístico, repetir a mesma configuração só ajuda depois de uma
falha.

#### D20 — Independência do adjudicador (P6-04)

**Escolha:**

- `require_independent_adjudicator`, padrão `false`, vale na política padrão e
  no snapshot do lote.
- **Contribuinte** é quem anotou a geração atual do item, ou quem revisou
  qualquer work item dele.
- **Com `false`:** o contribuinte pode adjudicar, mas a resposta e a auditoria
  registram `contributor_conflict: true`, e a justificativa é obrigatória.
- **Com `true`:** o contribuinte recebe `403 adjudicator_not_independent`, e o
  caso continua pendente.

#### D21 — Leases de resolução (P6-08)

**Rotas:**

| Método | Rota | Uso |
| --- | --- | --- |
| `POST` | `/projects/{id}/resolution-work-items/{w}/lease` | adquirir ou renovar |
| `DELETE` | `/projects/{id}/resolution-work-items/{w}/lease` | liberar |
| `POST` | `/projects/{id}/resolution-work-items/{w}/lease/revoke` | revogar (dono ou gerente), com `reason` obrigatório e auditoria |

**Tempos:**

- o lease dura 15 min e é renovado a cada 5 min;
- o teto é de 2 h;
- a expiração é decidida pelo relógio do servidor a cada pedido, sem
  varredura.

**Regras:**

- `edit_proposal`, `edit_submission` e `replace` exigem o lease de quem pede.
- `accept_proposal` não exige, mas devolve `409 lease_held` enquanto outra
  pessoa tiver o lease.
- Nova tentativa e cancelamento seguem a mesma regra.

#### D22 — Falha permanente e cancelamento

**Escolha:** quando a falha é permanente ou o gerente cancela:

- a rodada fica `failed` ou `cancelled`, com a evidência preservada;
- o item fica `review_required`;
- nasce um work item de imagem só para especialista, sem revisores.
  - O motivo é `worker_failed`, `resolver_unavailable`,
    `resolver_output_invalid` ou `expert_required`.

O gerente pode então tentar de novo ou adjudicar. Isso exige
`create_expert_work_item`, ao lado de `create_review_work_item`.

#### D23 — O que o anotador vê depois da resolução (P6-07)

**Escolha:**

- `GET /assignments/{id}` passa a trazer
  `resolution: {version, source, objects}`, só depois que a imagem é resolvida.
- `source` é `single_submission`, `automatic_consensus` ou
  `expert_adjudication`.
- Nunca traz votos, colegas ou diagnósticos.

#### D24 — Observações de desempenho e a rota agregada

**Escolha:**

- **Gravação:** as observações são gravadas na transação do aceite ou da
  adjudicação.
  - Uma chave única por resolução, objeto de origem e métrica torna as novas
    tentativas inofensivas.
  - Quando uma versão é substituída, suas observações recebem
    `summary_eligible = false`. Nenhuma observação é reescrita.
- **Leitura:** `GET /annotator-performance` agrega na hora da consulta.
  - Uma linha nomeada com menos de 30 decisões é suprimida.
  - Uma célula com menos de 5 observações é suprimida.

**Rejeitada:** a tabela `annotator_performance_summaries`. O plano a chama de
"cache regenerável", e nada precisa de cache neste tamanho. A estatística
publicada é da Fase 7. **Ponto para o Meirelles confirmar.**

#### D25 — Eventos

**Escolha:** a outbox recebe `resolution.started`, `resolution.completed`,
`resolution.review_required` e `resolution.adjudicated`, só com
identificadores e estado. A entrega é da Fase 8.

#### D26 — Autorização

**Escolha:**

- Entra `work_candidate_review` (dono, gerente e anotador), que o plano nomeia.
  As quatro rotas do revisor passam a usá-la.
- A matriz vai para 14 ações e 56 pares.
- As rotas de evidência, nova tentativa, adjudicação, lease e desempenho usam
  as quatro ações que já existiam sem uso.

#### D27 — A fila do gerente

**Escolha:** só a rota do plano,
`GET /projects/{id}/batches/{batch_id}/resolutions`.

- **Cada linha é um work item,** de imagem ou de candidato.
- **Ordenação:** primeiro as falhas, depois os motivos de especialista, depois
  os mais antigos.
- **Paginação:** 50 por página.
- **Filtros:** estado, motivo, estratégia e idade mínima.
- **Os filtros "lote, finalidade e tarefa" da A6-01** viram o seletor de lote
  do App, porque o projeto tem uma única tarefa.

#### D28 — Rotas e comandos além da tabela do contrato

**Escolha:**

- **Rotas:**
  - os leases (D21);
  - `POST /projects/{id}/resolution-runs/{run_id}/cancel`;
  - `GET /projects/{id}/resolver-eligibility` (D11);
  - `GET /projects/{id}/annotation-policy/history`, montada a partir da
    auditoria, para o histórico somente leitura da A6-04.
- **Comandos:**
  - `dada-api consensus-relay`;
  - `dada-api resolver-quarantine list|release --reason`. A liberação exige
    que a fixture de saúde passe.

**Motivo:** o mesmo da Fase 4 (D7). O comportamento é da fase, e essas rotas
são o único jeito de alcançá-lo.

#### D29 — Dependências

**Escolha:** um extra opcional `consensus`, com versões exatas: `numpy`,
`scipy`, `opencv-python-headless`, `crowd-kit==1.4.2` e `pandas`.

- O `uv.lock` é regenerado com `uv`, instalado por pip no ambiente `dada2`.
- O CI passa a usar `uv sync --extra dev --extra consensus --frozen`.
- Os testes de algoritmo são pulados, com o motivo explícito, quando o extra
  não está instalado.

**Ressalva registrada:** os requisitos base do crowd-kit 1.4.2 trazem
`transformers`, `nltk`, `pyarrow` e `scikit-learn`, sem torch.

### Decisões do App

- **A-1, sobreposição somente leitura.**
  - Um `EvidenceStage` desenha várias fontes em SVG na escala da imagem. Ele
    reaproveita as primitivas de forma e de viewport do `ImageStage`, sem
    estado de edição.
  - A segmentação aparece como polígonos preenchidos, porque nossas máscaras
    são polígonos, com controle de transparência.
  - Cada fonte tem uma cor e um tracejado estáveis.
  - O modo lado a lado entra abaixo de 1200 px ou com mais de quatro fontes.
  - Uma tabela não visual está sempre presente.
- **A-2, configuração do resolver.**
  - Um `ResolverConfigForm` compartilhado, guiado pelos descritores da D9.
  - Os controles avançados ficam recolhidos.
  - Estratégias indisponíveis aparecem desabilitadas, com o motivo exato.
  - É usado no assistente, nas configurações e na política do lote, e
    substitui o campo `agreement`.
- **A-3, revisor.**
  - O `CandidateReviewPage` troca a caixa de JSON pelo `ImageStage`, limitado
    a um objeto dentro da região.
  - Há uma opção **Não existe**.
  - A chave de recuperação é
    `dada.review-recovery:{projectId}:{reviewAssignmentId}:{baseVersion}`.
- **A-4, adjudicação.**
  - O editor usa o `ImageStage` sobre a fonte escolhida: a proposta (padrão),
    uma submissão bruta ou um documento em branco.
  - O lease é renovado a cada 5 min, com aviso ao sair da página.
  - A chave de recuperação é
    `dada.adjudication-recovery:{projectId}:{workItemId}:{userId}:{baseVersion}`.
  - Toda ação pede confirmação. Pedem justificativa a edição, a substituição,
    a nova tentativa, a revogação e a autoadjudicação com conflito.
  - Num `409`, o rascunho é preservado e o App mostra a comparação entre
    origem, base e versão nova.
- **A-5, rotas.**
  - `/projects/:id/consensus`, `/consensus/images/:batchItemId` e
    `/consensus/work-items/:workItemId`, como no plano do App.
  - Os protótipos de agosto são substituídos.
- **A-6, progresso.**
  - As contagens de resolução aparecem em `ProjectBatchesPage` e num selo no
    cartão do projeto.
  - `ProjectActivityPage` fica como está (Fase 7).
  - O workspace mostra a anotação final quando a D23 a fornece.
- **A-7, I6-01.** O defeito é reproduzido no navegador antes de qualquer
  mudança, e a resolução é registrada no arquivo de issues.

## Implementação

Status: API implementada em 2026-10-14, na branch `phase-6`, sem commit. O App
fica para uma etapa seguinte. Tudo continua pendente da revisão do Meirelles.

Guia de operação: [development.md](../development.md#consensus-engine-phase-6).
Formas no contrato do App: `dada-app/docs/api-contract.md`, seção "Phase 6
implemented shapes".

### Persistência

Migração `20261014_0010`, exercitada upgrade → downgrade → upgrade, com
`alembic check` limpo.

- **Tabelas novas:**
  - `resolution_runs` e `resolution_proposals`;
  - `resolution_object_evidence`;
  - `adjudications` e `resolution_leases`;
  - `performance_observations`;
  - `resolver_quarantines` e `resolver_calibration_snapshots`.
- **Colunas novas:**
  - `resolved_annotations` ganhou a origem, a proposta, a execução, quem
    aceitou e `superseded_at`, com um índice único parcial que garante
    exatamente uma resolução corrente por imagem;
  - política e lote ganharam `require_independent_adjudicator`;
  - o lote ganhou `calibration_snapshot_id`.
- **Migração de dados:** os identificadores provisórios (`majority_vote`,
  `two_stage_box_fusion`, `two_stage_mask_fusion`) passaram para os três
  pipelines, com a configuração padrão e `resolver_version = "1.0.0"`, nos
  padrões de projeto e nos lotes.

### Rotas e comandos

| Rota ou comando | Função |
| --- | --- |
| `GET /projects/{id}/batches/{batch_id}/resolutions` | Fila do gerente, por gravidade e idade |
| `GET /projects/{id}/batch-items/{item_id}/evidence` | Toda a evidência de uma imagem |
| `POST /projects/{id}/batch-items/{item_id}/resolve` | Nova tentativa, com versões esperadas e configuração opcional |
| `POST /projects/{id}/resolution-runs/{run_id}/cancel` | Cancela uma execução ativa |
| `POST/DELETE /projects/{id}/resolution-work-items/{work_item_id}/lease` | Adquire, renova ou libera o lease de edição |
| `POST /projects/{id}/resolution-work-items/{work_item_id}/lease/revoke` | Revoga um lease abandonado |
| `POST /projects/{id}/resolution-work-items/{work_item_id}/adjudicate` | Decisão do especialista |
| `GET /projects/{id}/annotator-performance` | Desempenho agregado, com supressão |
| `GET /projects/{id}/resolver-eligibility` | Elegibilidade das estratégias condicionais |
| `GET /projects/{id}/annotation-policy/history` | Histórico somente leitura da política |
| `dada-api consensus-relay` | Relay do outbox: cria, recupera e despacha execuções |
| `dada-api resolver-quarantine list\|add\|release` | Quarentena operada à mão |
| `celery -A dada_api.workers.celery_app worker` | Worker das filas `consensus.standard` e `consensus.mask` |

`/capabilities` trocou `consensus_resolvers` por `consensus_pipelines`. O
`openapi.json` foi de 49 para 59 rotas e de 69 para 99 schemas.

### Autorização

A matriz foi para 14 ações e 56 pares com `work_candidate_review` (owner,
manager e annotator), usada pelas rotas de revisão escopada. As rotas do
gerente usam `read_annotation_evidence`, `run_resolution`, `adjudicate` e
`read_annotator_performance`. A elegibilidade e o histórico da política usam
`manage_annotation_policy`.

### Desvios das decisões acima

Cada desvio tem um motivo:

- **D4 — adaptador falso.** Os testes instalam o falso em
  `consensus.pipeline.ADAPTERS`, em vez de registrá-lo no ambiente `test`.
  Registrado, ele apareceria em `/capabilities`.
- **D4 — confirmação e novas tentativas.**
  - O Celery confirma a mensagem cedo, e quem decide as novas tentativas é o
    banco. Cada comando leva o número da tentativa; uma mensagem repetida
    cuja tentativa não é mais a atual é ignorada.
  - Motivo: o Redis reentrega mensagens não confirmadas depois do seu tempo de
    visibilidade, mesmo com o worker ainda rodando. Com `acks_late`, isso
    viraria execução duplicada.
- **D4 — memória.** Não há `RLIMIT_AS`, porque ele conta a memória virtual que
  as bibliotecas numéricas reservam ao importar. A memória é protegida por três
  coisas:
  - a estimativa prévia de complexidade;
  - o teto de memória por filho do Celery, que os alvos `make worker-*`
    passam a partir de `DADA_CONSENSUS_*_MEMORY_BYTES`;
  - o limite do container do worker (P8-04).
- **D6 — precedência do estado do lote.**
  - A ordem é: `resolved`; depois `annotating`, enquanto houver imagem
    `pending`; depois `review_required`; por fim `resolving`.
  - Isso mantém a regra da Fase 5 de que o lote anota até a última imagem ser
    entregue.
- **D9 — formato das capabilities.**
  - Cada entrada traz `unavailable_reason`, nulo quando disponível, em vez de
    `availability: {available, reason}`.
  - Não há `applicability`, porque os pipelines são indexados pelo tipo de
    tarefa.
  - Os campos de correspondência são planos (`matching_iou`, e
    `matching_metric` com `matching_threshold`), e não o grupo
    `matching: {metric, threshold}` do exemplo da D9.
  - O App lê os descritores, então nenhum nome fica fixo no cliente.
- **D17 — `superseded_by` removido.** O número da versão seguinte já
  identifica a sucessora; `superseded_at` basta.
- **D28 — quarentena.**
  - Além de `list` e `release`, existe `add`, porque o texto do Meirelles diz
    que operadores podem pôr em quarentena uma versão defeituosa.
  - `--by` precisa nomear um administrador ativo, que fica registrado como
    quem liberou.
  - A "fixture de saúde" é empacotada em `consensus/health.py`, porque os
    testes não vão para o pacote instalado. Três documentos idênticos precisam
    virar a resposta conhecida, duas vezes de forma idêntica.
  - Só pipelines instalados entram em quarentena manual. A quarentena
    automática também é por pipeline.

### Decisões novas na implementação

- **D30 — ator do sistema na auditoria.**
  - **O quê:** `audit_entries.actor_user_id` passou a aceitar nulo, e nulo
    quer dizer que o sistema agiu sozinho.
  - **Por quê:** a CE-F11 pede auditoria de resultados automáticos, falhas e
    novas tentativas, e a P6-06 fala em "ator do sistema".
  - **Precedente:** a D1 da Fase 4 tornou `project_id` anulável pelo mesmo
    motivo.
  - **Downgrade:** as entradas do sistema são apagadas.
- **Estado do lote calculado num lugar só.** `batches.refresh_status`
  substituiu `_resolve_batch_if_done`. A função antiga só resolvia lotes ainda
  `annotating`, então um lote de consenso, que fica em `resolving`, nunca
  fecharia.
- **Reabrir durante a resolução.** Reabrir agora avança a geração de evidência
  em todos os estados depois da coleta: `awaiting_resolution`, `resolving`,
  `in_review` e `review_required`. Antes, só em `awaiting_resolution`.
- **Anéis canônicos de até 10.000 pontos.** O contorno traçado de uma máscara
  pode ter muito mais pontos que um polígono desenhado à mão, então o limite do
  documento canônico é `MAX_CANONICAL_RING_POINTS = 10_000`. A verificação de
  auto-interseção (`ring_is_simple`) passou a separar os segmentos por grade.
  Foi conferida contra a versão força bruta em 3.000 anéis, e um anel de 9.000
  pontos leva 0,28 s.
- **Anel canônico inválido vai para revisão.** Se o contorno traçado se
  auto-tocar, ou se o pós-processamento mudar a máscara materialmente, o
  candidato falha com `topology_invalid`. Nada é corrigido em silêncio.
- **RASA habilitado.** O perfil de recursos de `segmentation_rasa` foi medido
  dentro dos limites da fila `consensus.mask`.

### Interpretações nos módulos puros

Os módulos de estratégias de classe e de geometria foram escritos por agentes
a partir das fixtures. Estas são as leituras que eles fizeram onde o texto
deixava espaço:

- **Estratégias de classe:**
  - o suporte é a fração exata dos votos, sem peso, que o vencedor recebeu.
    Numa estratégia ponderada, o vencedor pode não ser o mais votado, e o
    suporte registrado é o dele;
  - um empate no topo dá só `class_tie`, e nada o desempata. Nos outros casos,
    as razões seguem a ordem suporte, depois posterior;
  - o portão da posterior existe só em `dirichlet_vote` e `dawid_skene`;
  - as três regras do `categorical_vote` (`plurality`, `strict_majority` e
    `supermajority`) chegam às mesmas decisões, porque o piso da política
    mantém o suporte acima de 1/2. Só a regra registrada muda;
  - os pesos de confiabilidade ficam entre 0,5 e 2,0, cortados sem
    renormalizar;
  - o Dawid-Skene usa só votos do pool e só itens com pelo menos três
    avaliadores distintos.
- **Correspondência e geometria:**
  - a ambiguidade é marcada dentro de uma faixa de sobreposição igual. Um
    empate entre os mesmos dois avaliadores não é marcado, porque essa imagem
    já vai para revisão por outro motivo;
  - um duplicado do mesmo avaliador é comparado com os objetos anteriores dele;
  - nos anéis externos, a área pelo shoelace é positiva em coordenadas de
    imagem (x para a direita, y para baixo), o que dá sentido horário na tela.
    Os buracos têm área negativa;
  - o preenchimento inclui os pixels por onde a borda passa, um viés de meio
    pixel para fora;
  - anéis degenerados no traçado são descartados e contados nos diagnósticos;
  - `segmentation_majority_vote` com dois avaliadores dá a união, porque o
    crowd-kit binariza em 0,5 inclusive;
  - com dois avaliadores que discordam muito, `segmentation_em` pode dar quase
    todo o peso a um deles.

**Para o Meirelles conferir:**

- **Buracos crescem 1 px.** Um buraco cresce cerca de um pixel a cada vez que
  um contorno traçado é rasterizado de novo. É consequência de incluir os
  pixels da borda no preenchimento.
- **Dois avaliadores na máscara.** Com dois avaliadores, a votação por maioria
  vira união. Pode ser preferível exigir três para máscaras.

## Defeitos encontrados

- **Corrida na revisão da 5.1.**
  - Duas últimas revisões simultâneas podiam, cada uma, ver um revisor ainda
    pendente, e nenhuma marcava o item pronto.
  - A entrega da revisão agora trava o item de trabalho antes de contar, e a
    passagem para a segunda rodada trava a imagem.
  - Coberto por `test_concurrent_final_reviews_open_exactly_one_second_round`.
- **Restrição da 5.1 sem a geração.**
  - `uq_resolution_candidate_run` era única em
    `(batch_item_id, candidate_key, source_run_number)` e ignorava a geração de
    evidência.
  - O caso de imagem tem sempre a chave `image`, então uma imagem reaberta que
    voltasse à revisão na nova geração violava a restrição.
  - Ela foi removida. `uq_resolution_candidate`, por entrada de resolução,
    continua garantindo a unicidade dentro de cada geração.
- **Auditoria sem ator do sistema.** `audit_entries.actor_user_id NOT NULL`
  impedia auditar decisões automáticas (D30).

## O que ficou de fora

| Item | Motivo |
| --- | --- |
| App da Fase 6 (passos 15 a 22) | Combinado: API primeiro, com commit, e o App numa etapa seguinte |
| Entrega dos eventos em tempo real | Fase 8; os eventos ficam no outbox com o formato sem identidade |
| Política de retenção dos logs | Fase 8 |
| Limite de memória no nível do container | P8-04 |
| Modo de rótulo único para classificação | Adiado desde a D6 da Fase 5 |

## Verificação

Executado contra PostgreSQL e Redis reais dos containers do Compose, com o
ambiente conda `dada2`.

- `ruff check` e `ruff format --check`: limpos. `alembic check`: sem divergência.
- Testes da API: **619 passaram** com integração habilitada, contra 316 no início.
- `openapi.json` regenera de forma determinística.
- O processo da API não importa numpy, SciPy, OpenCV, pandas nem crowd-kit.
  Isso foi verificado em `dada_api.main` e em `dada_api.cli`.

### Cobertura dos critérios de saída

| Critério | Como foi provado |
| --- | --- |
| Fixtures douradas determinísticas nas três tarefas | `test_every_golden_case_replays_to_its_recorded_decision`, `test_any_vote_order_reaches_the_same_decision`, `test_replay_is_deterministic_and_order_independent` (classificação), `test_replay_is_byte_identical` (detecção e segmentação) |
| As três estratégias iniciais passam nas fixtures da tarefa | Fixtures `categorical_*`, `multilabel_*` e `dirichlet_*`; `test_the_dirichlet_strategy_uses_the_posterior_gate`; `test_every_initial_strategy_combination_resolves_agreement` (detecção); `test_every_refinement_runs_after_the_class_decision` (segmentação) |
| As condicionais passam com corpus elegível e inelegível | `test_calibration.py`, as fixtures `reliability_*` e `dawid_skene_*`, `test_conditional_strategies_report_and_enforce_their_evidence` e `test_reliability_weights_are_frozen_from_adjudicated_evidence` |
| Baixa concordância chega à revisão | `test_low_agreement_reaches_a_reviewer_then_a_second_round`, `test_a_second_failure_goes_to_an_expert`, `test_classification_resolves_end_to_end_through_review`, `test_low_box_agreement_needs_review_despite_unanimous_class`, `test_low_mask_agreement_needs_review` |
| Nenhuma submissão bruta é alterada | `test_an_expert_edits_from_a_raw_submission_without_changing_it`, e a comparação de submissões e revisões antes e depois do fluxo completo em `test_classification_resolves_end_to_end_through_review` |
| Uma adjudicação fecha a imagem | `test_an_adjudication_closes_a_failed_image` (a imagem e o lote ficam `resolved`) |
| Resultados duplicados não criam duas resoluções aceitas | `test_duplicate_stale_and_concurrent_results_accept_once` (repetido, atrasado e concorrente) |
| Observações corretas, por projeto, sem duplicar em nova tentativa | `test_acceptance_records_observations_once_and_supersession_closes_them`, `test_an_adjudicated_classification_is_eligible_for_weighting`, `test_detection_resolves_with_box_agreement_observations`, `test_segmentation_resolves_with_mask_agreement_observations`, `test_a_reviewed_false_positive_is_recorded_without_a_zero_overlap`, e as observações únicas em `test_duplicate_stale_and_concurrent_results_accept_once` |

## Implementação do App

Status: Passos 15 a 21 implementados em 2026-10-15, na branch `phase-6`, sem
commit. O Passo 22 (verificação no navegador) fica para outra sessão, então o
critério de saída do App ainda não foi percorrido ponta a ponta. Tudo continua
pendente da revisão do Meirelles.

### O que foi construído

| Superfície | Onde (`dada-app/src/`) |
| --- | --- |
| Contrato: capabilities, política e lote tipados, tipos e cliente do gerente, evidência tipada do revisor, chaves de consulta | `api/capabilities.ts`, `api/client.ts`, `features/consensus/consensus-types.ts`, `consensus-api.ts`, `review-types.ts`, `review-api.ts` |
| Chaves de idempotência com o hash do corpo | `api/idempotency.ts` |
| Configuração do resolvedor guiada pelos descritores, no assistente, nas configurações e na política de cada lote; elegibilidade e histórico | `features/projects/ResolverConfigForm.tsx`, `resolver-config.ts`, `NewProjectPage.tsx`, `ProjectSettingsPage.tsx`, `ProjectBatchesPage.tsx` |
| Tela do revisor: só a imagem e a região, uma caixa ou um polígono, ou **No object** | `features/consensus/CandidateReviewPage.tsx`, `review-draft.ts`, `review-recovery.ts` |
| Fila do gerente, com filtros e paginação | `features/consensus/ConsensusQueuePage.tsx` |
| Comparação de evidências, procedência das execuções, nova tentativa e cancelamento | `ImageEvidencePage.tsx`, `EvidenceStage.tsx`, `EvidenceShapes.tsx`, `SourceToggles.tsx`, `EvidenceTables.tsx`, `RetryDialog.tsx` |
| Adjudicação com lease, recuperação local e reconciliação de `409` | `WorkItemPage.tsx`, `adjudication.ts`, `adjudication-recovery.ts`, `useEditLease.ts`, `ConfirmDialog.tsx` |
| Contagens de resolução nos lotes, selo de revisão no card, anotação final no workspace | `ProjectBatchesPage.tsx`, `ProjectsPage.tsx`, `features/annotation/AnnotationWorkspacePage.tsx` |
| Rotas do gerente | `app/router.tsx` |

Os protótipos de agosto (`ConsensusReviewQueuePage`, `ConsensusReviewPage`)
foram removidos, porque chamavam rotas que não existem (A-5).

### Decisões tomadas na implementação

- **Chave de idempotência com o hash do corpo (I6-02).**
  - **O quê:** toda entrega, revisão, nova tentativa, cancelamento e
    adjudicação usa `{escopo}:{id}:{hash do corpo}`.
  - **Por quê:** a API guarda sob a chave toda resposta abaixo de 500, inclusive
    um `422`. Com uma chave só por versão, um documento corrigido depois de um
    `422` voltava como `409 idempotency_conflict`.
  - **Efeito:** o mesmo corpo continua reaproveitando a resposta original
    depois de uma resposta perdida.
- **Nomes dos grupos de estratégia.**
  - Os descritores listam as estratégias, mas não o grupo em que cada uma vai.
  - O App guarda três constantes: `class_strategy` em todas as tarefas,
    `box_refinement` na detecção e `mask_refinement` na segmentação.
  - **Para o Meirelles:** o descritor poderia trazer esse nome.
- **Padrão do Dice.**
  - A API usa 2/3 em `matching_threshold` e `minimum_median_overlap` quando a
    métrica é Dice e o campo é omitido. Os descritores não expressam esse
    padrão condicional.
  - O formulário espelha a regra: ao trocar a métrica, um campo ainda no padrão
    da métrica anterior passa ao padrão da nova, e um valor escolhido pelo
    usuário é mantido.
  - **Para o Meirelles:** o descritor deveria trazer o padrão condicional.
- **`ImageStage`.** Ganhou uma camada sobreposta somente leitura, usada para a
  região do candidato e para o contexto da adjudicação. Também passou a
  desenhar todos os anéis de um polígono, com os buracos, em vez de só o
  primeiro.
- **I6-01 substitui a decisão I5-03.**
  - **Antes:** cada pasta selecionada era cortada na própria raiz, então
    `norte/0001.jpg` e `sul/0001.jpg` colidiam, e a segunda era pulada.
  - **Agora:** com duas ou mais pastas, cada imagem mantém o nome da sua pasta,
    como se a pasta-mãe tivesse sido escolhida. Com uma pasta só, nada muda.
  - **Por quê:** era isso que impedia a criação, como mostrou o teste que
    reproduziu o I6-01. A mudança também deixa a importação de rótulos
    coerente: ela aceita uma única pasta, então rótulos de várias pastas só
    entravam pela pasta-mãe, com o nome da pasta no caminho.
  - **Também:** a quantidade mínima exibida passou a incluir o crescimento do
    percentual de validação e teste, e percentuais que somam 100% ou mais são
    recusados.
- **Contagens do card vêm dos lotes.** A API não devolve contagens no projeto,
  e o card lia campos que nunca chegavam. O selo e o total resolvido vêm agora
  de `GET /batches`. Um `403`, de quem não é owner ou manager, simplesmente os
  esconde.
- **`ApiError.details`.** O cliente passou a guardar os detalhes do erro, para
  mostrar `details.errors` e os pré-requisitos ausentes (`details.missing`).
- **Nova tentativa com configuração explícita (D19).** É opcional na
  confirmação, parte da configuração da última execução e é validada pelos
  mesmos descritores. A configuração do lote não muda.

### Interpretações onde os documentos não diziam

- **Link do caso.** Carrega `?item={batchItemId}`, porque nenhuma rota leva de
  um caso à sua imagem. Sem o parâmetro, a página aponta para a fila.
- **Chave de recuperação da adjudicação.** A versão-base é
  `{geração}.{versão da resolução}`. A impressão digital da configuração vai
  junto, para detectar conflito.
- **Perda do lease.** A API recria o lease silenciosamente quando ele expirou.
  Por isso, uma renovação que volta com outro lease conta como perda: o
  rascunho fica, e a edição para até o gerente readquirir.
- **Fila.** O filtro de estado nunca fica vazio, porque vazio significaria
  `review_required` no servidor. A idade tem opções fixas (1 hora, 1 dia,
  1 semana).
- **Estratégias.**
  - A primeira estratégia listada é o padrão, como no catálogo da API.
  - "Mais estrito" é um limiar de revisão acima do padrão.
  - "Muda a topologia" é qualquer passo de `post_processing` ligado.
- **Edição de uma submissão bruta num caso de candidato.** O ponto de partida
  são os objetos daquela submissão que pertencem ao candidato (`members`).
- **Métricas.** Só as chaves que a API registra são mostradas. Na detecção,
  isso é o IoU mediano por par, porque não há IoU por par individual.

### O que ficou de fora

| Item | Motivo |
| --- | --- |
| Pré-visualização em blocos ou reduzida para imagens grandes (A6-02) | Não há API de pré-visualização; o palco mostra a escala do zoom |
| Miniaturas na fila | A fila não carrega imagens; mostra o caminho |
| Foco preso no diálogo de confirmação | O foco entra no diálogo e Escape cancela, mas o foco não fica preso |
| Versões de dependência e evidência de calibração no histórico da política (A6-04) | A rota de histórico não as devolve |
| Quantidade de imagens no card (`media_count`) | A API não devolve; o card mostra "—". É anterior à fase 6 |

### Verificação

- `npm run check` verde: lint, **197 testes** em 37 arquivos (eram 67), build.
- **Não verificado:** o navegador (Passo 22), com estes cenários:
  - um resultado automático revisado e aceito;
  - um caso forçado editado e adjudicado;
  - um conflito de versão em duas abas;
  - dois revisores em sessões separadas.
- I6-01 e I6-02 recebem a declaração de resolução no arquivo de issues só
  depois de confirmados ao vivo.

### Cobertura do critério de saída do App (provisória)

| Critério | Testes de componente | Navegador |
| --- | --- | --- |
| Um resultado automático pode ser revisado e aceito | `ImageEvidencePage.test.tsx`; `WorkItemPage.test.tsx` ("lets a plain acceptance go without a note") | Pendente |
| Um caso forçado pode ser editado e adjudicado | `WorkItemPage.test.tsx` ("takes the lease, edits a raw submission, and records the decision with a rationale") | Pendente |
| Versões desatualizadas preservam o trabalho local | `WorkItemPage.test.tsx` ("keeps the local draft through a version conflict…"), `CandidateReviewPage.test.tsx` ("keeps the local draft on a stale version…"), `adjudication-recovery.test.ts` | Pendente |
| Issues pendentes resolvidos | I6-01: `NewProjectPage.test.tsx`, `ingest.test.ts`. I6-02: `idempotency.test.ts`, `assignment-view.test.ts`, `consensus-api.test.ts` | Pendente, com as declarações |
