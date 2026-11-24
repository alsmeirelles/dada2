# Phase 7 pending decisions

This is the canonical decision record for Phase 7. It contains the shared API
decisions `P7-01`–`P7-09` and the App decisions `A7-01`–`A7-03` from the
[API implementation plan](../api-implementation-plan.md) and the
[App adaptation plan](../../../dada-app/docs/annotator-disagreement-adaptation-plan.md).

The individual decision records below are the source of truth for Phase 7 decision status; the register summarizes them. Phase 7 implementation must not begin until the pending decisions are resolved and approved here. App issues I7-04 and I7-05 are implementation stages: address and verify them when implementation begins; they do not block starting the phase. Their details and evidence are tracked in [Phase 7 App issues](../../../dada-app/docs/issues_before_phase7.md).

When a decision is approved, replace its pending status with **APPROVED** and
record the chosen behavior, its main reason, any contract change, how it will be
verified, the approving owner, and the approval date. Add further detail only
when the decision needs it. This file is the source of truth for those
resolutions; the two implementation plans retain the phase gate and link here.

## Decision register

| ID | Area | Required outcome | Status |
| --- | --- | --- | --- |
| `P7-01` | Active-learning run and dataset export boundary | Exact accepted annotations given to the internal active-learning worker, its selection result, temporary run/artifact retention, and the final annotated-dataset export | **APPROVED** |
| `P7-02` | Active-learning selection | Initial task adapter, uncertainty ranking, media versus object targets, deterministic ties, object context, and unavailable-adapter behavior | **APPROVED** |
| `P7-03` | Iteration stopping and recovery | Validation metric per task, optional target, maximum iterations, evaluation point, and retry behavior | **APPROVED** |
| `P7-04` | Assisted segmentation | Whether it ships in Phase 7 and, if so, the provider, minimal request/result contract, authorization, timeout, and non-vote rule | **APPROVED** |
| `P7-05` | Quality statistics | Published metrics, formulas, authorized roles, and minimum-sample suppression | **APPROVED** |
| `P7-06` | HEIC/HEIF ingestion and browser rendition | Accepted types, decoder, original retention, deterministic lossless WebP rendition, pixel-coordinate invariant, delivery contract, App selection behavior, and verification | **APPROVED** |
| `P7-07` | Assistance model lifecycle and contract | Model availability, provider and authorized request/result behavior | **APPROVED** |
| `P7-08` | Batch and evaluation contract | Snapshots, jobs, evaluation cadence and recovery semantics | **APPROVED** |
| `P7-09` | DADA selection edge cases | Budget, clustering, insufficient candidates and reproducibility | **APPROVED** |
| `A7-01` | Acquisition activity UX | User-visible random/active-learning states, failure message, and retry action | **APPROVED** |
| `A7-02` | Quality presentation | Manager-visible values, suppression display, accessible table, and no annotator ranking | **APPROVED** |
| `A7-03` | Assisted-segmentation UX | Trigger, preview, accept/discard/edit, and safe failure without changing the draft | **APPROVED** |

## Fixed Phase 7 constraints

The resolutions below must preserve these existing decisions:

- Any training and evaluation used for selection are internal to the active-learning solution. Exporting, deploying, or experimenting with production models is outside the application scope.
- The durable product is an annotated dataset. Its export contains accepted
  resolutions and their media/target provenance; raw submissions, unresolved
  annotations, imported seeds, model seeds, and consensus proposals are
  excluded.
- The initial training batch does not count as an acquisition iteration. Each
  acquisition follows accepted resolutions; fixed test data is used only for
  final evaluation.
- Random acquisition may run only after the initial images are resolved.
  Active learning requests a batch from the selected solution using the accepted training set and eligible pool. Static `single_batch` projects do not acquire.
- Classification active learning selects media. Model-guided detection and
  segmentation select object targets inside media. The target's model-generated
  box or mask identifies the object to annotate, while the source image remains
  visible. The annotator labels only that target.
- Active learning and consensus are independent choices. A selected target may
  use either annotation mode; the model target cue is never a consensus vote.
- Training uses accepted `initial_training` data plus accepted acquisition data
  from earlier iterations. Validation is evaluation-only and the fixed test
  split is final-evaluation-only. Detection/segmentation training uses accepted
  selected object annotations and source-media context, never unselected
  objects from the image.
- A model seed is optional per-assignment draft assistance. It is never a
  submission, consensus vote, resolution proposal, or canonical resolution.
- Assisted-segmentation output is an aid for the annotator who owns the active
  assignment. It is never an independent vote.
- Phase 7 quality metrics must not create annotator-facing rankings or feed
  consensus weights. Project-level performance summaries use the immutable
  Phase 6 observations.
- An HEIC/HEIF source and its browser rendition share one canonical oriented
  pixel plane. The rendition has exactly the same width and height as the
  decoded primary source image, with no resize, crop, padding, or second
  orientation transform. Annotation geometry is stored in that plane.

## Resolution records

### P7-01 — Active-learning run and dataset export boundary

**Status:** **APPROVED**

**Purpose.** Define the small handoff between DADA and its internal
active-learning worker, and keep that handoff separate from the annotated
dataset delivered to the user. This prevents an iteration from training on the
wrong split, unresolved annotations, or unselected objects. It is not a general
training platform, model registry, or production-model export.


**Approved decision, clarified:** Use one internal run record for each batch request. The API supplies an immutable snapshot of accepted training resolutions and media, the eligible unlabeled pool, task, class mapping, requested size and solution configuration. Validation data, if supplied for evaluation, is separate from the acquisition pool. The selected solution returns an ordered batch of eligible media or object targets and provenance under the [shared contract](../active_learning/active_learning_requirements_specification.md#batch-selection-interface). Selection methods, training and model artifacts are solution internals. Performance evaluations use the target model at a user-selected frequency, not a proxy or helper model; cadence and stopping follow P7-03 and P7-08. Record evaluation results with target-model, data-snapshot and iteration provenance.

The API validates and records the batch, manages single-annotation or consensus workflows, and maintains accepted annotations in the canonical labeled pool. The next request uses a new accepted-data snapshot. Proxy and helper models and checkpoints are not kept by default. A configuration parameter may explicitly enable their retention. Temporary artifacts needed for a run or retry may be kept until no longer needed, then deleted unless retention is enabled. Record failures and retry against the same snapshot; retain run and evaluation provenance independently of helper artifacts.

Dataset export should be possible at any iteration (training, validation and test sets). Export the final accepted
annotations, media, classes, and provenance; do not export an application model or expose a generic training API. Dataset
export format for detection and segmentation should be selected by the user. Available formats: YOLO normalized or COCO.

**Approving owner:** DADA API/App owner

**Approval date:** 2026-11-09


### P7-02 — Active-learning selection

**Status:** **APPROVED**

**Purpose.** Give active learning an executable selection rule. This is the
core product decision: without it, the system knows when to run an iteration
but not how to choose the most useful next annotations.

**Approved decision:** use DADA as the active learning framework [DADA](../active_learning/dada_active_learning_requirements_specification.md).
Other frameworks can be implemented in the future and if another option exists, the user may select it from a dropdown.
General modularity requirements and architecture definitions for any active learning solution are defined in [AL](../active_learning/active_learning_requirements_specification.md)
and should be followed.

**Approving owner:** DADA API/App owner

**Approval date:** 2026-11-09


### P7-03 — Iteration stopping and recovery

**Status:** **APPROVED**

**Purpose.** Make the annotation loop stop and recover predictably. This keeps
the API, worker, and App from applying different stopping rules or advancing
after a failed iteration.


**Decision:** Let the user choose accuracy or F1 for classification, mAP@50 for
detection, and mean IoU for segmentation. Let the user choose when to evaluate, with possibilities to
evaluate the target model at every acquisition iteration or after every K iterations. Stop when the maximum acquisition count is reached or the optional metric target is met. Retry a failure from the same accepted-resolution snapshot as a new attempt.

**Approving owner:** DADA API/App owner

**Approval date:** 2026-11-09

### P7-04 — Assisted segmentation

**Status:** **APPROVED**

**Purpose.** Decide whether Phase 7 includes interactive segmentation help. If
it does, define enough of the boundary that a suggestion cannot bypass
assignment authorization or become annotation evidence by itself.

**Decision:** Implement the feature.

**Rationale:** Use the last trained model (if in active learning mode) to produce masks or bounding boxes for segmentation / detection assignments. Accept point/box prompts and return editable polygons in original-
image coordinates. A timeout leaves the draft unchanged. The annotator must
accept the suggestion before it becomes draft geometry, and it never counts as
a submission or vote. If the feature is deferred, approve that explicit
deferral and keep the current placeholder.

**Approving owner:** DADA API/App owner

**Approval date:** 2026-11-09

### P7-05 — Quality statistics

**Status:** **APPROVED**

**Purpose.** Ensure that published quality numbers have one meaning and do not
expose unreliable or private annotator comparisons.

**Decision:** Publish review rate, resolution rate, and the
task-appropriate agreement summaries. Owners and managers may see performance
summaries after at least 30 eligible decisions; hide cells below five
observations. Annotators do not receive named performance data or rankings.

**Approving owner:** DADA API/App owner

**Approval date:** 2026-11-09


### P7-07 — Assistance model lifecycle and contract

**Status:** **APPROVED**

**Decision needed:** Define the provider, model selection and retention, availability before the first target evaluation and outside AL mode, authorization, timeout, and request/result contracts for detection and segmentation assistance. Reconcile boxes, polygons and supported prompts with A7-03.

**Decision:** Use the latest compatible target model with an explicit assistance retention policy; report assistance unavailable when no compatible model exists. Authorize against the active assignment, impose a bounded timeout, and return typed geometry in canonical coordinates. Never persist a suggestion without explicit acceptance into the draft.

**Implementation suggestions:** Use an internal provider interface that loads the latest compatible retained target model and reports a stable unavailable reason when absent. Apply a configurable 30-second timeout; authorize project membership and the active assignment before reading media. Accept an assignment ID, canonical-plane point/box prompts and a request ID; return typed box or polygon geometry, model provenance and status. Reject invalid coordinates and keep drafts unchanged on timeout or failure. Define target-model retention and cleanup for assistance independently of helper-model retention.

**Approving owner:** DADA API/App owner

**Approval date:** 2026-11-09

### P7-08 — Batch and evaluation contract

**Status:** **APPROVED**

**Decision needed:** Specify versioned request/result schemas, snapshot and media access, job states, errors, idempotency and retry; define evaluation data requirements and delivery of results. Specify K bounds and first evaluation point, metric aggregation, threshold direction, empty validation and pool exhaustion behavior.

**Decision:** Use immutable identified snapshots and a durable idempotent job per iteration and attempt; retries use the same snapshots. Evaluations should be performed over the validation set (defined at project creation) and over the test set after the last iteration and persist target-model metrics and provenance. Evaluate after every K completed acquisition iterations, K >= 1, and stop on an explicitly configured threshold or maximum; define task-specific averaging and unavailable-data errors before implementation.

**Implementation suggestions:** Use a versioned manifest schema shared by input and selection output, preserving media references and adding selected object geometry when needed; include snapshot IDs, task, class mapping, requested size, solution version and configuration. Use queued, running, succeeded, failed and cancelled job states with structured errors and an idempotency key scoped to project, iteration and attempt. Retry as a new attempt against the same immutable snapshots. Persist evaluation data and model provenance; define macro F1 across classes and class-averaged IoU with an explicit absent-class rule, treat all listed metrics as higher-is-better, and report an unavailable-data error for empty validation. Define first evaluation at iteration K, with final test evaluation after the last iteration. The exact schema and rules require approval.

**Approving owner:** DADA API/App owner

**Approval date:** 2026-11-09

### P7-09 — DADA selection edge cases

**Status:** **APPROVED**

**Decision needed:** Resolve requested budget versus DADA configuration, insufficient candidates, empty or undersized clusters, zero uncertainty, quota redistribution, random seeds and tie-breaking.

**Decision:** The batch request is authoritative for Q. Cap clusters by candidate count, allocate by largest remainder with capacity-aware redistribution, use equal weights when all scores are zero, and return all available candidates with a reason when fewer than Q exist. Persist seeds and use stable identifiers for ties; define empty-pool behavior explicitly.

**Approving owner:** DADA API/App owner

**Approval date:** 2026-11-10

### P7-06 — HEIC/HEIF ingestion and browser rendition

**Status:** **APPROVED**

**Decision.** The App and API accept `.heic` and `.heif` files with
`image/heic` and `image/heif` media types. Sequence extensions and media types
remain unsupported because one uploaded file must identify one dataset image.
The API adds `pillow-heif`, inspects the actual decoded format, and uses the
container's primary image. HEIF orientation and mirror transformations are
applied exactly once before dimensions are recorded.

The verified original bytes remain the content-addressed source. At upload
completion the API also creates one deterministic, versioned, lossless WebP
sidecar from the oriented primary image. The conversion uses a deterministic
8-bit sRGB RGB or RGBA pixel representation, preserves alpha when present,
carries the resulting color profile, and enables the WebP encoder's exact mode
to preserve transparent RGB values. It performs no resize, crop, padding,
sharpening, or other image alteration. Lossless WebP is required so conversion
introduces no
additional compression loss that could hide small objects. Here, source and
rendition being the same size means identical pixel width and height; their
encoded byte lengths are not expected to match.

`ContentObject.width` and `ContentObject.height` describe this canonical
oriented pixel plane. The signed media-content route serves the WebP sidecar as
`image/webp` for HEIC/HEIF sources and reports the sidecar byte length. Existing
JPEG, PNG, and WebP delivery remains unchanged. Browser annotation, review,
assisted segmentation, training, and evaluation use the same canonical
rendition. A consumer that decodes the retained original and applies its HEIF
transformations obtains the same dimensions and coordinate origin, so stored
boxes, polygons, and masks map directly to the original.

The sidecar key is derived from the project, source SHA-256, and rendition
version, for example `renders/v1/<source-sha>.webp`. This preserves the existing
source digest and deduplication invariant and requires no database migration.
Creation is atomic; duplicate source content reuses the existing sidecar. A
source is not promoted to usable media unless full decode and sidecar creation
succeed. CPU-bound decode/encode work runs in a bounded thread rather than on
the async event-loop thread. Invalid, unsupported, over-limit, or failed
conversions fail the upload with a stable structured error and never expose a
raw-only media record. Decode, declared/actual-format mismatch, and decoder
security-limit failures use `invalid_image`; a valid decoded image that cannot
be written as the required rendition uses `image_conversion_failed`.

The App uploads original bytes and does not bundle a HEIC decoder or transcode
in the browser. One shared format registry maps MIME types and extensions,
builds both file-input `accept` values, and filters formats against
`supported_image_media_types` from `/api/v1/capabilities`. Both new-project and
resumed-draft selection use that registry and describe HEIC/HEIF support in the
visible format help.

Learning manifests identify the source SHA-256 and rendition version. Image
consumers use the rendition path so the pixels presented to models and
assisted-segmentation providers are the pixels on which browser annotations
were drawn. Export metadata retains the canonical width, height, orientation
rule, and rendition identity alongside the original source identity.

**Rationale.** Raw HEIC delivery depends on browser support, while client-side
conversion duplicates a heavy codec in every browser and lets conversion
behavior vary by client. A server-created lossless rendition gives every App,
worker, and export one display plane, preserves the uploaded source for
provenance, and keeps storage changes small.

**Rejected alternatives.** Serving raw HEIC was rejected because the supported
Chrome and Firefox clients cannot rely on decoding it. Lossy WebP or JPEG was
rejected because additional compression can remove small annotation targets.
Browser-side conversion was rejected because it increases App complexity and
cannot enforce one decoder, orientation, and color policy. Replacing the source
with WebP was rejected because it breaks source checksums and provenance.
On-demand conversion was rejected because annotation requests would pay the
decode cost and could observe inconsistent failures.

**Contract and implementation effects.** The capability list adds
`image/heic` and `image/heif`; upload validation, format sniffing, storage,
signed media delivery, learning manifests, App selection, help text, and tests
change as described above. No annotation payload or geometry schema changes.
No data migration is required.

**Verification.** Commit representative 8-bit, 10-bit, portrait-oriented,
landscape, alpha, and invalid/truncated HEIC/HEIF fixtures. Tests must prove
format acceptance and spoof rejection, source checksum retention, deduplication,
atomic failure, rendition reuse, `image/webp` delivery, correct content length,
and exact canonical width/height. Decode each generated WebP and compare every
pixel with the deterministic 8-bit oriented source decode. App tests cover typed
and MIME-less files, both file inputs, capability filtering, and annotation in
the two latest Chrome and Firefox releases. An end-to-end geometry fixture must
draw and reload a small box and polygon at image edges and confirm unchanged
coordinates against the retained original.

**Approving owner:** DADA API/App owner

**Approval date:** 2026-10-24

### A7-01 — Acquisition activity UX

**Status:** **APPROVED**

**Purpose.** Let users understand whether the next annotation batch is being
selected randomly or through active learning, and what they can do after a
failure.

**Decision:** Use one activity card. Show `Selecting randomly`,
or `Training`, `Evaluating`, and then `Selecting images`/`Selecting objects`.
Show ETA only when the API provides one. On failure, show the API reason and a
Retry action to authorized users.

**Approving owner:** DADA API/App owner

**Approval date:** 2026-11-09

### A7-02 — Quality presentation

**Status:** **APPROVED**

**Purpose.** Present quality statistics without turning missing or suppressed
data into misleading zeros and without creating annotator rankings.

**Decision still needed.** Define what owners/managers see, how insufficient
samples appear, and the accessible non-chart representation.

**Decision:** Add a manager-only Quality section with a small
table for review rate, agreement, and task metrics. Render suppressed values as
`Not enough data`. Do not add annotator-facing rankings. Charts and CSV export
can be added later if there is a concrete need.

**Approving owner:** DADA API/App owner

**Approval date:** 2026-11-09

### A7-03 — Assisted-segmentation UX

**Status:** **APPROVED**

**Purpose.** Keep model assistance under the annotator's control and prevent a
failed or unwanted suggestion from changing saved work.

**Decision:** Place an `Assist segmentation` action beside the
drawing tools. Preview the result before it changes the draft; let the annotator
accept, discard, or edit it. For an object-target assignment, limit edits to the
highlighted target. Offline and timeout errors leave the existing draft
unchanged.

**Approving owner:** DADA API/App owner

**Approval date:** 2026-11-09


## Resolution checklist

Before changing a status to **APPROVED**, record:

1. the chosen behavior and its main reason;
2. any API, App, worker, or data-model change;
3. the verification that will prove it works; and
4. the approver and approval date.

After all pending records are approved, the implementation plans refer to this record for their current status.

## Decisões

Fechadas em 2026-11-23 com a Stephany, sob as decisões P7-01 a P7-09 e A7-01 a
A7-03 acima. Só cobrem o que aqueles registros e as especificações de
aprendizado ativo deixavam sem definição; nada aprovado acima foi reaberto.
**Continuam sujeitas à revisão do Meirelles.**

A implementação é feita em três blocos: o ciclo de aquisição na API (bloco 1),
a solução DADA, os alvos por objeto e a assistência (bloco 2), e as saídas, o
App e o fechamento (bloco 3).

### Ciclo e dados

#### D1: Configuração de aprendizado ativo no projeto

**Escolha:**

- Colunas novas no projeto: `max_acquisition_iterations`,
  `learning_solution`, `learning_solution_version`, `learning_configuration`,
  `evaluation_metric`, `evaluation_interval` (o K) e `metric_target`.
- `max_acquisition_iterations` é obrigatório na criação de projetos `split` e
  vale também para a aquisição aleatória. Projetos `single_batch` não aceitam
  nenhum desses campos. Projetos criados antes da migração ficam com o máximo
  nulo, o que quer dizer "até acabarem as imagens elegíveis".
- Com `active_learning`, os campos omitidos recebem os padrões: a primeira
  solução disponível do catálogo para a tarefa, a métrica padrão da tarefa,
  K = 1 e a configuração padrão da solução. Com `random`, os campos de solução
  e avaliação ficam nulos.
- A API recusa solução desconhecida, indisponível ou incompatível com a
  tarefa, métrica fora da tarefa e configuração inválida, sempre com `422`.
- Tudo muda pelo `PATCH` versionado, em `draft` ou `active`, com auditoria
  `project.learning_settings_changed`. Cada execução copia a configuração
  vigente, então uma mudança vale a partir da próxima.

**Motivo:** mesmo padrão da estratégia de aquisição (D1 da Fase 5), sem tabela
de configuração.

#### D2: Execuções e avaliações

**Escolha:**

- `learning_runs` tem uma linha por iteração e tentativa: finalidade
  (`selection` ou `final_evaluation`), estratégia, solução e versão,
  configuração e impressão digital, tamanho pedido, semente, plano de
  avaliação, retratos, estado, etapa, fila, tempos, resultado e falha.
- Um índice único parcial garante uma só execução ativa por projeto.
- `model_evaluations` guarda uma avaliação por execução e divisão
  (`validation` ou `test`), com a métrica, o valor, as demais métricas, a
  procedência do modelo-alvo e o retrato usado.
- O lote de aquisição aponta para a execução que o escolheu pela coluna
  `model_run_id`, que já existia e ganha chave estrangeira.
- A "iteração" das rotas é derivada da execução e do lote, sem tabela própria.
  O identificador da iteração é o da primeira tentativa.

**Motivo:** segue a D2 da Fase 6 (o estado do job fica na própria tabela de
execuções) e a D4 da Fase 4 (a procedência fica no lote).

**Rejeitada:** tabelas `iterations` e `iteration_selections`. Repetiriam o que
a execução e o lote já guardam.

#### D3: Formato do manifesto

**Escolha:**

- Um único formato, o COCO estendido da especificação DADA (`dada-coco-pai/1`),
  para treino, validação, teste, imagens elegíveis e o resultado da seleção.
- Cada imagem traz o id da mídia, o caminho do arquivo relativo à raiz de
  mídia (a cópia WebP quando a origem é HEIC/HEIF), largura e altura
  canônicas, o caminho relativo original, o sha256 da origem, a versão da
  cópia, o estado de anotação e as regiões consultadas.
- As anotações vêm só de resoluções aceitas e vigentes, com o id e a versão da
  resolução. As categorias usam o `display_order` como índice.
- Cada retrato é um arquivo JSON imutável gravado em
  `<projeto>/learning/snapshots/<sha256>.json` na raiz de mídia, identificado
  pelo sha256 do próprio conteúdo. A execução guarda só as impressões
  digitais. O arquivo sai junto com o projeto.

**Motivo:** a especificação já define esse formato e pede que o resultado use o
formato da entrada. Um arquivo em disco escala melhor que JSONB com 100 mil
imagens.

#### D4: Como o ciclo anda sozinho

**Escolha:**

- Quando um lote `initial_training`, `validation`, `test` ou `acquisition`
  passa a `resolved`, a mesma transação grava o evento
  `learning.batch_resolved.v1` na outbox.
- O relay existente (`dada-api consensus-relay`) também consome esses eventos.
  Para cada um, decide se a próxima iteração deve nascer: o projeto é `split`
  e está ativo, as imagens iniciais estão resolvidas, o último lote de
  aquisição está resolvido e não há execução ativa nem pendente.
- O sorteio aleatório roda no próprio relay e já cria o lote. A seleção por
  aprendizado ativo vira uma execução na fila Celery `learning`.
- `POST /iterations/{id}/close` refaz essa mesma verificação, para o caso de um
  evento perdido.

**Motivo:** reaproveita a outbox e o relay da Fase 6.

#### D5: Início do lote de aquisição

**Escolha:** o lote nasce em `preparing`, com a cópia da política vigente, e o
gerente o inicia pela rota de sempre.

**Motivo:** mantém a janela de edição da política que o plano exige, sem lógica
nova.

#### D6: Estados da iteração

**Escolha:** iteração n = execução n + lote n.

| Estado | Quando |
| --- | --- |
| `training` | A execução está na fila ou rodando. A etapa (`training`, `evaluating`, `selecting`) vem do worker |
| `preparing` | O lote existe e ainda não começou |
| `annotating` | O lote está coletando anotações |
| `consolidating` | O lote está em `resolving` ou `review_required` |
| `ready` | O lote está resolvido, ou a avaliação final terminou |
| `failed` | A última tentativa falhou |

Não há previsão de tempo (`eta_seconds` é sempre nulo) nesta fase.

**Motivo:** pela P7-01, a mesma execução treina e escolhe, então é ela que
abre a iteração. O estado `closing` do contrato antigo não tem o que
representar e sai; a rota `close` continua.

#### D7: Falha e tempo-limite

**Escolha:**

- Sem novas tentativas automáticas.
- Uma execução que passa do tempo-limite (`DADA_LEARNING_TIMEOUT_SECONDS`,
  padrão de 24 h) vira `failed` com `worker_failed`, pelo relay.
- O gerente usa `POST /iterations/{id}/retry`, que cria a próxima tentativa
  sobre os mesmos retratos, a mesma configuração e a mesma semente.
- Um resultado repetido, atrasado ou de tentativa antiga não muda nada.

**Motivo:** a A7-01 só pede a nova tentativa manual, e repetir um treino longo
de forma automática custa caro.

#### D8: Parada e fim

**Escolha:**

- Dentro da execução, a avaliação vem antes da seleção. Se a meta da métrica
  foi atingida, a solução avalia no teste e devolve `stop_reason:
  metric_target`, sem seleção.
- Quando o máximo de iterações é alcançado ou acabam as imagens elegíveis, o
  aprendizado ativo ainda faz uma execução `final_evaluation` (validação e
  teste). A aquisição aleatória termina direto.
- Ao terminar, o projeto fica `completed`, com `completion_reason` igual a
  `max_iterations`, `metric_target` ou `pool_exhausted`.
- A aquisição aleatória não avalia, porque não há modelo.
- A validação de um projeto `split` nunca é vazia (a Fase 4.1 garante ao menos
  uma imagem). Se, na hora de avaliar, nenhuma imagem de validação tiver
  resolução aceita, a execução falha com `validation_unavailable` antes de ir
  ao worker.

#### D9: Métricas

| Tarefa | Métricas | Média |
| --- | --- | --- |
| Classificação | `accuracy` ou `f1` | F1 macro entre as classes |
| Detecção | `map50` | média das classes presentes na validação |
| Segmentação | `mean_iou` | IoU de máscara por classe, somado nas imagens; classe ausente na referência e na predição fica fora da média |

Todas ficam entre 0 e 1, e maior é melhor. `metric_target` fica em (0, 1].

#### D10: Classificação multirrótulo e a DADA

**Escolha:** o treino e a avaliação da classificação na DADA usam só imagens
com exatamente uma classe aceita. As demais continuam no conjunto e na
exportação, e a quantidade excluída fica na procedência da execução.

**Motivo:** a Fase 6 manteve a classificação multirrótulo (D10) e a
especificação DADA usa uma classe por imagem. **Ponto para o Meirelles
confirmar.**

#### D11: Solução determinística para desenvolvimento

**Escolha:** um adaptador determinístico (`deterministic`) entra no catálogo só
com `DADA_ENVIRONMENT` igual a `development` ou `test`, marcado como de
desenvolvimento. Ele escolhe pela ordem de um hash da semente com o id da mídia
e calcula uma métrica sintética e crescente.

**Motivo:** sem GPU, é o único jeito de ver o ciclo inteiro. O `testing.md` e o
critério da Fase 9 já preveem um worker determinístico.

#### D12: Catálogo de soluções

**Escolha:** `GET /capabilities` ganha `active_learning_solutions` (id, versão,
nome, descrição, tarefas, se é de desenvolvimento, motivo de
indisponibilidade e descritores de configuração no formato dos resolvers) e
`evaluation_metrics` por tarefa.

**Motivo:** mesmo padrão dos pipelines de consenso. O App reaproveita o
formulário guiado por descritores.

#### D13: Onde mora o código

**Escolha:**

- `dada_api/active_learning/` guarda o contrato (`BaseModelAdapter`,
  `BatchRequest`, `BatchResult`), o catálogo e o adaptador determinístico.
- A DADA fica em `dada_api/active_learning/dada_al/`, com a estrutura da
  especificação, sem importar nada da API.
- As dependências ficam no extra `learning`, que ganha `timm` e
  `scikit-learn`. Testes que exigem torch ou GPU são pulados quando o extra não
  está instalado.

**Motivo:** mesmo padrão do pacote `consensus`.

#### D14: Etapas informadas pelo worker

**Escolha:** `select_batch` recebe, além do pedido, uma função opcional
`report_stage(stage)`, que o worker usa para gravar a etapa da execução
(`training`, `evaluating` ou `selecting`).

**Motivo:** a A7-01 mostra essas etapas, e o contrato geral só define a
operação de seleção. A função é opcional e não muda o pedido nem o resultado.

#### D15: Limpeza dos artefatos

**Escolha:** cada tentativa recebe uma pasta de artefatos em
`<projeto>/learning/runs/iteration-<n>/attempt-<a>`, e cada solução uma pasta de
estado em `<projeto>/learning/state/<solução>`. Depois de uma execução bem
sucedida, o worker apaga as pastas de artefatos de todas as tentativas daquela
iteração, a menos que `retain_helper_models` esteja ligado. Numa falha, elas
ficam para a nova tentativa.

### Alvos por objeto (bloco 2)

#### D16: Representação do alvo

**Escolha:**

- Um item de lote por alvo, com a geometria proposta e a área de contexto (15%
  de margem, da especificação DADA) gravadas no item. A unicidade (lote,
  imagem) passa a incluir o alvo.
- O documento do alvo tem no máximo um objeto. Vazio quer dizer "não há
  objeto" e vira um negativo confirmado (`EXPLICIT_HARD_NEGATIVE`).
- Imagens anotadas só em parte continuam elegíveis para novos alvos.

#### D17: Consenso do alvo

**Escolha:** sem etapa de casamento, porque todas as respostas já são do mesmo
alvo. Vota classe e existência (com `no_object`) e depois refina a geometria.
Revisão e especialista funcionam como na Fase 6.

### Segmentação assistida (bloco 2)

#### D18: Pedido e modelo

**Escolha:**

- O modelo-alvo roda na imagem. Com uma caixa, devolve a instância de maior
  IoU com ela; com um ponto, a de maior confiança que contém o ponto. Sem
  instância, devolve `no_suggestion`.
- Executa numa fila Celery própria, com espera de até 30 s. A sugestão nunca é
  gravada.
- O projeto guarda só o último modelo-alvo, trocado a cada avaliação e apagado
  com o projeto.
- A rota mantém o caminho documentado, `/inference/sam-predict`, e passa a
  exigir `project_id` e `assignment_id`.

### Saídas e acesso (bloco 3)

#### D19: Exportação

**Escolha:** um ZIP gerado na hora e enviado aos poucos, separado por divisão.
COCO ou YOLO na detecção e na segmentação, à escolha; CSV (caminho e classes) na
classificação. Sempre traz um `provenance.json` com as versões das resoluções,
a origem, a cópia de exibição, o estado de anotação e as regiões consultadas.
As imagens são as cópias de exibição.

#### D20: Fórmulas da qualidade

| Medida | Fórmula |
| --- | --- |
| Taxa de revisão | imagens resolvidas que passaram por revisão ou especialista ÷ imagens resolvidas |
| Taxa de resolução | imagens resolvidas ÷ imagens não canceladas |
| Concordância | mediana da métrica da primeira rodada (suporte do vencedor, IoU mediano por par, Dice ou IoU de máscara) |

Rota `GET /projects/{id}/quality`, com a supressão da P7-05.

#### D21: Autorização

**Escolha:** uma ação nova, `manage_learning` (dono e gerente), para nova
tentativa e exportação. A matriz vai para 15 ações. Iterações e estatísticas
usam `read_project`; qualidade usa `read_annotator_performance`; assistência
usa `annotate` e a tarefa da própria pessoa.

#### D22: Sementes de modelo

**Escolha:** ficam fora da Fase 7. O destaque do alvo já cumpre esse papel.

**Motivo:** a P6-06 as trata como opcionais e o plano não as lista na Fase 7.

## Implementação

### Bloco 1: ciclo de aquisição na API

Status: implementado em 2026-11-23, na branch `phase_7`, sem commit. Continua
sujeito à revisão do Meirelles.

Guia de operação: [development.md](../development.md#acquisition-loop-phase-7).

#### Persistência

Migração `20261123_0011`, exercitada upgrade → downgrade → upgrade, com
`alembic check` limpo.

- **Projeto:** `max_acquisition_iterations`, `learning_solution`,
  `learning_solution_version`, `learning_configuration`,
  `evaluation_metric`, `evaluation_interval`, `metric_target` e
  `completion_reason` (D1, D8).
- **Tabelas novas:** `learning_runs` (com o índice único parcial de uma
  execução ativa por projeto) e `model_evaluations` (D2).
- **Lote:** `model_run_id` ganhou chave estrangeira para `learning_runs`.

#### Código

| Onde | O quê |
| --- | --- |
| `dada_api/active_learning/contract.py` | `BaseModelAdapter`, `BatchRequest`, `BatchResult`, `EvaluationPlan` e a leitura verificada de manifestos (D3, D14) |
| `dada_api/active_learning/catalog.py` | Registro, disponibilidade, validação de configuração e descritores (D12) |
| `dada_api/active_learning/deterministic.py` | Solução determinística de desenvolvimento (D11) |
| `services/learning_settings.py` | Padrões e validação das configurações do projeto (D1) |
| `services/learning_snapshots.py` | Manifestos `dada-coco-pai/1` só com resoluções aceitas (D3) |
| `services/learning_runs.py` | Abertura de iterações, relay, tentativas, ingestão, nova tentativa, fechamento e as visões de iteração (D4 a D8, D15) |
| `services/renditions.py` | Decodificação canônica e cópia WebP sem perda (P7-06) |
| `workers/learning.py` | Tarefa Celery `learning.select` na fila `learning` |
| `api/v1/endpoints/iterations.py` | Rotas de iteração e estatísticas |

#### Rotas e comandos

| Rota ou comando | Função |
| --- | --- |
| `GET /projects/{id}/iterations` | Iterações, da mais antiga à mais recente, e a atual |
| `GET /projects/{id}/iterations/{iteration_id}` | Uma iteração, com contagens, estado, etapa e métricas |
| `POST /projects/{id}/iterations/{iteration_id}/close` | Verificação idempotente; `409 iteration_incomplete` enquanto houver imagens |
| `POST /projects/{id}/iterations/{iteration_id}/retry` | Nova tentativa sobre os mesmos retratos (`manage_learning`) |
| `GET /projects/{id}/statistics` | Progresso e avaliações do modelo-alvo |
| `dada-api consensus-relay` | Passa a abrir iterações, vencer execuções e despachá-las |
| `make worker-learning` | Worker da fila `learning` |

`/capabilities` ganhou `active_learning_solutions` e `evaluation_metrics`, e
os tipos `image/heic` e `image/heif`. O `openapi.json` foi de 60 para 65
caminhos e de 101 para 106 schemas. A matriz de autorização foi para 15 ações
e 60 pares com `manage_learning`.

#### Leituras feitas na implementação

- **Avaliação devida.** A avaliação entra quando o número de aquisições
  concluídas é múltiplo de K e maior que zero, e sempre na execução final.
  Com K = 1, a primeira avaliação acontece na execução que segue a primeira
  aquisição.
- **Seleção vazia.** Uma solução que devolve zero imagens de um conjunto não
  vazio tem o resultado aceito, e o ciclo segue como se as imagens tivessem
  acabado: avaliação final e `pool_exhausted`.
- **Alvos ainda não aceitos.** No bloco 1, um resultado com anotações na
  seleção é recusado como `solution_output_invalid`; os alvos por objeto
  entram no bloco 2.
- **Validação de formato da imagem.** A troca de formato só é verificada
  quando a origem declarada ou a real é HEIF; JPEG, PNG e WebP seguem como
  antes.

#### Verificação

Executado contra PostgreSQL 16 e Redis 7 locais.

- `ruff check` e `ruff format --check`: limpos. `alembic check`: sem
  divergência.
- Testes da API: **648 passaram** com integração habilitada, contra 621 no
  início do bloco.
- `openapi.json` regenerado.

| Critério de saída da Fase 7 | Como foi provado |
| --- | --- |
| Anotação não resolvida não entra em manifesto | `test_active_learning_runs_through_the_worker_to_its_final_evaluation` e `test_a_manifest_carries_accepted_geometry_in_the_shared_format` |
| Sucesso, nova tentativa, duplicado, atrasado, tempo esgotado e falha | `test_active_learning_runs_through_the_worker_to_its_final_evaluation`, `test_failures_are_recorded_and_a_retry_reuses_the_snapshots`, `test_duplicate_late_and_timed_out_results_change_nothing`, `test_a_result_that_does_not_fit_its_request_fails_the_run` |
| HEIC/HEIF: digest da origem, WebP sem perda com mesmo tamanho e pixels iguais | `test_heif_sources_keep_their_digest_and_gain_an_exact_rendition`, `test_orientation_is_applied_once`, `test_spoofed_and_broken_heif_uploads_fail_without_media`, `test_a_conversion_failure_fails_the_upload`, `test_duplicate_heif_content_reuses_its_rendition` |

#### Pendências do bloco

| Item | Situação |
| --- | --- |
| `uv.lock` | A dependência `pillow-heif` foi acrescentada ao `pyproject.toml`. O lock precisa ser regenerado com `uv lock` numa máquina que alcance `download.pytorch.org` |
| `.env` local | Acrescentar `image/heic` e `image/heif` a `DADA_SUPPORTED_IMAGE_MEDIA_TYPES` |
| App | O assistente ainda não envia `max_acquisition_iterations`, que passou a ser obrigatório em projetos `split`; entra no bloco 3 |

### Bloco 2: DADA, alvos por objeto e segmentação assistida

Status: implementado em 2026-11-24, na branch `phase_7`, sem commit. Continua
sujeito à revisão do Meirelles.

Guia de operação: [development.md](../development.md#object-targets) e
[assistência](../development.md#assisted-annotation-phase-7).

#### Persistência

Migração `20261124_0012`, exercitada upgrade → downgrade → upgrade, com
`alembic check` limpo.

- **Item do lote:** `target_key`, `target_geometry` e `target_region` (D16).
- **Unicidade:** `uq_batch_item` passa a ser (lote, imagem, alvo) com
  `NULLS NOT DISTINCT`, então o item de imagem inteira continua único por
  imagem.

#### Código

| Onde | O quê |
| --- | --- |
| `services/learning_runs.py` | Validação dos alvos da seleção e pasta do modelo retido (D16, D18) |
| `services/learning_snapshots.py` | `PARTIALLY_LABELED`, `queried_rois` e anotações `AL_OBJECT_QUERY` nos manifestos (D16) |
| `services/batches.py`, `services/datasets.py` | Um item por alvo; imagem com alvos respondidos continua elegível (D16) |
| `services/assignments.py`, `services/annotation_documents.py` | Documento do alvo com no máximo um objeto (D16) |
| `consensus/candidates.py`, `consensus/protocol.py` | Consenso do alvo sem casamento (D17) |
| `services/assistance.py`, `workers/assistance.py`, `api/v1/endpoints/inference.py` | Segmentação assistida (D18) |
| `active_learning/contract.py`, `active_learning/catalog.py` | Pasta de assistência no pedido, interface de assistência e registro da DADA |
| `active_learning/deterministic.py` | Alvos e assistência também na solução de desenvolvimento |
| `active_learning/dada_al/` | Solução DADA com a estrutura da especificação |

#### Rotas e comandos

| Rota ou comando | Função |
| --- | --- |
| `POST /inference/sam-predict` | Sugestão para um ponto ou caixa na tarefa aberta da própria pessoa |
| `make worker-assistance` | Worker da fila `assistance` |

As tarefas (`/assignments`), o detalhe da tarefa e as evidências do gerente
ganharam o campo `target`. `/capabilities` lista a DADA, com
`dependency_missing` onde o extra `learning` não está instalado, e os
descritores ganharam o tipo `string`. O `openapi.json` ficou com 65 caminhos
e foi de 106 para 107 schemas.

#### Leituras feitas na implementação

| Ponto | Leitura |
| --- | --- |
| Formato do alvo na seleção | Cada anotação da seleção é um alvo, com `image_id`, `roi_id` e a geometria (`bbox`, ou `segmentation` na segmentação); a região é o `bbox_xyxy` da entrada de mesmo `roi_id` em `queried_rois` da imagem |
| Validação na API | Imagem elegível, geometria válida da tarefa, região dentro da imagem e contendo a geometria, nada repetido e no máximo o tamanho pedido. Classificação não pode devolver alvos; detecção e segmentação só devolvem alvos |
| Identidade do alvo | `target_key` vem do hash da geometria; a região fica como `[x, y, largura, altura]` |
| Semente importada | Não vale para alvo, porque descreve a imagem inteira |
| Elegibilidade | Item de alvo resolvido não segura a imagem; item em lote ainda aberto segura |
| Estado da imagem no manifesto | `EXHAUSTIVELY_LABELED` quando há resolução de imagem inteira; `PARTIALLY_LABELED` quando só há alvos respondidos; `al_iteration` é a iteração da execução que escolheu o alvo |
| Consenso do alvo | A entrada do resolvedor recebe só a região do alvo (`target_region`); a geometria proposta nunca entra, então não há como virar voto |
| Solução determinística | Propõe um alvo no centro de cada imagem nunca consultada; a métrica sintética conta imagens distintas; deixa um modelo descritivo para a assistência |
| Assistência | Um único prompt por pedido; resultado no Redis só para essa tarefa, por até 5 minutos; geometria conferida antes de responder; `409 assistance_unavailable` (`no_target_model`, `incompatible_target_model` ou `solution_unavailable`), `422 invalid_prompt` ou `assistance_not_supported`, `503 assistance_timeout` ou `assistance_failed` |
| Configuração da DADA | `DADASettings` é o que o projeto guarda; `DADAAlConfig` acrescenta a tarefa e o orçamento do pedido. A tarefa chega como contexto da validação, que preenche os padrões e recusa método, modelo ou pesos incompatíveis |
| Campos acrescentados | `proxy_epochs` (10), `target_epochs` (50), `batch_size` (16) e `image_size` (640 no YOLO, a do alvo no timm), porque a especificação cita épocas e tamanho sem defini-los |
| Divergências da especificação | `acquisition_budget_q` aceita zero, para a avaliação final; o `CandidateItem` guarda anéis de polígono (`segmentation`) no lugar de `mask_rle`, porque o manifesto troca polígonos; não há `config.yml`, porque a configuração já é persistida pela API em cada projeto e execução |
| Ordem dentro da execução | Treina e avalia o alvo, decide a parada, depois treina o proxy e seleciona (D8); as etapas informadas são `training`, `evaluating`, `training` e `selecting` |
| Modo 1 | Imagens só com letterbox, sem aumento geométrico, para as regiões caírem exatamente na imagem de treino; âncora positiva e âncora de imagem exaustiva têm peso 1 |
| Modo 2 | O professor é o último modelo-alvo retido; pseudorrótulos com confiança de 0,80 ou mais e centro fora das regiões; na segmentação, o pseudorrótulo é o contorno |
| Ensemble | Sementes 1 a N, como na especificação, treinadas lado a lado e uma a uma quando falta memória; o TTA multivista treina um proxy |
| Pré-NMS | Sobreviventes por NMS (IoU 0,7) sobre o ramo um-para-muitos e os 300 melhores do um-para-um; objeto sem proposta no grupo usa a si mesmo (K = 1); casamento do um-para-um com IoU de 0,30 |
| TTA | Os objetos são os da passada original; o termo de máscara é só a entropia da borda, a única medida que a especificação define para esse método |
| Polígonos | Contorno simplificado em 1 pixel e conferido com a mesma regra de simplicidade da API, com o fecho convexo como reserva; coordenadas numa grade de 1/64 de pixel, para `x + largura` fechar exatamente |
| Métricas | `map50` da validação do Ultralytics; `mean_iou` como na D9, valendo 1 quando nenhuma classe aparece; acurácia e F1 macro nas classes presentes na referência ou na predição; só imagens de uma classe (D10), com a quantidade excluída na procedência |
| Modelo retido | Detecção e segmentação trocam o modelo da assistência a cada avaliação; classificação não tem assistência |
| JPEG com orientação EXIF | Exposto ao treino como PNG sem girar, porque a anotação está no plano de pixels guardado |
| Pesos pré-treinados | Baixados para `learning/state/dada/weights/` (YOLO, do GitHub) e pelo Hugging Face (timm) |

#### Verificação

Executado contra PostgreSQL 16 e Redis 7 locais.

- `ruff check` e `ruff format --check`: limpos. `alembic check`: sem
  divergência.
- Testes da API: **677 passaram** com integração habilitada, contra 648 no
  início do bloco; `tests/test_dada_models.py` fica pulado sem o extra
  `learning`.
- Num ambiente à parte com torch 2.15 (CPU), ultralytics 8.4.218, timm 1.0.31 e
  scikit-learn 1.9.1: `tests/test_dada_models.py` passou (8 testes), e a DADA
  rodou de ponta a ponta em dados sintéticos para detecção e segmentação
  (pré-NMS e TTA, modos 1 e 2) e classificação (ensemble e multivista), com
  as seleções aceitas pela validação da API.
- `openapi.json` regenerado.

| Critério do bloco | Como foi provado |
| --- | --- |
| Limites da incerteza | `test_classification_uncertainty_is_bounded_and_positive_on_a_boundary`, `test_object_uncertainties_stay_bounded_in_every_edge_case`, `test_a_lone_proposal_falls_back_to_its_own_measures`, `test_a_one_to_one_miss_counts_as_disagreement`, `test_pre_nms_candidates_are_bounded_and_embedded` |
| Conservação das cotas e casos da P7-09 | `test_quotas_conserve_the_budget_and_respect_capacity`, `test_selection_fills_each_cluster_with_its_most_uncertain_candidates`, `test_ties_and_zero_uncertainty_are_resolved_by_identifier`, `test_too_few_or_no_candidates_are_reported`, `test_clustering_is_reproducible_and_capped_by_the_candidates` |
| Deduplicação | `test_the_gatekeeper_drops_known_objects_and_caps_candidates` |
| Gradiente zero fora das regiões (modo 1) e neutralização (modo 2) | `test_mode_1_gives_unqueried_background_an_exact_zero_gradient` (YOLO26 nas duas cabeças, YOLO11 e YOLO12), `test_mode_2_neutralizes_unqueried_pixels_and_adds_confident_labels` |
| Alvos por objeto | `test_object_targets_are_answered_one_object_at_a_time`, `test_a_target_that_does_not_fit_fails_the_run`, `test_classification_acquires_whole_images` |
| O alvo nunca conta como voto | `test_an_object_target_is_one_candidate_without_matching`, `test_an_empty_answer_to_a_target_votes_that_there_is_no_object`, `test_a_target_nobody_found_resolves_to_an_empty_document` |
| A assistência recusa tarefa alheia e não mexe no rascunho | `test_assistance_answers_the_owner_and_never_touches_the_draft` |

O teste de velocidade em GPU da especificação (critério 2) fica para quando a
máquina estiver disponível.

#### Pendências do bloco

| Item | Situação |
| --- | --- |
| `uv.lock` | O extra `learning` ganhou `timm` e `scikit-learn`, e o `ultralytics` passou a exigir 8.4 (YOLO26). O lock precisa ser regenerado com `uv lock` |
| Ambiente da DADA | A API e os dois workers precisam do extra `learning` para a DADA aparecer como disponível |
| App | O campo `target`, o novo contrato da `sam-predict` (o App ainda manda `image_id` e espera `polygons`) e o tipo `string` dos descritores entram no bloco 3 |
| GPU | Verificação com GPU e modelos reais quando a máquina estiver disponível |

### Bloco 3: saídas, App e fechamento

Status: implementado em 2026-11-24, na branch `phase_7`, sem commit. A
verificação no navegador fica para quando a máquina estiver disponível. Continua
sujeito à revisão do Meirelles.

Guia de operação: [exportação](../development.md#dataset-export-phase-7) e
[qualidade](../development.md#quality-statistics-phase-7). Contrato do App:
[Phase 7 implemented shapes](../../../dada-app/docs/api-contract.md#phase-7-implemented-shapes).

#### Persistência

Nenhuma migração. A exportação e a qualidade leem o que já existe.

#### Código da API

| Onde | O quê |
| --- | --- |
| `services/exports.py` | ZIP escrito enquanto é enviado, por divisão, em COCO, YOLO ou CSV, com `provenance.json` (D19) |
| `services/quality.py`, `schemas/quality.py` | Fórmulas e supressão da qualidade (D20, P7-05) |
| `api/v1/endpoints/outputs.py` | Rotas de exportação e qualidade |
| `services/learning_snapshots.py` | A consulta das resoluções aceitas e a descrição de cada imagem passam a ser públicas, para a exportação usar as mesmas dos manifestos |

#### Rotas

| Rota | Função |
| --- | --- |
| `GET /projects/{id}/export?format=coco\|yolo\|csv` | Conjunto anotado em ZIP (`manage_learning`) |
| `GET /projects/{id}/quality` | Taxa de revisão, taxa de resolução e concordância (`read_annotator_performance`) |

O `openapi.json` foi de 65 para 67 caminhos e de 107 para 109 schemas. A matriz
de autorização não mudou (15 ações).

#### App

| Superfície | Onde (`dada-app/src/`) |
| --- | --- |
| Contrato da fase: capabilities, projeto, iterações, estatísticas, qualidade, alvo e assistência | `api/capabilities.ts`, `features/projects/types.ts`, `features/annotation/types.ts`, `features/annotation/annotation-api.ts` |
| Máximo de iterações e configuração do aprendizado ativo na criação e nas configurações: solução, descritores (com o tipo `string`), métrica, K e meta | `features/projects/NewProjectPage.tsx`, `ProjectSettingsPage.tsx`, `LearningSettingsForm.tsx`, `learning-settings.ts`, `ResolverConfigForm.tsx`, `resolver-config.ts`, `project-api.ts` |
| HEIC/HEIF: um registro de formatos filtrado pelo `/capabilities`, nos dois campos de arquivo da criação e da retomada, com o texto de ajuda (P7-06) | `features/projects/ingest.ts`, `NewProjectPage.tsx`, `DraftProjectSetupPage.tsx` |
| Cartão de atividade, avaliações do modelo-alvo, iterações e nova tentativa (A7-01) | `features/annotation/ProjectActivityPage.tsx`, `activity.css` |
| Qualidade e exportação, só para dono e gerente (A7-02, D19) | `features/annotation/ProjectActivityPage.tsx` |
| Alvo destacado com a região, um objeto por alvo e entrega "sem objeto" (D16) | `features/annotation/AnnotationWorkspacePage.tsx`, `ImageStage.tsx` |
| Assist segmentation com prévia, aceitar e descartar, e o novo contrato da `sam-predict` (A7-03, D18) | `features/annotation/AnnotationWorkspacePage.tsx`, `ImageStage.tsx`, `assignment-view.ts` |
| I7-04 | `features/annotation/ImageStage.tsx`, `viewport.ts`, `annotation.css` |
| I7-05 | `api/client.ts`, `features/auth/AuthProvider.tsx`, `LoginPage.tsx` |
| Atividade visível nos projetos `split` ativos | `features/projects/ProjectsPage.tsx` |

#### Leituras feitas na implementação

| Ponto | Leitura |
| --- | --- |
| Divisões da exportação | `train` (treino inicial e aquisições), `val` e `test`; `all` num projeto `single_batch` |
| Nome das imagens | O caminho relativo do envio; uma origem HEIC/HEIF vira `<caminho>.webp`, porque a imagem exportada é a cópia de exibição |
| Índice de classe | O `display_order`, no COCO e no YOLO, como na importação de rótulos; no COCO, cada anotação também traz `resolution_id` e `resolution_version` |
| YOLO de segmentação | Uma linha por objeto, com o maior anel, como no treino da DADA; o COCO mantém todos os anéis |
| CSV da classificação | Uma coluna 0/1 por classe, porque a classificação é multirrótulo (D10 da Fase 6) |
| Formato padrão | `coco` na detecção e na segmentação, `csv` na classificação; um formato fora da tarefa é `422 export_format_not_supported` |
| Item da qualidade | Um alvo conta como um item; as "imagens" da D20 são os itens de lote |
| Decisões elegíveis (P7-05) | Os itens resolvidos: abaixo de 30, nenhum valor aparece; uma mediana com menos de 5 candidatos fica oculta |
| Passou por revisão | O item tem item de trabalho na geração de evidência vigente, seja de revisores, seja de especialista |
| Primeira rodada | A execução mais recente sobre a entrada de número 1 da geração vigente. Métricas: `winner_support` na classificação, `box_iou` na detecção e `mask_iou` ou `mask_dice` na segmentação, conforme a métrica de casamento do lote |
| Seções de gerente no App | Qualidade, exportação e nova tentativa aparecem só para dono, gerente e administrador; a API continua decidindo |
| Assistência num alvo | O botão pergunta direto, com a caixa da geometria proposta; sem alvo, o anotador clica um ponto ou arrasta uma caixa |
| Editar a sugestão | O canvas não edita vértices. Aceitar põe a sugestão no rascunho, já selecionada, e ela se edita como qualquer anotação (classe, apagar, desfazer) |
| Assistência por tarefa | O botão aparece na detecção e na segmentação, as duas tarefas que a API atende |
| I7-04 | A imagem abre centrada e na largura total do canvas, como pede a issue; "Fit image" mostra a imagem inteira |

#### Verificação

Executado contra PostgreSQL 16 e Redis 7 locais.

- API: `ruff check` e `ruff format --check` limpos; `alembic check` sem
  divergência. Testes: **683 passaram** com integração habilitada, contra
  677 no início do bloco. `openapi.json` regenerado.
- App: `npm run check` verde: lint, **230 testes** em 43 arquivos (eram 200 em
  37) e o build de produção.
- **Não verificado:** o navegador e a GPU.

| Critério do bloco | Como foi provado |
| --- | --- |
| A exportação só contém resoluções aceitas | `test_an_export_holds_only_accepted_resolutions`, `test_a_classification_export_is_a_table_of_classes`, e o `provenance.json` parcial em `test_object_targets_are_answered_one_object_at_a_time` |
| A qualidade respeita a supressão | `tests/test_quality.py`, a rota em `test_detection_resolves_with_box_agreement_observations`, a revisão em `test_low_agreement_reaches_a_reviewer_then_a_second_round` e o acesso em `test_only_owners_and_managers_reach_the_resolution_routes` |
| `npm run check` passa | 230 testes, lint e build |
| I7-04 e I7-05 registradas como resolvidas | `dada-app/docs/issues_before_phase7.md`; `ImageStage.test.tsx`, `viewport.test.ts`, `client.test.ts` e `session-expiry.test.tsx` |

| Critério de saída do App na Fase 7 | Testes | Navegador |
| --- | --- | --- |
| Submissões não resolvidas nunca aparecem como dado de treino | A tela mostra só as contagens e avaliações da API; a exportação só traz resoluções aceitas | Pendente |
| A assistência fica restrita à tarefa aberta | `AnnotationWorkspacePage.test.tsx` (prévia, aceite, falha sem mudar o rascunho, um objeto por alvo) e `test_assistance_answers_the_owner_and_never_touches_the_draft` | Pendente |
| Uma amostra HEIC/HEIF passa por seleção, envio, anotação, recarga e revisão sem mudar dimensões nem geometria | `ingest.test.ts` e `NewProjectPage.test.tsx` (seleção); os testes HEIF da API do bloco 1 | Pendente |

#### Pendências do bloco

| Item | Situação |
| --- | --- |
| Navegador | Percorrer no Chrome e no Firefox: criação com aprendizado ativo, cartão de atividade com nova tentativa, qualidade, exportação, alvo com assistência, HEIC/HEIF de ponta a ponta e as issues I7-04 e I7-05 |
| GPU | Verificação com GPU e modelos reais, como nos blocos 1 e 2 |

