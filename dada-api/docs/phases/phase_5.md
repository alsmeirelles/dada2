# Decisions for Phase 5 implementation

## API decisions
Phase 5 has the pending decisions below. Remarks are made for some of them and any other decisions during implementation
should be registered.

| ID | Pending decision | Required documented outcome |
| --- | --- | --- |
| `P5-01` | Acquisition-strategy project contract | Field name and enum, default for new projects, mutability before/after activation, version/audit behavior, development-reset treatment, and OpenAPI examples |
| `P5-02` | Random acquisition semantics | Sampling algorithm/order, seed lifecycle, fingerprint, and provenance. The eligible pool, completed/cancelled/incomplete-item handling, final undersized-batch rule, and `iteration_batch_size` requested-size rule are fixed by the [Phase 4.1 revision plan](phase-4-annotation-sequence-revision-plan.md). |
| `P5-03` | Image-assignment access | Direct assigned-image access without annotation leases or claims; queue ordering; disconnect and recovery behavior; manager reassignment; and concurrent visibility of the same image to the configured consensus group |
| `P5-04` | Assignment reassignment and submission lifecycle | Reassignment authority and audit before submission; immutable full-image submission revisions; whether submitted work may reopen; duplicate-completion response; and return of cancelled/incomplete images to the eligible train pool |
| `P5-05` | Full-image annotation document contract | Versioned classification/detection/segmentation image-document schemas; explicit single-label vs. multi-label configuration; object entries within detection/segmentation documents; coordinate precision; empty-annotation semantics; geometry limits; validation errors; and payload/complexity limits |
| `P5-06` | Blindness release boundary | Exactly what aggregate state an annotator may read before submission, after own submission, after item resolution, and after batch closure; event redaction rules |

### P5-01

Default acquisition strategy is RANDOM selection from unlabeled pool. The acquisition strategy may be changed to active learning
after activation for prepared split projects. A static `single_batch` project
cannot use or switch to active learning, has no later acquisition iterations,
and may still use consensus annotation.

## P5-03

Automatically save annotated objects at fixed 10 minute intervals. Recover from the last saved configuration (automatically saved or user manually
save the image work).

During optional consensus, the same image may have objects assigned to different annotators. New objects are not created at this stage.

Manager reassignment while still at an annotator's responsibility is not supported

## P5-04

Manager reassignment or reopen before and after submission is possible. Managers may reopen for the same annotator or reassign a submission for correction before it goes
into consensus resolution. Annotators may not cancel or reject assignments for themselves. Managers may cancel the assignment but should be warned that cancelling will
return the images to the unlabeled training pool.

## P5-05

Empty annotations are possible for detection and segmentation projects and annotators may explicitly mark an image as empty.
Multi-label for detection and segmentation should be supported.
Reject unknown classes and malformed or self-intersecting geometry.

Before assignment distribution, an owner or manager may import YOLO detection
or COCO segmentation labels. Match source class indexes to the prepared project
class `display_order`; retain file, mapping, actor, and validation provenance.
An accepted import creates editable seed documents only. When an annotator saves
or submits seeded work, it becomes that annotator's draft/submission with an
immutable link to the import; the import is never a submission, consensus vote,
or accepted resolution.

## P5-06

Before submission, show only the annotator’s assignment and project instructions.
Do not reveal peer annotations, agreement, submission counts, consensus status, or identity.
After their own submission, show that their work was received, but keep peer evidence hidden while collection continues.
After resolution, allow managers and authorized reviewers to inspect evidence.

## APP decisions

| ID | Pending App decision | Required documented outcome |
| --- | --- | --- |
| `A5-01` | Acquisition-strategy setup UX | Control placement and wording, default shown to users, validation, review summary, draft recovery, settings visibility, and treatment when the API says the setting is locked |
| `A5-02` | Random-acquisition presentation | Explanation of unlabeled-pool eligibility and reproducibility, manager visibility of seed/strategy provenance, empty/exhausted-pool messaging, and removal of model-guided language |
| `A5-03` | Image-assignment queue UX | Direct assigned-image queue ordering/filtering, navigation, offline and stale-version recovery, manager reassignment messaging, accessibility behavior, and no annotation-lease controls |
| `A5-04` | Submission and recovery UX | Reopen rules, success terminology, stale-draft reconciliation choices, recovery expiry/display, empty-annotation confirmation, and visibility after own submission |

### A5-01

Place the acquisition-strategy choice in project setup beside the learning
settings. Offer **Random acquisition** and **Active learning**, with Random
selected by default. Explain that the choice controls future training
acquisition batches only; it does not alter the fixed train, validation, and
test splits or the initial annotation batches. For Random projects, also let
the owner choose `split` or static `single_batch`; the latter has no held-out
sets or acquisition loop but permits consensus.

Persist the server-returned value in the project review, draft recovery, and
project settings views. The review must state that random acquisition selects
from the eligible unlabeled training pool after the preceding image batch has
an accepted canonical resolution. If the API reports that the setting is
locked, render it read-only with the server's value and explain when it became
locked; do not retain a conflicting browser-only draft.

### A5-02

For Random acquisition, use plain language: “Randomly selected from the
remaining eligible training images.” Do not show model scores, confidence,
ranking, training progress, or any model-guided terminology.

Managers may inspect the completed batch's strategy, server-generated seed,
input fingerprint, requested size, selected size, and selection time. Explain
that validation and test images are never eligible, completed training images
are excluded, and cancelled or incomplete training images may return to the
pool. When the pool is empty, show that acquisition has finished; when fewer
images remain than `iteration_batch_size`, state that the final batch may be
smaller.

### A5-03

Show a caller-specific queue of direct complete-image assignments. Do not show
claim, lease, renewal, expiry, release, or lease-loss controls. A consensus
annotator can open the same image independently of peers; the queue must never
hide an assignment because another annotator is working on that image.

Provide filters for batch purpose and personal state (`available`, `in
progress`, `submitted`), deterministic ordering supplied by the API, and
keyboard-accessible next/previous navigation. Store unsaved work against the
`assignment_id` and its version. On offline use or a stale-version response,
retain the local draft, refetch the assignment, and offer a clear resume or
reconciliation path. Display manager reassignment or reopen controls only when
the authorized API action exists; annotators have no self-cancel action.

### A5-04

Autosave full-image work every ten minutes and provide an explicit Save action.
On return, restore the newest server or local recovery draft for the same
`assignment_id`, identify its save time, and never present recovery data as a
submitted annotation.

Before final submission, require confirmation for an explicitly empty
detection or segmentation image. Submit through an idempotency key and show
**Submission received** after success. Do not state that the image is resolved:
in single mode it awaits the canonical-resolution response, while in consensus
mode it awaits the other required submissions and then consensus or
adjudication. After submission, keep peer evidence, peer progress, and
consensus diagnostics hidden. If a manager reopens or reassigns work, preserve
the annotator's recoverable draft and explain the new assignment state.

Only owners/managers may reach the import screen, which appears before
assignment distribution. Show import parsing/mapping errors and an explicit
accept/discard step. A seeded draft may say that it began from imported labels,
but it must identify the saving annotator as the author of the saved work and
must not describe the import as a resolved annotation.

## Decisões

Fechadas localmente em 2026-09-30, sob autorização explícita da Stephany, a
partir das observações acima. O trabalho é feito na branch `phase-05`, e cada
decisão registra o motivo e a alternativa rejeitada. **Continuam sujeitas à
revisão do Meirelles.** Onde as observações acima respondem, elas foram
seguidas; o que segue preenche o que ficou em aberto.

### D1 — `P5-01` Mutabilidade da estratégia de aquisição

**Escolha:**

- `PATCH /api/v1/projects/{id}` (já versionado) passa a aceitar `acquisition_strategy`.
- Em projetos `split`, a troca vale nos dois sentidos, em `draft` ou `active`.
- Um projeto `single_batch` recusa qualquer valor diferente de `random` com `422 acquisition_strategy_not_allowed`.
- A troca incrementa `projects.version` e grava a auditoria `project.acquisition_strategy_changed`, com antes e depois.

**Motivo:** a observação permite a troca depois da ativação. Nenhuma regra
de bloqueio foi criada, porque o que a travaria (um lote de aquisição
existente) só passa a ser escrito na Fase 7.

**Rejeitada:** uma rota própria para a estratégia. Duplicaria o versionamento
que o `PATCH` já faz.

### D2 — `P5-02` Semântica da aquisição aleatória

**Escolha:** a implementação da 4.1, sem código novo:

- ordem `(relative_path, id)`;
- semente de 62 bits gerada pelo servidor (`secrets`);
- `selection.choose_up_to`, que sorteia o pool inteiro quando ele é menor que o pedido;
- fingerprint SHA-256 dos ids ordenados;
- proveniência gravada no lote.

**Motivo:** o registro pede exatamente esses itens, e eles já existem e são
testados. Quem chama o sorteio é o produtor de aquisição da Fase 7.

### D3 — `P5-03` Modo `single` sem claim

**Escolha:** no `start`, cada imagem de um lote `single` recebe um anotador
nomeado, em rodízio:

- pelos membros do grupo, na ordem registrada, quando o grupo não está vazio;
- senão, por todos os membros com autoridade de anotação (owner, manager e annotator), em ordem de username.

As imagens seguem a ordem `(relative_path, id)`. Por isso,
`annotation_assignments.annotator_id` passa a ser `NOT NULL`.

**Motivo:** a Fase 4 (D5) deixava o anotador nulo para "qualquer um pegar".
Sem claim, uma tarefa sem dono não chega a ninguém. O rodízio é
determinístico e não disputa nada. Um owner que não quer receber parte do
trabalho define um grupo.

**Rejeitada:** manter o nulo e dar a tarefa a quem salvar primeiro. Seria um
claim disfarçado, com a própria condição de corrida.

**Efeito na migração:** exige o reset de desenvolvimento já pedido pela 4.1,
porque nenhum lote `single` iniciado antes pode existir.

### D4 — `P5-03` Fila e acesso

**Escolha:**

- `GET /api/v1/projects/{id}/assignments` lista **só** as tarefas de quem chama.
  - Exclui as terminais.
  - Ordem: criação do lote, `(relative_path, id)` da imagem, id da tarefa.
  - Filtros: `purpose` e `state` (`pending`, `in_progress`, `submitted`; o App mostra `pending` como "Available").
  - As contagens são apenas as próprias.
- `GET …/assignments/{assignment_id}` devolve:
  - a tarefa, sua versão e a finalidade do lote;
  - a mídia com uma URL de imagem assinada (**D11**);
  - os objetos atuais e `seeded_from_import`.
- Só o dono da tarefa a acessa. Isso inclui administradores e gerentes: os outros recebem `403 assignment_not_owned`.
- Desconectar não tem efeito, porque nada é travado. A recuperação vem do último rascunho salvo e do snapshot local (A5-04).

### D5 — `P5-04` Ciclo da tarefa, reabertura, reatribuição e cancelamento

**Estados:**

- Tarefa: `pending → in_progress → submitted`, mais os terminais `reassigned` e `cancelled`.
- Item: `pending → awaiting_resolution → resolved`, mais `cancelled`.

**Rascunho:** salvar leva a tarefa a `in_progress` e incrementa a versão.

**Entrega:**

- Cria uma revisão imutável em `annotation_submissions` (1, e 2 depois de uma reabertura, e assim por diante), leva a tarefa a `submitted` e incrementa a versão.
- Entrega repetida:
  - com a mesma `Idempotency-Key`, a resposta original é repetida;
  - sem ela, `409 assignment_already_submitted`.

**Ações do gerente (ação `manage_assignments`, todas auditadas):**

- **Reabrir:** uma tarefa `submitted` cujo item não esteja resolvido volta a `in_progress` para o mesmo anotador. O rascunho recebe a última entrega, e a versão é incrementada. Uma imagem já resolvida ou cancelada recusa as ações do gerente com `409 item_closed`.
  - Uma aba aberta com a versão antiga recebe `409`.
  - No modo `single` a entrega já resolve a imagem, então ela não pode ser reaberta. Isso é coerente com "antes de ir para a resolução".
- **Reatribuir:** vale em `pending`, `in_progress` ou `submitted`, desde que o item não esteja resolvido.
  - A tarefa antiga vira `reassigned` e guarda seu rascunho e suas entregas como evidência.
  - Uma tarefa nova é criada para o destino, começando do seed e nunca do trabalho do colega.
  - O destino precisa ter autoridade de anotação e não pode já ter esse item (`409 already_assigned`).
- **Cancelar a imagem:** `POST /projects/{id}/batch-items/{item_id}/cancel`, só em lotes `initial_training` e `acquisition`.
  - O item e suas tarefas ativas viram `cancelled`, e a imagem volta ao pool de treino.
  - Validação e teste são conjuntos fixos: `409 cancel_not_allowed`.
  - O cancelamento é da imagem inteira, e não de uma tarefa, porque cancelar uma de três tarefas de consenso deixaria a imagem abaixo das entregas exigidas, e o plano proíbe ficar abaixo de duas.

**Contradição resolvida — reatribuir tarefa em andamento.** A `P5-03` diz
que isso não é suportado, e a `P5-04` diz que é possível "antes e depois da
entrega". Foi escolhida a `P5-04`, que é o texto mais detalhado e o único
caminho para recuperar uma imagem cujo anotador saiu no meio do trabalho. Sem
ele, uma imagem de validação ou teste, que não pode ser cancelada, ficaria
travada. **Ponto para o Meirelles confirmar.**

### D6 — `P5-05` Contrato do documento

**Formato na rede:** o do `api-contract.md`, sem mudança:
`{media_id, task_type, version, objects}`. Cada objeto é
`{id, class_id, geometry, attributes}`.

**Armazenamento:** só a lista `objects`, em JSONB. Não há tabela
`annotation_objects`, porque nada na Fase 5 consome objetos como linhas.

**Geometria:**

- Detecção: `rectangle [x, y, largura, altura]`, com largura e altura maiores que zero, dentro da imagem.
- Segmentação: `polygon`, uma lista de anéis `[x1, y1, x2, y2, …]`. Cada anel tem pelo menos 3 pontos distintos, fica dentro da imagem e não se auto-intercepta. É a mesma função pura da importação.
- Classificação: `geometry: null`.

**Precisão:** pixels da imagem original, gravados como enviados. Os números
precisam ser finitos, e não há arredondamento.

**Multi-rótulo:** uma imagem pode ter várias classes em todas as tarefas.

- Cada objeto de detecção ou segmentação tem exatamente uma classe.
- A classificação é um conjunto de classes distintas, como o App já faz.
- Isso fixa a configuração que `consensus/classification.md` exige que seja explícita: multi-rótulo em todas as tarefas nesta versão. Um modo de rótulo único por projeto fica adiado.
- **Ponto para o Meirelles:** a observação foi lida como "várias classes por imagem", não "várias classes por objeto".

**Imagem vazia:**

- Uma **entrega** sem objetos é a marcação explícita de imagem vazia. É permitida em detecção e segmentação, e o App pede confirmação.
- A classificação exige ao menos uma classe.
- Um rascunho pode estar vazio.

**Profundidade da validação:**

- O rascunho é validado só na estrutura e nos limites, para que trabalho incompleto sempre possa ser salvo.
- A entrega recebe a validação completa.
- Os erros de regra saem como `422 invalid_document`, com `details.errors: [{object_id, code}]`. Os códigos são:
  - `unknown_class`
  - `wrong_geometry`
  - `out_of_bounds`
  - `degenerate_geometry` (caixa sem área, ou anel com menos de 3 pontos distintos)
  - `self_intersecting`
  - `duplicate_object_id`
  - `duplicate_class`
  - `empty_not_allowed`

**Limites:** 1.000 objetos por imagem e 1.000 pontos por anel. O segundo
mantém rápida a checagem O(n²) de auto-interseção. Os limites e números não
finitos são recusados pelo próprio schema, como qualquer corpo malformado
(`422` de validação).

**Versão do esquema:** cada entrega grava `schema_version = 1` e um
`content_hash` SHA-256 do JSON canônico, como o `CE-F01` exige para a Fase 6.

### D7 — Seeds são copiados no início (substitui a D9 da 4.1)

**Escolha:** no `start`, e numa reatribuição, o rascunho de cada tarefa
recebe uma cópia dos objetos do seed da imagem. O vínculo `seed_document_id`
continua na tarefa e é copiado para cada entrega, como proveniência. O autor
da entrega é o anotador (`submitted_by`). O seed nunca muda e nunca é lido
como voto nem como resolução.

**Motivo:** é o texto literal da Fase 5 ("clone … into each annotator's
editable draft"). Com o rascunho guardado na própria tarefa, a cópia é uma
única atribuição.

### D8 — Persistência e a resolução do modo `single`

Migração `20260930_0008`:

| Mudança | Descrição |
| --- | --- |
| `annotation_assignments` | `annotator_id NOT NULL` (**D3**), mais `version`, `draft` (JSONB), `draft_saved_at` e `updated_at` |
| `annotation_submissions` | Uma revisão imutável por entrega, única em `(assignment_id, revision)`, com `content_hash`, `schema_version`, `seed_document_id` e `submitted_by` |
| Vínculos com o seed | `annotation_assignments.seed_document_id` e `annotation_submissions.seed_document_id` passam a `ON DELETE SET NULL` (ver "Defeito encontrado") |
| `resolved_annotations` | Uma versão da resolução canônica por item, única em `(batch_item_id, version)`. É o nome do agregado Resolution no plano; runs, inputs e work items são da Fase 6 |

**Modo `single`:** na mesma transação da entrega:

- grava a versão 1 de `resolved_annotations`;
- leva o item a `resolved`;
- move o lote de `annotating` para `resolved` quando todas as imagens não canceladas estiverem resolvidas.

Com isso, a readiness da 4.1 (**D8** de lá) passa a ter um escritor real.

**Modo `consensus`:**

- Quando todas as tarefas ativas do item estiverem `submitted`, o item vira `awaiting_resolution`.
- A entrada de outbox que o `CE-F01` pede fica com a infraestrutura de jobs da Fase 6. Este é o ponto onde ela entra.

**Concorrência:** a entrega trava a linha do item (`SELECT … FOR UPDATE`),
para que duas últimas entregas simultâneas não percam a readiness.

**Pool e readiness:** um item cancelado deixa de reter sua imagem, e a
readiness o ignora.

**Contagens do lote:** separam imagens resolvidas e aguardando resolução, e
tarefas disponíveis, em andamento e entregues.

### D9 — `P5-06` Cegueira nas rotas existentes

**Escolha:**

- `GET /batches` e `GET /batches/{id}` passam de `read_project` para `manage_annotation_policy` (owner e manager). Hoje elas mostram a um anotador o grupo (`annotator_ids`) e as entregas dos colegas.
- A resposta da entrega informa só o resultado de quem entregou: `image_resolved` é verdadeiro no modo `single` e sempre falso no consenso, para não revelar se os colegas terminaram.
- O detalhe da tarefa diz apenas se ela começou de rótulos importados, e a importação continua visível só para owner e manager.
- Não há eventos na Fase 5 para censurar.

### D10 — Matriz de autorização

**Escolha:** `revoke_lease` é renomeada para `manage_assignments`, com as
mesmas concessões (owner e manager). Leases de anotação não existem mais, e
essa ação é a autoridade de listar, reabrir, reatribuir e cancelar. A matriz
continua com 13 ações e 52 pares.

### D11 — Bytes da imagem por URL assinada

**Escolha:** `GET /api/v1/media/{media_id}/content?expires=…&signature=…`.

- A assinatura é um HMAC-SHA256 sobre `media:{media_id}:{expires}`, no mesmo padrão dos cursores.
- A URL vale 1 hora. A política de expiração é a `P8-02`.
- Assinatura inválida ou vencida gera `403 invalid_media_url`.
- Os bytes saem pelo adaptador de storage, que continua sendo a única fronteira com o disco.

**Motivo:** nenhuma rota entregava a imagem. O contrato fala em URL assinada,
e a arquitetura proíbe token de acesso na URL.

### D12 — Fila protótipo removida

**Escolha:** `/api/v1/queue/next` e `/api/v1/queue/annotations` saem. O segundo
respondia `200 accepted` sem gravar nada, uma dívida registrada desde a
Fase 1. O SAM continua `501`; ele é da Fase 7.

### Decisões do App

| Decisão | Escolha |
| --- | --- |
| **A5-01** | Rádio **Random acquisition / Active learning** no passo Learning, com Random por padrão. Active learning desativa o lote estático e mostra o motivo. A revisão e a recuperação do draft usam o valor do servidor. As configurações do projeto mostram a estratégia e permitem trocar em projetos `split` |
| **A5-02** | O texto do Random é "Randomly selected from the remaining eligible training images.", sem linguagem de modelo |
| **A5-03** | A fila pessoal tem filtros de finalidade e de estado e navegação por setas. Não há controles de lease. O gerente reabre, reatribui ou cancela a imagem numa lista de tarefas por lote, na página de lotes. Cada card de projeto ativo ganha o link **Open my assignments** |
| **A5-04** | Autosave no servidor a cada 10 minutos, mais o botão Save e Ctrl+S. Snapshot local a cada mudança, com a chave `{projeto}:{tarefa}:{versão}` e validade de 24 h. Numa versão desatualizada, **Keep my version** ou **Use server version**. A entrega pede confirmação se estiver vazia e mostra só **Submission received**, nunca "resolvida", como a A5-04 pede |
| **I5-01..04** | Os registros de resolução ficam em [issues_before_phase5.md](../../../dada-app/docs/issues_before_phase5.md) |

## Implementação

Status: API e App implementados em 2026-09-30, na branch `phase-05`, sem
commit. Pendente da revisão do Meirelles.

Guia de operação: [development.md](../development.md#image-assignments-phase-5).
Formas no contrato do App: `dada-app/docs/api-contract.md`, seção "Phase 5
implemented shapes".

### Persistência

Migração `20260930_0008`, exercitada upgrade → downgrade → upgrade. A tabela
**D8** acima descreve as mudanças.

### Rotas

| Rota | Função |
| --- | --- |
| `GET /api/v1/projects/{id}/assignments` | Fila pessoal, com filtros e contagens próprias |
| `GET /api/v1/projects/{id}/assignments/{assignment_id}` | Abre uma tarefa: imagem, URL assinada e objetos |
| `PUT /api/v1/projects/{id}/assignments/{assignment_id}/draft` | Salva o rascunho versionado |
| `POST /api/v1/projects/{id}/assignments/{assignment_id}/submit` | Entrega imutável e idempotente |
| `GET /api/v1/media/{media_id}/content` | Bytes da imagem por link assinado |
| `GET /api/v1/projects/{id}/batches/{batch_id}/assignments` | Tarefas do lote, para o gerente |
| `POST /api/v1/projects/{id}/assignments/{assignment_id}/reopen` | Reabre uma entrega |
| `POST /api/v1/projects/{id}/assignments/{assignment_id}/reassign` | Reatribui a imagem |
| `POST /api/v1/projects/{id}/batch-items/{item_id}/cancel` | Cancela uma imagem de treino |

`PATCH /projects/{id}` passou a aceitar `acquisition_strategy`. As leituras de
lote passaram a `manage_annotation_policy`. As rotas `/queue` foram removidas.
O `openapi.json` foi de 38 para 45 rotas e de 51 para 62 schemas.

### App

| Mudança | Onde |
| --- | --- |
| Workspace convertido de lease para tarefa: fila pessoal com filtros, abrir sem travar, autosave de 10 min, Save, entrega idempotente, confirmação de imagem vazia, escolha em versão desatualizada | `AnnotationWorkspacePage.tsx`, `annotation-api.ts`, `assignment-view.ts` |
| Recuperação por projeto, tarefa e versão | `recovery.ts` |
| Estratégia de aquisição na criação e nas configurações | `NewProjectPage.tsx`, `ProjectSettingsPage.tsx`, `project-api.ts` |
| Tarefas do lote, com reabrir, reatribuir e cancelar imagem | `BatchAssignmentsPanel.tsx`, `ProjectBatchesPage.tsx`, `batch-api.ts` |
| Link **Open my assignments** e links do card em coluna (I5-02) | `ProjectsPage.tsx`, `projects.css` |
| Seleção cumulativa de pastas e arquivos (I5-01, I5-03) | `NewProjectPage.tsx`, `DraftProjectSetupPage.tsx`, `ingest.ts` |
| Cancelar a criação (I5-04) e retomada sem projeto duplicado (I5-05) | `NewProjectPage.tsx`, `DraftProjectSetupPage.tsx` |

### Autorização

A matriz continua com 13 ações e 52 pares. `revoke_lease` virou
`manage_assignments` (**D10**). Fila, rascunho e entrega usam `annotate` mais a
regra de dono da tarefa.

## Defeito encontrado

A exclusão de um projeto com uma entrega feita a partir de um seed falhava com
violação de chave estrangeira. As exclusões em cascata do PostgreSQL rodam em
etapas: os seeds (projeto → importação → seed) eram apagados antes das
entregas que apontavam para eles (projeto → lote → item → tarefa → entrega), e
a chave `NO ACTION` reclamava no fim da etapa.

O vínculo da tarefa com o seed, criado na 4.1, tinha a mesma fragilidade; só
não tinha falhado ainda. Os dois vínculos passaram a `ON DELETE SET NULL`. Um
seed só desaparece junto com o próprio projeto, então isso nunca altera uma
entrega que sobrevive. Encontrado por
`test_a_seeded_submission_is_the_annotators_and_deletion_removes_it`.

Também no App, registrado como `I5-05`: repetir uma criação que falhou depois de
o projeto existir criava um segundo projeto.

## O que ficou de fora

| Item | Motivo |
| --- | --- |
| Resolução de consenso, outbox e jobs | Fase 6. A entrega marca `awaiting_resolution` no ponto onde o outbox entra |
| Produtor de aquisição e iterações | Fase 7. `ProjectActivityPage` continua dependendo de `/iterations` |
| SAM | Fase 7; o App só deixou de mandar `lease_id` |
| Eventos em tempo real | Fase 8; o workspace segue por polling |
| Modo de rótulo único para classificação | Adiado (**D6**) |

## Verificação

Executado contra PostgreSQL e Redis reais dos containers do Compose, com o
ambiente conda `dada2`.

- `ruff check` e `ruff format --check`: limpos. `alembic check`: sem divergência.
- Testes da API: **312 passaram** com integração habilitada, contra 286 no início.
- `openapi.json` regenera de forma determinística.
- App: `npm run check` verde (lint, TypeScript, build) com **67 testes**, contra 47 no início.
- Fluxo ponta a ponta contra a API rodando (uvicorn), com PNGs reais enviados em chunks:
  - dois anotadores recebem a mesma imagem em tarefas diferentes e não leem o lote nem a tarefa um do outro;
  - a imagem sai pelo link assinado sem token, e o CORS responde à origem do App;
  - um rascunho desatualizado é recusado e a entrega repetida com a mesma chave é reproduzida;
  - a imagem só fica `awaiting_resolution` depois das duas entregas.
- **Não verificado:** duas sessões reais de navegador na mesma imagem (o critério de saída do App). Fica para o teste manual.

### Cobertura dos critérios de saída

| Critério | Como foi provado |
| --- | --- |
| A criação persiste a estratégia de aquisição | `test_the_acquisition_strategy_changes_only_on_split_projects` (API); `project-api.test.ts` (corpo da criação) |
| Todos os anotadores do consenso anotam a mesma imagem independentemente | `test_two_consensus_annotators_work_the_same_image_independently` e o fluxo ponta a ponta |
| Rascunhos desatualizados falham | `test_stale_drafts_and_duplicate_submissions_are_refused`, `test_reopen_gives_submitted_work_back_as_a_new_revision` |
| Entregas duplicadas falham | Mesmo teste: `409 assignment_already_submitted`, e a mesma chave reproduz o `200` |
| Acesso cruzado falha | `test_only_the_assignee_reaches_an_assignment` (colega, owner e administrador) |
| Ninguém vê evidência dos colegas | `test_batch_routes_are_a_manager_view` e os campos da fila, fixados em `QUEUE_FIELDS` |
| A recuperação local não colide | `recovery.test.ts` (duas tarefas da mesma imagem) e `assignment-view.test.ts` |
| O caminho aleatório é descrito corretamente | Textos da A5-02 no assistente e nas configurações |
| I5-01..05 | [issues_before_phase5.md](../../../dada-app/docs/issues_before_phase5.md) |
| Modo `single` resolve e libera a primeira aquisição | `test_single_mode_submissions_resolve_images_and_unlock_acquisition`. Fecha o ponto **parcial** da D8 da 4.1 |
| O seed chega a cada anotador e nunca é voto | `test_an_accepted_import_seeds_every_assignment_without_submitting`, `test_a_seeded_submission_is_the_annotators_and_deletion_removes_it`. Fecha o ponto **parcial** da D9 da 4.1 |
