# Fase 3: Ingestão Resumível e Mídia

Status: implementada em 2026-09-01 (API). O trabalho do App permanece pendente.

Plano de referência: [api-implementation-plan.md](../api-implementation-plan.md).
Plano do App: [annotator-disagreement-adaptation-plan.md](../../../dada-app/docs/annotator-disagreement-adaptation-plan.md).
Guia de operação: [development.md](../development.md).

## Objetivo

A Fase 2 fechou o assistente de criação de projeto, mas o dataset ainda não
existia: o App já sabia varrer a pasta, calcular SHA-256 e fatiar arquivos em
chunks, e recebia `404` em todas as cinco rotas de upload. A Fase 3 constrói o
lado que faltava — receber, verificar e guardar os bytes — e é a primeira em
que um projeto pode efetivamente ser ativado.

## O que foi implementado

### Persistência

Migração `20260901_0004`.

| Tabela | Descrição |
| --- | --- |
| `upload_sessions` | Uma tentativa de ingestão, com estado e prazo de expiração |
| `upload_items` | Um arquivo da sessão, com disposição, motivo de recusa e offset aceito |
| `upload_chunks` | Cada faixa de bytes aceita, com offset e checksum próprios |
| `content_objects` | Conteúdo verificado do projeto: digest, tamanho, dimensões e chave de armazenamento |
| `media` | A aparição do conteúdo em um caminho relativo do dataset |

`upload_items.received_bytes` é o próximo offset esperado. Ele vive no
PostgreSQL, não na memória do processo — é isso que faz um upload sobreviver a
um restart da API.

`content_objects` e `media` são tabelas separadas porque a mesma imagem
realmente aparece em dois caminhos numa varredura recursiva. Duas linhas de
`media` apontam para um único `content_object`, exatamente o caso que o
`findDuplicateGroups` do App já detecta localmente.

### Adapter de armazenamento

`services/storage.py` é o único módulo que toca o sistema de arquivos. Ele
recebe e devolve chaves de armazenamento e fluxos de bytes; nenhum objeto do
FastAPI ou do ORM cruza essa fronteira. Trocar disco local por um object store
depois substitui esse arquivo e nada mais.

Todo caminho é construído **apenas** com identificadores gerados pelo servidor e
com o digest verificado. Nenhum nome de arquivo ou caminho relativo vindo do
cliente chega ao filesystem. Um guarda de contenção recusa qualquer caminho que
resolva para fora da raiz configurada.

Layout:

```
{media_root}/{project_id}/{sha256[0:2]}/{sha256[2:4]}/{sha256}
{upload_parts_root}/{upload_session_id}/{upload_item_id}
```

O fan-out de dois níveis existe porque `max_project_files` anuncia 100 mil
arquivos, e um diretório plano nesse tamanho é problema real de filesystem.

### Rotas

| Rota | Função |
| --- | --- |
| `POST /api/v1/projects/{id}/uploads` | Cria a sessão e classifica cada entrada do manifesto |
| `PUT /api/v1/uploads/{id}/files/{client_file_id}` | Aceita um chunk verificado e confirma o próximo offset |
| `POST /api/v1/uploads/{id}/complete` | Verifica digests, lê dimensões e promove; idempotente |
| `GET /api/v1/uploads/{id}` | Estado e progresso por arquivo, para retomada |
| `DELETE /api/v1/uploads/{id}` | Cancela e purga as partes |
| `GET /api/v1/projects/{id}/media` | Inventário paginado por cursor |
| `DELETE /api/v1/projects/{id}` | Deleção terminal com purga (ver **D3**) |

`GET /api/v1/capabilities` passou a anunciar `upload_session_ttl_hours`, e os
quatro limites que já anunciava passaram a ser efetivamente aplicados — a
pendência que a Fase 2 registrou para cá.

### Códigos de erro estáveis introduzidos

Por requisição: `too_many_files`, `duplicate_client_file_id`,
`checksum_mismatch`, `offset_mismatch`, `file_too_large`, `invalid_image`,
`upload_not_complete`, `upload_not_active`, `upload_session_expired`,
`file_rejected`.

Por arquivo, no campo `reason` de um item `rejected`: `invalid_relative_path`,
`unsupported_media_type`, `file_too_large`.

Problemas do manifesto inteiro são erro de requisição; problemas de um arquivo
são uma disposição `rejected` com motivo, que é o que o contrato descreve.

### Autorização

Uma ação nova: `delete_project`, concedida apenas ao `owner` — e ao
administrador global, que contorna a matriz. Managers não deletam projeto, o
mesmo tratamento que `activate_project` já recebia. A matriz foi de 48 para 52
pares, cobertos duas vezes.

Ingestão usa `update_project` (owner e manager) e leitura de mídia usa
`read_project` (qualquer membro). Nenhuma ação nova foi criada para isso: as
concessões seriam idênticas às existentes, e o plano não nomeia `manage_media`.

Rotas endereçadas por sessão de upload não têm `project_id` no caminho, então
`require_upload_action` resolve o projeto a partir da sessão e delega à mesma
função central. A autoridade continua decidida em um só lugar.

## Decisões tomadas

As quatro perguntas em aberto foram fechadas localmente em 2026-09-01, sob
autorização explícita da usuária, com a condição de que o trabalho ficasse em
branch e cada decisão registrasse seu raciocínio. **Continuam sujeitas à revisão
do Meirelles.** Texto completo em `.claude/plans/phase-3.md`.

| Decisão | Escolha | Motivo |
| --- | --- | --- |
| **D1** Raízes de armazenamento | Duas: `DADA_MEDIA_ROOT` e `DADA_UPLOAD_PARTS_ROOT`, absolutas e obrigatoriamente distintas | Cancelar upload purga a raiz de partes inteira. Com uma raiz só, todo cancelamento vira deleção seletiva dentro da árvore de mídia viva — o único lugar onde um erro é irreversível, já que a retenção não tem janela de restauração |
| **D2** Purga síncrona ou por worker | Síncrona, na requisição | Introduzir Celery e `worker_jobs` aqui seria começar trabalho de fase posterior, o que as práticas de trabalho proíbem. O D4 reduz a operação a um `rmtree` só. "Imediata e permanente" lê-se como síncrona |
| **D3** `DELETE /projects/{id}` na Fase 3 | Entregar | O critério de saída do App exige que projetos deletados fiquem imediatamente indisponíveis, e o requisito de purga de projeto é desta fase. Mesmo formato do D1 da Fase 2, cuja resolução já foi aceita e mergeada |
| **D4** Deduplicação global ou por projeto | Por projeto | Dedup global exige contagem de referências cujo modo de falha é apagar bytes de um projeto vivo — perda silenciosa e permanente, sem restauração. Escopo por projeto torna essa classe de bug impossível por construção, e o *reference-safe cleanup* passa a ser trivial. O custo é duplicar bytes quando um dataset alimenta dois projetos, o que é barato em disco local |

### Ordem da purga

Registros do banco commitam primeiro; a árvore de arquivos é removida depois.
Se a remoção falhar, sobram bytes órfãos que nada referencia e nenhuma rota
serve — invisíveis e inofensivos. Na ordem inversa sobraria um projeto listando
imagens que a API não consegue mais entregar. Entre os dois modos de falha,
disco desperdiçado ganha de projeto quebrado. A falha é registrada em nível
`error`, e o teste do critério de saída afirma que o diretório sumiu, de modo
que uma falha silenciosa não passa por sucesso.

### Julgamento registrado: `insufficient_media`

O plano manda recusar ativação "até que classes, mídia e os tamanhos de split
solicitados sejam válidos". Com mídia existindo pela primeira vez, passou a ser
verificável se o split cabe no dataset. Um projeto com menos imagens que
`initial_training_size + test_set_size` reporta `insufficient_media` em
`details.missing`. O código de erro continua sendo `activation_incomplete`; só a
lista de pendências ganhou um nome novo.

## Bugs reais encontrados durante a implementação

Os três foram encontrados pelos testes, não por revisão, e os três eram
alcançáveis em produção.

| Bug | Efeito | Correção |
| --- | --- | --- |
| Caminho relativo com byte NUL chegava ao PostgreSQL | `CharacterNotInRepertoireError` → `500`. Um cliente malicioso derrubava a requisição | Caracteres de controle são removidos antes de persistir o caminho e o nome de um item recusado |
| `UploadItemResponse.model_validate(item)` procurava `reason`, mas o modelo tem `rejection_reason` | **O motivo da recusa nunca chegava ao cliente**: sempre `null` | A resposta é construída explicitamente, como o endpoint de mídia já fazia |
| O validador de settings não resolvia caminhos absolutos | O guarda de contenção comparava formas canônicas diferentes e recusava todo caminho válido quando a raiz vinha por symlink ou short name do Windows | `.resolve()` passou a ser incondicional |

## O que ficou de fora

| Item | Motivo |
| --- | --- |
| Trabalho do App da Fase 3 | Uploader resumível mid-file, chave de idempotência estável, editor de rascunho e gestão de membros. Não faz parte da entrega da API |
| Rota que serve os bytes de uma imagem | O plano lista apenas o inventário de mídia nesta fase. O workspace de anotação é da Fase 5 |
| Congelar split e criar lotes | Fase 4 |
| Volume dedicado no `compose.yaml` | O Compose local sobe apenas `postgres` e `redis`; não há container da API. Localmente as raízes são diretórios do host, e o bind mount pertence ao servidor compartilhado |
| Celery, outbox e `worker_jobs` | Fases posteriores, conforme **D2** |

## Verificação

Executado contra PostgreSQL e Redis reais dos containers do Compose, com o
ambiente conda `dada2` (uv não está instalado nesta máquina).

- `ruff check` e `ruff format --check`: limpos.
- `alembic check`: sem divergência entre o modelo e a migração.
- Migração `20260901_0004` exercitada em upgrade, downgrade e upgrade novamente.
- Testes: **175 aprovados** com `DADA_RUN_INTEGRATION=1`, contra 147 na Fase 2.
- `openapi.json` regenerado de forma determinística: duas exportações seguidas
  produzem bytes idênticos. Foi de 18 para 23 caminhos.
- Armazenamento dos testes isolado em diretório temporário pelo `conftest.py`,
  para que nenhuma execução escreva na árvore do repositório.

### Cobertura do critério de saída

> Uploads sobrevivem a restart da API e todos os casos documentados de
> corrupção, duplicata, offset, checksum, caminho, tamanho, retentativa e
> cancelamento passam contra o armazenamento em volume do servidor
> compartilhado. Cancelamento e deleção de projeto não deixam para trás nenhuma
> mídia legível nem parte temporária de upload.

| Cláusula | Como foi provado |
| --- | --- |
| Sobrevive a restart | Chunk enviado, aplicação recriada com `create_app()`, progresso relido, upload retomado do offset confirmado e concluído |
| Corrupção em trânsito | `X-Chunk-SHA256` divergente devolve `checksum_mismatch` e nenhuma linha de chunk é gravada |
| Corrupção em nível de arquivo | Bytes adulterados com o mesmo tamanho passam pelo checksum do chunk e são pegos no `complete`; a sessão termina `failed` e nenhuma mídia é criada |
| Arquivo que não é imagem | `invalid_image` no `complete` |
| Duplicata | Mesmo conteúdo em dois caminhos gera um `content_object` e duas linhas de `media` |
| `already_present` | Segundo manifesto do mesmo conteúdo não pede upload e ainda assim registra o novo caminho |
| Offset | Chunk fora de ordem devolve `offset_mismatch` com `expected_offset`; reenvio do mesmo chunk no offset conhecido é idempotente |
| Caminho | Absoluto, `..`, caractere de controle e colisão de normalização Unicode, cada um recusado com `invalid_relative_path` |
| Tamanho | Arquivo acima de `max_file_bytes` recusado; manifesto acima de `max_project_files` devolve `too_many_files` |
| Tipo de mídia | `image/gif` recusado com `unsupported_media_type` |
| Retentativa | `Idempotency-Key` repetido em `POST /uploads` e em `complete` devolve a resposta original, e apenas uma mídia é criada |
| Cancelamento | `DELETE /uploads/{id}` remove o diretório de partes e todas as linhas |
| Deleção de projeto | Árvore sob `media_root` removida, e `media`, `content_objects`, `upload_sessions`, `upload_items` e `audit_entries` zerados por cascata |
| Sessão expirada | `upload_session_expired` |
| Autorização | `viewer` e `annotator` recusados no upload; `annotator` lê mídia; `manager` recusado na deleção do projeto |
| Ativação | Sem classes e sem mídia devolve `activation_incomplete` listando ambas; com classes e mídia suficientes, ativa |

Todas as cláusulas do critério da API estão cobertas. O critério do App
permanece **não atendido**, porque o trabalho do App não faz parte desta
entrega.
