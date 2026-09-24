# Fase 4.1: Correção da Sequência de Anotação, Layout do Dataset e Importação de Rótulos

Status: API e App implementados em 2026-09-24, na branch `api-phase4.1`
cortada de `development` em `df17d39`. Pendente da revisão do Meirelles.

Plano de referência: [phase-4-annotation-sequence-revision-plan.md](../phase-4-annotation-sequence-revision-plan.md),
na versão do commit `5191c98` (branch `phase-05`), que acrescenta `dataset_layout`,
`single_batch` e a importação de rótulos à versão presente em `development`.
Plano da API: [api-implementation-plan.md](../api-implementation-plan.md).
Guia de operação: [development.md](../development.md).

## Objetivo

A Fase 4 entregou splits fixos, mas o lote `initial_training` cobria o split de
treino inteiro. A correção 4.1, obrigatória antes da Fase 5, muda isso e
acrescenta dois recursos de preparação:

| Frente | O que resolve |
| --- | --- |
| **Sequência de anotação** | O primeiro lote de treino passa a ter `initial_training_size` imagens (ou `iteration_batch_size` quando omitido); o resto do treino fica no pool não rotulado. A primeira aquisição passa a exigir resolução aceita, não só submissão |
| **Layout do dataset** | `split` (treino/validação/teste) ou `single_batch` (um lote estático com todas as imagens, só para projetos aleatórios), materializado numa preparação explícita do draft |
| **Importação de rótulos** | Owners e managers podem semear o trabalho com rótulos YOLO (detecção) ou COCO (segmentação). O seed nunca é submissão, voto ou resolução |

## O que foi implementado

### Persistência

Migração `20260924_0007`.

| Mudança | Descrição |
| --- | --- |
| `projects.acquisition_strategy` | `random` ou `active_learning`, padrão `random` (ver **D1**) |
| `projects.dataset_layout` | `split` ou `single_batch`, padrão `split` (ver **D2**) |
| `projects.dataset_prepared_at` | Preenchido enquanto o draft está preparado; volta a `NULL` no reset |
| `projects.initial_training_size`, `iteration_batch_size` | Passaram a aceitar `NULL` |
| `annotation_imports` | Uma importação por projeto (ver **D10**), com snapshot do mapa de classes e do inventário |
| `annotation_import_files` | Os arquivos de origem guardados na íntegra, com digest (ver **D11**) |
| `imported_seed_documents` | Um documento imutável por imagem rotulada |
| `annotation_assignments.seed_document_id` | Vínculo com o seed da imagem (ver **D9**) |
| `batch_items.status = resolved` | Valor novo, sem DDL: o sinal da resolução aceita (ver **D8**) |
| `BatchPurpose.initial_annotation` | Valor novo, sem DDL: o lote único do `single_batch` |

### Rotas

| Rota | Função |
| --- | --- |
| `GET /api/v1/projects/{id}/dataset-layout` | Layout, tamanhos, lotes, pool de treino e importação |
| `POST /api/v1/projects/{id}/dataset-layout/prepare` | Sorteia o split e abre os lotes iniciais |
| `DELETE /api/v1/projects/{id}/dataset-layout` | Descarta a preparação e a importação |
| `POST /api/v1/projects/{id}/annotation-imports` | Abre uma importação a partir de um manifesto |
| `POST /api/v1/annotation-imports/{id}/files/{client_file_id}` | Recebe um arquivo inteiro |
| `POST /api/v1/annotation-imports/{id}/validate` | Analisa e grava o relatório |
| `POST /api/v1/annotation-imports/{id}/accept` | Persiste os seeds |
| `GET /api/v1/annotation-imports/{id}` | Status, arquivos e relatório |
| `DELETE /api/v1/annotation-imports/{id}` | Descarta uma importação não aceita |

`POST /activate` deixou de sortear: agora exige a preparação e nenhuma
importação pendente. `POST /batches/{id}/start` passou a exigir projeto ativo e
vincula cada assignment ao seed da sua imagem.

### Preparação

Para `split`, teste é sorteado do inventário ordenado inteiro, validação do
restante e o primeiro lote de treino do que sobra. Cada lote grava a semente e o
fingerprint **do próprio sorteio**, o que fecha a limitação registrada em
`dataset-split-workflow-review.md`: as sementes dos splits deixaram de se
perder. A capacidade é verificada só contra os conjuntos reservados e o primeiro
lote (`409 preparation_incomplete` com `insufficient_media`).

As imagens de treino não sorteadas não têm item de lote e formam o pool
elegível. Uma imagem de treino sai do pool enquanto um lote de treino vivo a
contém e para sempre quando seu item é resolvido; volta ao pool quando o lote
termina `closed` ou `failed` sem resolvê-la (ver **D7**). O último lote pode ser
menor que o pedido: `selection.choose_up_to` limita o sorteio ao pool.

### Importação

| Formato | Tarefa | Correspondência | Geometria |
| --- | --- | --- | --- |
| `yolo_detection` (`yolo-detection/1`) | detecção | `a/b.txt` rotula a imagem `a/b.*` | `class cx cy w h` normalizado vira `[x, y, largura, altura]` em pixels |
| `coco_segmentation` (`coco-segmentation/1`) | segmentação | `images[].file_name` igual ao caminho relativo | polígonos viram anéis `[x1, y1, ...]` em pixels |

O índice de classe (`class_id`/`category_id`) casa com `display_order`. Qualquer
erro rejeita a importação inteira; ela é descartada e refeita. Imagens sem
rótulo continuam válidas e são apenas contadas.

### App

| Mudança | Onde |
| --- | --- |
| Escolha do layout (**Split dataset** ou **One static annotation batch**); o estático esconde os campos de split e iteração | `NewProjectPage.tsx`, passo 3 |
| Primeiro lote de treino opcional, com o texto "vazio usa o tamanho por iteração" | `NewProjectPage.tsx` |
| Estimativa de trabalho e capacidade calculadas pelos três lotes iniciais, com o pool restante na revisão | `NewProjectPage.tsx` |
| O fluxo de criação termina no `prepare`; a ativação virou um passo próprio, depois da revisão da importação | `project-api.ts`, `setup-recovery.ts` (estágio `prepared`) |
| Passo **Prepare**: resumo do layout, importação YOLO/COCO com relatório de erros, aceitar ou descartar, reset e ativação | `DatasetPreparationPanel.tsx`, `dataset-api.ts` |
| O draft retoma na preparação a partir do estado do servidor e avisa que mudar classes ou mídia reseta a preparação | `DraftProjectSetupPage.tsx` |
| Lotes: rótulo `initial_annotation`, texto sem "treino completo" e pool restante | `ProjectBatchesPage.tsx` |

Os caminhos dos rótulos são relativos à pasta selecionada, como os das imagens.
Selecionar a pasta `labels/` de um dataset YOLO faz as árvores paralelas
`images/` e `labels/` casarem sem nenhuma regra extra no servidor.

A escolha da estratégia de aquisição **não** foi adicionada à interface: é
`A5-01`. Todo projeto criado pelo App nesta fase é `random`, e por isso as duas
opções de layout ficam disponíveis.

### Códigos de erro estáveis introduzidos

`preparation_incomplete`, `dataset_already_prepared`, `dataset_not_prepared`,
`project_not_active`, `import_not_supported`, `import_already_exists`,
`import_not_uploading`, `import_files_incomplete`, `import_not_valid`,
`import_accepted`. Dentro do relatório: `invalid_relative_path`,
`unmatched_path`, `ambiguous_media_match`, `duplicate_source_label`,
`unknown_class_index`, `malformed_label`, `invalid_geometry`,
`unsupported_geometry`.

`activation_incomplete` manteve a forma; `details.missing` ganhou
`dataset_layout` e `label_import`.

### Autorização

Nenhuma ação nova; a matriz continua com 13 ações e 52 pares. Preparação, reset
e todas as operações de importação usam `update_project` (owner e manager), a
mesma ação que já guarda o upload de mídia. `GET /dataset-layout` usa
`read_project`. A leitura de uma importação fica com owner e manager, porque a
visibilidade do seed para anotadores é a decisão `P5-06`.

## Decisões tomadas

As doze lacunas foram fechadas localmente em 2026-09-24, sob autorização
explícita da usuária, com a condição de que o trabalho ficasse em branch e cada
decisão registrasse seu raciocínio. **Continuam sujeitas à revisão do
Meirelles.** Texto completo em `.claude/plans/phase-4.1.md`.

Quatro delas tocam território das Fases 5 e 6 (**D1**, **D8**, **D9**, **D12**)
e estão marcadas para que fique claro onde a 4.1 se adianta.

| Decisão | Escolha | Motivo |
| --- | --- | --- |
| **D1** `acquisition_strategy` | Entra agora, mínima: `random`/`active_learning`, padrão `random`, definida só na criação | A 4.1 exige a regra "`single_batch` só com aleatória", que não existe sem o campo. A mutabilidade depois da ativação e a UI continuam sendo `P5-01`/`A5-01` |
| **D2** Onde se escolhe o layout | Na criação do projeto; `prepare` não tem corpo | `single_batch` não aceita tamanhos, então o layout precisa ser conhecido ao validar o corpo da criação. Nenhuma rota edita tamanhos hoje; recriar o projeto já é o caminho |
| **D3** Onde o split é materializado | Na preparação, ainda em draft; a ativação só trava | Reconcilia "a ativação congela" (item 3 do plano) com "materializado enquanto draft" (seção de layout e contrato). Nada é sorteado na ativação |
| **D4** Mudança de insumo preparado | Reset automático na mesma transação, auditado com o motivo | O contrato diz que mudar um insumo reseta a preparação. Refinamento feito na implementação: só reseta o que muda o **mapa de índices** — criar ou apagar classe, mudar `display_order`, ou nova mídia. Renomear ou recolorir uma classe não reseta |
| **D5** Tamanhos resolvidos | Gravados em `test_set_size`/`validation_set_size` na preparação, como na Fase 4; o reset devolve `NULL` quando há percentual | Mantém o contrato da Fase 4 e deixa o próximo `prepare` recalcular |
| **D6** Proveniência dos splits | Cada lote grava a semente do sorteio que o criou | Antes, os lotes de teste e validação ressorteavam o próprio split com semente nova e a semente do split se perdia. Nenhuma tabela nova |
| **D7** Pool de treino | Sai do pool: item resolvido, ou item em lote de treino vivo. Volta: item não resolvido em lote `closed`/`failed` | Não existe status `cancelled` nem operação de cancelamento (`P5-04`). O cancelamento da Fase 5 só precisa levar o lote a um status terminal |
| **D8** Readiness | `batch_items.status == "resolved"` nos três lotes iniciais; sempre falso para `single_batch` | As tabelas de resolução são das Fases 5 e 6. Elas serão as escritoras desse status; os testes da 4.1 o definem diretamente |
| **D9** Seed por anotador | Vínculo `seed_document_id` no assignment, não cópia | A cópia editável exige tabela de rascunho, que é da Fase 5. O seed é imutável, então o vínculo funciona como copy-on-write; o primeiro salvamento da Fase 5 cria o rascunho próprio |
| **D10** Quantas importações | No máximo uma por projeto | "Rótulo duplicado para uma imagem" vira propriedade de uma importação só, sem mesclagem |
| **D11** Transporte e armazenamento | Arquivo inteiro por requisição, conferido por tamanho e SHA-256, guardado em `bytea`, limitado por `DADA_MAX_IMPORT_FILE_BYTES` (50 MiB) | Rótulos são pequenos; a proveniência exige reter o arquivo. O adaptador de storage é para mídia |
| **D12** Regras de parsing e geometria | Ver a seção Importação. Sem dependência nova: a checagem de auto-interseção é uma função pura | Parte das regras vem de `P5-05`, ainda pendente: precisão de coordenadas, multi-rótulo, limites de complexidade |

### Julgamento registrado: auditoria sem conteúdo

A auditoria da importação registra formato, versão do parser, contagens e
status — nunca o conteúdo dos rótulos nem geometria, pela regra de não registrar
payloads de anotação. Os digests dos arquivos ficam registrados de forma
imutável em `annotation_import_files`, e não são duplicados na auditoria: numa
importação YOLO com milhares de arquivos, isso tornaria cada entrada enorme.

### Julgamento registrado: tolerância no YOLO

Exportadores YOLO arredondam para poucas casas decimais, então uma caixa
encostada na borda pode passar de `1.0` por arredondamento. Valores até `1e-6`
além da borda são aceitos e recortados à imagem; acima disso, `invalid_geometry`.

### Para o Meirelles: convenção de caminhos do YOLO

O plano diz que o rótulo casa com "o caminho relativo sem o sufixo da imagem".
Isso só vale para arquivos `.txt` **ao lado** das imagens. O layout mais comum de
datasets YOLO usa árvores paralelas `images/` e `labels/`, que não casariam. A
regra foi implementada literalmente.

## Defeito encontrado

Um validador de modelo Pydantic que levanta `ValueError` deixa a própria
exceção em `ctx`, e o handler de erros de validação tentava serializá-la em
JSON: o resultado era **500**, não 422. O defeito já existia desde a Fase 4 — um
`POST /projects` com contagem e percentual para o mesmo split já o disparava —,
mas só era testado via `model_validate`, nunca por HTTP. Um teste da 4.1 o
encontrou. `redact_validation_errors` agora reporta a exceção pela mensagem.

## O que ficou de fora

| Item | Motivo |
| --- | --- |
| Rascunho editável por anotador | Fase 5 (**D9**) |
| Escrita de `batch_items.status = resolved` | Fases 5 (modo `single`) e 6 (consenso) (**D8**) |
| Produtor de lotes de aquisição e iterações | Fase 7; o pool e `choose_up_to` já estão prontos |
| Mudar `acquisition_strategy` depois da criação | `P5-01` |
| RLE do COCO, YOLO em árvores paralelas | Fora do texto do plano (**D12**) |

## Verificação

Executado contra PostgreSQL e Redis reais dos containers do Compose, com o
ambiente conda `dada2`.

- `ruff check` e `ruff format --check`: limpos.
- `alembic check`: sem divergência. `20260924_0007` exercitada upgrade → downgrade → upgrade.
- Testes da API: **286 passaram** com integração habilitada, contra 229 no início.
- `openapi.json` regenera de forma determinística: 38 rotas (eram 31) e 51 schemas (eram 44).
- App: `npm run check` verde — lint, **47 testes** (eram 38), TypeScript e build de produção.
- Fluxo ponta a ponta contra a API rodando (uvicorn), com imagens PNG reais em
  chunks: ativação recusada antes do `prepare` (`dataset_layout`), preparação
  com 1 validação, 1 teste, 2 no primeiro lote e 1 no pool, importação YOLO
  validada (5 imagens, 4 objetos), ativação recusada com a importação pendente
  (`label_import`), aceite, ativação, três lotes iniciados sem submissões e
  projeto apagado.
- Reset de desenvolvimento: o banco local desta máquina foi criado do zero nesta
  fase, então não havia projetos antigos. A consulta de verificação devolveu
  zero em todas as colunas. **O ambiente compartilhado de desenvolvimento não
  foi tocado**: o procedimento está documentado para quem o opera.

### Cobertura da verificação exigida pelo plano

| Verificação exigida | Como foi provada |
| --- | --- |
| Configurações absolutas e percentuais congelam a partição pretendida | `test_preparation_freezes_three_splits_and_opens_the_initial_batches`, `test_percentage_sizes_are_resolved_and_fixed_at_preparation` |
| Com `initial_training_size`, o lote inicial tem esse tamanho | Mesmo teste de preparação (`requested_size` e `total_items`) |
| Sem ele, tem `iteration_batch_size` | `test_an_omitted_first_batch_size_uses_the_iteration_size` |
| Validação e teste completos; o resto do treino sem item e elegível | `test_held_out_media_never_reaches_the_training_batch`, `test_the_training_pool_keeps_unselected_and_returned_train_media` |
| A readiness só libera com resolução aceita em todas as imagens | `test_first_acquisition_waits_for_accepted_resolutions`: falsa com tudo submetido, falsa com uma imagem sem resolução, verdadeira só com todas. **Parcial**: prova a regra sobre o status do item; quem escreve o status são as Fases 5 e 6 |
| Lote cancelado ou incompleto devolve a mídia; mídia concluída nunca duas vezes | `test_the_training_pool_keeps_unselected_and_returned_train_media` |
| Último lote de aquisição pode ser menor | `test_a_final_batch_takes_the_whole_pool_when_it_runs_short` (unitário). **Parcial**: não há produtor de aquisição nesta fase |
| `single_batch`: um lote com tudo, recusa aprendizado ativo, sem splits, com consenso | `test_a_single_batch_project_annotates_every_image_once` |
| Importações recusam índice, caminho e geometria inválidos | `test_label_formats.py` (um caso por código) e `test_invalid_labels_reject_the_import_until_discarded` |
| Importações retêm proveniência de auditoria | `test_an_import_records_its_provenance_without_label_content` |
| Seeds chegam a cada anotador atribuído | `test_an_accepted_import_seeds_every_assignment_without_submitting`. **Parcial** (**D9**): prova o vínculo em cada assignment; o rascunho editável é da Fase 5 |
| Seeds nunca viram voto ou resolução | Mesmo teste: tudo `pending`, zero submetidos, zero itens resolvidos, readiness falsa |
| Reset de desenvolvimento | Procedimento em [development.md](../development.md#development-data-reset); verificado localmente. **Parcial**: o ambiente compartilhado ainda precisa ser resetado e reconstruído por quem o opera |
