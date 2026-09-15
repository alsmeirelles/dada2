# Fase 4: Ativação, Seleções Reprodutíveis, Lotes e Administração de Usuários

Status: API concluída em 2026-09-08 e fluxo de splits ajustado em 2026-09-15.
O trabalho do App **não** faz parte desta entrega.

Plano de referência: [api-implementation-plan.md](../api-implementation-plan.md).
Plano do App: [annotator-disagreement-adaptation-plan.md](../../../dada-app/docs/annotator-disagreement-adaptation-plan.md).
Guia de operação: [development.md](../development.md).
Revisão do fluxo de dados e aderência para aprendizado ativo:
[dataset-split-workflow-review.md](../dataset-split-workflow-review.md).

## Objetivo

A Fase 3 encheu o projeto de imagens, mas nada acontecia com elas: `POST
/activate` apenas validava e devolvia o projeto intacto. A Fase 4 é onde o
projeto deixa de ser *configurado* e passa a ser *trabalhado* — o dataset
congela, as imagens são escolhidas de forma reprodutível, a política de
anotação é fotografada em cada lote e os assignments nascem.

São duas frentes independentes que o plano entrega juntas:

| Frente | O que resolvia |
| --- | --- |
| **A — administração global de usuários** | A única forma de criar uma conta era o comando `bootstrap-admin`. Um administrador não conseguia criar os anotadores que a política de consenso exige, e ninguém trocava a própria senha |
| **B — ativação, seleções e lotes** | A ativação não congelava nada e não gerava trabalho nenhum |

## O que foi implementado

### Persistência

Migrações `20260908_0005` e `20260915_0006`.

| Mudança | Descrição |
| --- | --- |
| `users.version` | Coluna nova. O contrato exige versão otimista em `UserRead` e `UserUpdate` |
| `audit_entries.project_id` | Passou a aceitar `NULL` (ver **D1**) |
| `projects` | Configuração de validação e alternativas percentuais para validação e teste; percentuais são resolvidos na ativação |
| `dataset_splits` | A partição `train`, `validation` ou `test` de cada imagem, escrita uma vez na ativação e nunca atualizada |
| `annotation_batches` | Conjunto selecionado + snapshot da política + proveniência da seleção |
| `annotation_batch_annotators` | O grupo de consenso congelado, ordenado |
| `batch_items` | Uma imagem selecionada dentro de um lote |
| `annotation_assignments` | A obrigação de um anotador anotar um item |

`annotation_assignments` e `annotation_batch_annotators` referenciam `users`
com `ondelete="RESTRICT"`. Isso não é detalhe: é o que transforma "o usuário
tem referências de domínio retidas" numa recusa do próprio banco, e não numa
regra de aplicação que pode divergir do esquema.

### Frente A — rotas

| Rota | Função |
| --- | --- |
| `GET /api/v1/users` | Lista paginada por cursor, com filtro opcional `active` |
| `POST /api/v1/users` | Cria conta; `username_taken` em duplicata |
| `GET /api/v1/users/{id}` | Leitura para edição |
| `PATCH /api/v1/users/{id}` | Atualização versionada de `display_name`, `is_active`, `is_administrator` |
| `POST /api/v1/users/{id}/reset-password` | Redefinição por administrador |
| `DELETE /api/v1/users/{id}` | Remoção terminal, versão via `If-Match` |
| `POST /api/v1/auth/me/password` | Troca da própria senha, para qualquer usuário ativo |

A coleção era `/api/v1/users/` — com barra final e sem paginação. Virou
`/api/v1/users`. Foi verificado que nenhum teste e nenhum módulo do App
consumiam a rota antiga, então a correção não quebrou consumidor algum.

`username` é imutável: ele simplesmente não existe em `UserUpdate`, de modo que
a imutabilidade é uma propriedade do contrato e não uma checagem que alguém
pode esquecer de rodar.

### Frente B — rotas

| Rota | Função |
| --- | --- |
| `POST /api/v1/projects/{id}/activate` | Congela três splits, cria três lotes de cobertura completa e ativa o projeto |
| `GET /api/v1/projects/{id}/batches` | Inventário paginado dos lotes (ver **D7**) |
| `GET /api/v1/projects/{id}/batches/{batch_id}` | Snapshot da política e contagens |
| `PATCH /api/v1/projects/{id}/batches/{batch_id}` | Edita a política enquanto `preparing` |
| `POST /api/v1/projects/{id}/batches/{batch_id}/start` | Congela e gera os assignments |

A ativação executa numa transação só: resolve tamanhos percentuais, congela
`dataset_splits` para todas as imagens, cria os lotes `test`, `validation` e
`initial_training`, copia a política padrão para dentro de cada um e move o
projeto de `draft` para `active`.

Teste é sorteado **primeiro, do dataset inteiro**; validação sai do restante e
treino recebe o que sobrou. Cada lote cobre integralmente o próprio split. A
função `first_acquisition_ready` exige assignments criados e nenhum assignment
`pending` nos três lotes antes da primeira aquisição futura.

### Tamanhos dos splits

Teste e validação aceitam exatamente uma forma de tamanho: contagem absoluta
(`test_set_size`/`validation_set_size`) ou percentual maior que 0 e menor que 100
(`test_set_percentage`/`validation_set_percentage`). O percentual é convertido
com arredondamento para cima sobre o total existente na ativação; a contagem
resultante fica gravada e não é recalculada.

`initial_training_size` continua sendo a capacidade mínima exigida para o
treino. O lote `initial_training` cobre todo o restante do split `train`, pois
as três partições precisam terminar a anotação antes da primeira aquisição.
Clientes anteriores recebem validação padrão de uma imagem; clientes novos
devem informar a escolha explicitamente.

### Seleção reprodutível

`services/selection.py` não toca banco nem HTTP. Recebe uma lista ordenada, um
tamanho e um seed, e devolve a escolha. O lote grava `selection_strategy`,
`selection_seed` e `selection_input_fingerprint` — o digest SHA-256 da entrada
ordenada —, de modo que uma seleção guardada pode ser recomputada e comparada
muito depois.

O seed é gerado pelo servidor, nunca enviado pelo cliente: ele é proveniência,
não um parâmetro de requisição.

A ordem de entrada é `(relative_path, id)`, a mesma que a rota de inventário de
mídia já usa. A entrada da seleção é, portanto, algo que o cliente consegue ler.

### Contagens

`total_items` e `total_assignments` são reportados separadamente porque em modo
consenso uma imagem carrega um assignment por anotador configurado — os dois
números nunca coincidem. `submitted_assignments` existe e vale zero nesta fase;
submissão é da Fase 5.

### Códigos de erro estáveis introduzidos

Frente A: `username_taken`, `user_in_use`, `last_active_administrator`,
`self_administration_change`, `version_conflict` (reaproveitado),
`current_password_incorrect`, `invalid_if_match`.

Frente B: `policy_locked`, `batch_already_started`. `activation_incomplete`,
`project_not_draft` e `invalid_consensus_group` foram reaproveitados das fases
anteriores sem mudança de forma.

### Autorização

Nenhuma ação nova. A matriz continua com 13 ações e 52 pares (ver **D6**).

As rotas `/users` **não** passam pela matriz de projeto: são autoridade global,
guardadas pelo `require_administrator` que já existia. Um `owner` de projeto não
recebe nada globalmente, e há teste afirmando exatamente isso nas seis rotas.

## Decisões tomadas

As sete lacunas encontradas ao ler o código contra o plano foram fechadas
localmente em 2026-09-08, sob autorização explícita da usuária, com a condição
de que o trabalho ficasse em branch e cada decisão registrasse seu raciocínio.
**Continuam sujeitas à revisão do Meirelles.** Texto completo em
`.claude/plans/phase-4.md`.

| Decisão | Escolha | Motivo |
| --- | --- | --- |
| **D1** Onde vive a auditoria global | `audit_entries.project_id` passou a aceitar `NULL` | Um `DROP NOT NULL` numa coluna, e `audit.record` aceita `None`. Nenhum call site existente mudou. Uma segunda tabela duplicaria a forma ator/ação/alvo/antes/depois e criaria dois lugares para procurar "quem mudou isto?" |
| **D2** Como detectar `user_in_use` | Tentar deletar e traduzir o `IntegrityError` | Os `RESTRICT` já existem no esquema. Um levantamento prévio seria uma segunda implementação da mesma regra, que diverge silenciosamente quando uma fase futura adiciona tabela — e as fases futuras adicionam muitas. `add_member` já usa esse padrão para `duplicate_member` |
| **D3** Formato do `If-Match` | Inteiro puro, aspas toleradas. Ausente é `400 invalid_if_match`, divergente é `409 version_conflict` | Nada no repositório usava `If-Match`, então não havia precedente a seguir nem cliente a quebrar. `version_conflict` é o código que projeto e política já devolvem para o mesmo significado |
| **D4** Tabelas `selections`, `iterations`, `model_runs` | Nenhuma das três. A proveniência da seleção vive em colunas do lote | A seleção é 1:1 com o lote nesta fase. Uma iteração não sai de `preparing` sem treino, que é da Fase 7, e uma linha que nunca avança é estado inventado. `model_runs` não tem produtor |
| **D5** Assignments em modo `single` | Um por item, com `annotator_id` nulo | Mantém uma regra só: número de assignments é o número de submissões exigidas. A alternativa daria à Fase 5 dois caminhos para a mesma operação e tornaria "total de assignments" incontável antes de a anotação começar |
| **D6** Ação de autorização para lotes | Nenhuma nova. `read_project` para leitura, `manage_annotation_policy` para `PATCH` e `start` | Mesmo precedente já aceito da Fase 3, que recusou criar `manage_media`: nenhuma ação nova quando as concessões seriam idênticas a uma existente e o plano não a nomeia |
| **D7** `GET /batches` e as rotas de iteração | O inventário de lotes entra; iteração e estatística não | O plano nomeia `GET /batches/{id}` mas nenhuma forma de descobrir um `batch_id`, e o App precisa enumerar os lotes. Por **D4** não existem iterações: uma rota devolvendo coleção sempre vazia mentiria mais que o `404` atual |

### Julgamento registrado: a ordem de `last_active_administrator`

O contrato descreve duas proteções: não deixar a instalação sem administrador
ativo, e não permitir que um administrador retire o próprio acesso. Elas se
sobrepõem, e a ordem em que são checadas decide qual código o cliente vê.

Com `self_administration_change` primeiro, `last_active_administrator` fica
**inalcançável**: o único ator possível é sempre um administrador ativo, então
ou ele é o alvo — e a regra de auto-mudança dispara antes —, ou existe outro
administrador ativo e a contagem nunca chega a zero. Isso foi descoberto por um
teste que falhou, não por revisão.

A ordem foi invertida. Cada regra passou a ter um cenário próprio:

| Situação | Código |
| --- | --- |
| Um administrador só, tentando se rebaixar, desativar ou remover | `last_active_administrator` |
| Dois administradores, um tentando retirar o próprio acesso | `self_administration_change` |
| Dois administradores, um rebaixando o outro | Permitido |

A mensagem mais específica sobre o estado do sistema vem primeiro, que também é
a mais útil para quem recebe a recusa.

### Julgamento registrado: revogação de sessão na deleção

O requisito diz que redefinição de senha, troca de senha, desativação e deleção
revogam as sessões do alvo. Nas três primeiras, `revoke_user_sessions` roda na
mesma transação da mudança. Na deleção, `refresh_sessions.user_id` é `CASCADE`:
as linhas são **removidas**, o que é mais forte que revogá-las. Chamar a
revogação antes de apagar seria código sem efeito observável, então não é
chamado, e o docstring de `delete_user` diz por quê.

## O que ficou de fora

| Item | Motivo |
| --- | --- |
| Lotes de `acquisition` | Precisam de uma iteração e de um modelo treinado. Fase 7. O guard de conclusão das anotações iniciais já existe para o produtor futuro |
| `GET /projects/{id}/iterations` e `/statistics` | Ver **D7**. O App já as chama e recebe `404`; é dívida anterior a esta fase |
| Fila, leases, rascunhos e submissões | Fase 5 |
| Trabalho do App: `/admin/users`, troca de senha e visibilidade de lotes | Fora desta entrega, como na Fase 3 |
| Celery, outbox e `worker_jobs` | Nada nesta fase precisa deles |

## Verificação

O ajuste de 2026-09-15 acrescentou testes para os três splits, resolução de
percentuais e bloqueio da primeira aquisição. Nesta revisão local, os **229
testes** passaram com integração habilitada, lint e formatação ficaram limpos,
a revisão `20260915_0006` foi aplicada, `alembic check` não encontrou
divergência e `openapi.json` foi regenerado.

A entrega original foi executada contra PostgreSQL e Redis reais dos containers
do Compose, com o ambiente conda `dada2` (uv não está instalado nesta máquina).

- `ruff check` e `ruff format --check`: limpos.
- `alembic check`: sem divergência entre o modelo e a migração.
- Migração `20260908_0005` exercitada em upgrade, downgrade e upgrade novamente.
- Testes: **223 aprovados** com `DADA_RUN_INTEGRATION=1`, contra 191 no início
  da fase; 92 aprovados e 131 pulados sem a variável.
- `openapi.json` regenerado de forma determinística: duas exportações seguidas
  produzem bytes idênticos. Foi de 25 para 31 caminhos e de 37 para 44 schemas.

### Cobertura do critério de saída

> A mesma entrada e seed reproduzem a seleção; validação e teste permanecem
> reservados; toda mídia dos três splits entra em um lote inicial; todo item de
> lote de consenso tem exatamente um assignment por anotador snapshotado;
> starts que falham revertem completamente.
> Administradores conseguem criar, atualizar, redefinir, desabilitar e remover
> com segurança usuários elegíveis; todos os usuários trocam a própria senha;
> nenhum não-administrador acessa ações globais de usuário.

| Cláusula | Como foi provado |
| --- | --- |
| Mesma entrada e seed reproduzem a seleção | Teste unitário da função pura: duas chamadas com a mesma entrada ordenada e o mesmo seed devolvem lista idêntica; seed diferente devolve outra; entrada reordenada tem outro fingerprint |
| Três splits fixos | A ativação materializa exatamente uma linha `train`, `validation` ou `test` por mídia e cria um lote de cobertura completa para cada partição |
| Tamanhos percentuais | Percentuais são arredondados para cima, persistidos como contagens na ativação e exercitados junto às alternativas absolutas |
| Barreira da primeira aquisição | O guard permanece falso com assignments pendentes e só libera depois da conclusão de todos os assignments dos três lotes |
| Mídia de teste nunca entra em aquisição | Nenhum `media_id` do split `test` aparece nos itens do lote `initial_training`, e os itens do lote `test` são exatamente o split `test` |
| Um assignment por anotador snapshotado | Um lote em consenso gera um assignment por par `(item, anotador)`, sem duplicatas e cobrindo exatamente o grupo |
| Assignments em modo `single` | Cada item gera um assignment com `annotator_id` nulo |
| Starts que falham revertem completamente | Um membro do grupo removido do projeto depois do snapshot faz o `start` devolver `invalid_consensus_group`, com zero assignments no banco e o lote ainda em `preparing` sem `started_at` |
| Política congela depois do start | `PATCH` num lote `annotating` devolve `policy_locked`; enquanto `preparing`, funciona. Um segundo `start` devolve `batch_already_started` |
| Snapshot é imune à política padrão | Editar o padrão do projeto depois da ativação não muda o modo, o grupo nem o resolver do lote |
| Administradores criam usuários | `201`; username duplicado devolve `username_taken` |
| Administradores atualizam usuários | Versão corrente incrementa; versão velha devolve `version_conflict`; `username` enviado no corpo é ignorado |
| Administradores redefinem senhas | `204`, senha antiga deixa de logar, nova loga, e o refresh emitido antes é recusado |
| Administradores desabilitam usuários | `is_active=false` bloqueia login e recusa o bearer já emitido na próxima requisição |
| Administradores removem usuários com segurança | Usuário sem referência sai com `204`; dono de projeto, autor de auditoria e administrador de bootstrap devolvem `user_in_use` |
| Último administrador protegido | Rebaixar, desativar e remover o único administrador ativo devolvem `last_active_administrator` |
| Auto-administração protegida | Com dois administradores, retirar o próprio acesso devolve `self_administration_change`; rebaixar um par continua permitido |
| Todos trocam a própria senha | Um anotador troca a própria senha; senha atual errada devolve `current_password_incorrect`; o refresh anterior é recusado |
| Nenhum não-administrador acessa ações globais | As seis rotas `/users` devolvem `403` para um usuário que é `owner` de um projeto |
| `If-Match` | Ausente e ilegível devolvem `invalid_if_match`; valor velho devolve `version_conflict`; valor entre aspas é aceito |
| Senhas nunca vazam | O `422` de senha curta não contém o valor enviado, e nenhuma entrada de auditoria carrega senha |
| Matriz de papéis nas rotas de lote | `viewer` lê o lote, mas recebe `403` no `PATCH` e no `start` |
| Isolamento entre projetos | Um `batch_id` de outro projeto devolve `404` |

Todas as cláusulas do critério da API estão cobertas. O critério do App
permanece **não atendido**, porque o trabalho do App não faz parte desta
entrega.
