# Fase 2: Projetos, Membros e Política de Anotação

Status: implementada em 2026-08-26.

Plano de referência: [api-implementation-plan.md](../api-implementation-plan.md).
Plano do App: [annotator-disagreement-adaptation-plan.md](../../../dada-app/docs/annotator-disagreement-adaptation-plan.md).
Guia de operação: [development.md](../development.md).

## Objetivo

A Fase 1 entregou identidade real, mas o projeto ainda não existia: `GET` e
`POST /api/v1/projects` devolviam `501`. A Fase 2 é a primeira em que o
assistente de criação do App conversa com a API de ponta a ponta, e a primeira
que persiste a política de anotação que todas as fases seguintes vão fotografar.

## O que foi implementado

### Persistência

Migração `20260826_0003`.

| Mudança | Descrição |
| --- | --- |
| `project_classes` | Classes ordenadas com cor `#RRGGBB` e versão otimista. Nome e ordem únicos por projeto, garantidos por constraint |
| `annotation_policy_defaults` | Política padrão do projeto: modo, resolver, parâmetros, limiares de revisão e versão. Uma linha por projeto |
| `annotation_policy_annotators` | Grupo de consenso normalizado, com posição explícita para preservar a ordem |
| `audit_entries` | Trilha de auditoria de mudanças de membro e de política |
| `uq_project_single_owner` | Índice único parcial em `project_members (project_id) WHERE role = 'owner'` |

O índice parcial fecha uma lacuna deixada pela Fase 1: a autoridade de projeto é
resolvida apenas por `project_members`, e `Project.owner_id` nunca é consultado.
Sem a linha de membro `owner`, o criador recebia `403` no próprio projeto. Agora
a criação grava projeto, membro dono e política padrão na mesma transação, e o
banco recusa um segundo dono.

### Rotas

| Rota | Função |
| --- | --- |
| `GET /api/v1/projects` | Lista paginada por cursor opaco, restrita ao que o usuário pode ler |
| `POST /api/v1/projects` | Cria o projeto, o membro dono e a política padrão |
| `GET/PATCH /api/v1/projects/{id}` | Leitura e atualização com versão otimista |
| `POST /api/v1/projects/{id}/activate` | Valida pré-requisitos de ativação |
| `GET/POST /api/v1/projects/{id}/classes` | Classes ordenadas |
| `PATCH/DELETE /api/v1/projects/{id}/classes/{class_id}` | Edição versionada e remoção |
| `GET/POST /api/v1/projects/{id}/members` | Membros, adicionados por username |
| `PATCH/DELETE /api/v1/projects/{id}/members/{user_id}` | Troca de papel e remoção |
| `GET/PUT /api/v1/projects/{id}/annotation-policy` | Política padrão versionada |

`GET /api/v1/capabilities` passou a anunciar `supported_annotation_modes` e
`consensus_resolvers` por tarefa.

### Códigos de erro estáveis introduzidos

`version_conflict`, `duplicate_class_name`, `duplicate_display_order`,
`duplicate_member`, `user_not_found`, `sole_owner_protected`,
`invalid_consensus_group`, `unsupported_resolver`, `activation_incomplete`,
`project_not_draft`.

### Autorização

Cinco ações novas entraram na matriz: `manage_annotation_policy`,
`read_annotation_evidence`, `run_resolution`, `adjudicate` e
`read_annotator_performance`. Todas concedidas a `owner` e `manager`, negadas a
`annotator` e `viewer`. A matriz passou de 28 para 48 pares, cobertos duas vezes:
como lógica pura e contra o PostgreSQL real. As três ações que pertencem a fases
posteriores ainda não têm rota; foram definidas agora porque o plano manda
centralizar a matriz completa em um único lugar.

### Bootstrap

`replace-bootstrap-admin` agora pergunta se o administrador anterior deve perder
o status global, conforme a atualização 2.1 registrada na Fase 1. Sem resposta
disponível — execução não interativa ou EOF — a autoridade anterior é mantida,
porque retirar acesso de alguém nunca é o default seguro a presumir. A
idempotência do `bootstrap-admin` normal não mudou.

## Decisões tomadas

| Decisão | Escolha | Motivo |
| --- | --- | --- |
| `POST /activate` na Fase 2 | Entregar a rota, apenas validando | O critério de saída exige que uma ativação incompleta devolva erro estável, o que precisa de uma rota para tentar. A alternativa exigiria inventar um endpoint de prontidão que o plano não menciona. Como não há mídia antes da Fase 3, a rota está correta hoje, não é um stub |
| Identificadores de resolver | Registro único em `services/resolvers.py`, anunciado por `/capabilities` e validado na escrita | O vocabulário final pertence à Fase 6. Uma constante em um lugar só torna a renomeação uma edição mais uma migração. Guardar opaco deixaria salvar política inutilizável que só falharia muito depois |
| Camada `repositories/` | Não introduzida | Toda consulta da fase tem exatamente um chamador. A regra de estilo proíbe camada de abstração "para depois", e o padrão da Fase 1 já funciona. **Pendente de confirmação**, porque o plano nomeia a pasta |
| Forma do `audit_entries` | Mínima: ator, projeto, ação, alvo, `before`/`after` em JSONB, `trace_id`, timestamp | Sem `trace_id` o registro não correlaciona com o log. IP e user-agent ficaram de fora por serem dado pessoal que exigiria política de retenção |
| Momento da escrita de auditoria | Mesma transação da mudança | Uma auditoria que pode se perder enquanto a mudança comita é pior que auditoria nenhuma |
| Transferência de titularidade | Não implementada | O plano pede proteção do dono único, não transferência. Promover outro membro a `owner` ou rebaixar o atual são ambos recusados com `sole_owner_protected` |

## Decisões posteriores registradas

1. **Catálogo provisório de resolver.** `majority_vote`,
   `two_stage_box_fusion` e `two_stage_mask_fusion` são valores provisórios
   persistidos por política e descobertos por capacidades; não são nomes que o
   App possa fixar. A Fase 6 os migrará para os IDs de pipeline
   `cleanlab_multiannotator`, `two_stage_detection_consensus` e
   `two_stage_segmentation_consensus`, respectivamente. `staple` continua uma
   opção de refinamento de segmentação, nunca um resolver de topo.
2. **Contrato transitório de parâmetros.** É fechado e mínimo: o App envia
   `parameters: {}` e pode expor apenas `review_thresholds.agreement`. Schemas,
   defaults e controles avançados por resolver pertencem à Fase 6.
3. **Camada `repositories/`.** Continua pendente de confirmação; ver a tabela
   de decisões acima. Não bloqueia o contrato nem o trabalho da Fase 2 do App.
4. **Ordem de validação da política.** O grupo é validado antes do resolver, de
   modo que um grupo inválido mascara um resolver incompatível. É defensável
   nos dois sentidos e não bloqueia o contrato do App.

## Débito da Fase 1 absorvido

| Item | Situação |
| --- | --- |
| Senha em texto puro no corpo do `422` | Corrigido. O campo `input` do Pydantic é removido de todo erro de validação antes da resposta |
| Idempotência montada por fora do CORS | Corrigido. A ordem agora é Trace, CORS, Idempotência, então respostas de curto-circuito e replays carregam `Access-Control-Allow-Origin` |
| Tipo `role` desatualizado no App | Já corrigido no merge do Meirelles |
| `uv.lock` ausente | Já resolvido no merge do Meirelles |

Continuam abertos: `POST /queue/annotations` devolvendo `200 accepted` sem
persistir nada (a rota é aposentada na Fase 5), o `sub` do JWT sendo o username
mutável, e o registro de idempotência viver fora da transação de negócio.

## O que ficou de fora

| Item | Motivo |
| --- | --- |
| Ativação de verdade: congelar split e criar lotes | Fase 4 |
| `policy_locked` | Depende de lotes com política fotografada, que são da Fase 4 |
| Limites de armazenamento em `/capabilities` | A escolha posterior é armazenamento local em volume persistente configurado; a implementação pertence à Fase 3 |
| Telas de revisão de consenso no App | Fase 6. As rotas existiam apontando para arquivos inexistentes e quebravam o build; foram substituídas por páginas mínimas e honestas |

## Verificação

Executado contra PostgreSQL e Redis reais dos containers do Compose, com o
ambiente conda `dada2` (uv não está instalado nesta máquina).

- `ruff check` e `ruff format --check`: limpos.
- `alembic check`: sem divergência entre o modelo e a migração.
- Migração exercitada em upgrade, downgrade e upgrade novamente.
- Testes: **147 aprovados** com `DADA_RUN_INTEGRATION=1`; 66 aprovados e 81
  ignorados sem essa variável.
- `openapi.json` regenerado de forma determinística: duas exportações seguidas
  produzem bytes idênticos. Ganhou 12 operações novas e 11 schemas.
- App: `npm run lint` limpo, **27 testes** aprovados, `npm run build` verde,
  incluindo as rotas de consenso que antes quebravam a compilação.
- CLI validado de ponta a ponta: criação, reexecução segura, recusa de
  identidade diferente com código de saída 1, e substituição não interativa que
  preserva a autoridade anterior sem travar em prompt.

### Cobertura do critério de saída

| Critério | Como foi provado |
| --- | --- |
| Criar projeto em modo `single` | Requisição HTTP real, incluindo replay por `Idempotency-Key` |
| Criar projeto em modo `consensus` | Requisição HTTP real com grupo validado e política salva |
| Grupos inválidos | Grupo de um, não membro e membro `viewer`, cada um com `invalid_consensus_group` |
| Membros duplicados | Segundo `POST` do mesmo usuário devolve `409 duplicate_member` |
| Membro sem autoridade de anotação | `viewer` no grupo é recusado, com o ID apontado em `details.not_allowed` |
| Versões de política obsoletas | `PUT` com versão antiga devolve `409 version_conflict` |
| Ativação com setup incompleto | `409 activation_incomplete`, listando o que falta |
| Retomada de setup parcial (App) | Testes de unidade do snapshot e da ordem de estágios |
| Conflito `409` de política (App) | `buildPolicyBody` sempre carrega a versão que o chamador acredita ser a atual |
| Matriz de papéis | 48 pares, puros e contra o banco, mais negação por HTTP nas rotas de política |
| Proteção do dono único | Remoção e rebaixamento do dono recusados, e promoção de outro membro a dono também |
| Auditoria | Entradas de membro e de política verificadas no banco, com `trace_id` preenchido |
