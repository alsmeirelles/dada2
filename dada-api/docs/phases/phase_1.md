# Fase 1: Identidade, Capacidades e Autorização

Status: implementada em 2026-08-12.

Plano de referência: [api-implementation-plan.md](../api-implementation-plan.md).
Guia de operação: [development.md](../development.md).

## Objetivo

A Fase 0 entregou a fundação do serviço (configuração, banco, erros, tracing,
idempotência, health) sem nenhum comportamento de domínio. A Fase 1 é a
primeira que entrega identidade real: um jeito de criar o primeiro
administrador, sessões que podem ser renovadas e revogadas de verdade, e um
único lugar que decide quem pode o quê.

## O que foi implementado

### Persistência

Migração `20260812_0002`.

| Mudança | Descrição |
| --- | --- |
| `users.role` vira `users.is_administrator` | Autoridade global passa a ser um booleano. A migração converte quem tinha `role='admin'` para `is_administrator=true` e remove o tipo `user_role` do PostgreSQL |
| `refresh_sessions` | Sessões de refresh. Guarda o hash do token, nunca o token. O campo `family_id` agrupa a linhagem de rotação |
| `bootstrap_records` | Registro único do administrador inicial, com restrição `CHECK (id = 1)` no banco |
| `projects` e `project_members` | Persistência mínima para que a autorização por papel seja verificável |

### Bootstrap do administrador

Um banco recém migrado não tem usuário nenhum e nenhuma rota HTTP capaz de
criar o primeiro. O administrador inicial é criado por linha de comando:

- `dada-api bootstrap-admin` (também disponível como `make bootstrap-admin`)
- `dada-api replace-bootstrap-admin` para trocar a identidade de bootstrap

Comportamento:

- Lê `DADA_SEED_ADMIN_USERNAME`, `DADA_SEED_ADMIN_DISPLAY_NAME` e
  `DADA_SEED_ADMIN_PASSWORD`. O que faltar é perguntado interativamente, com a
  senha lida sem eco.
- Senha hasheada com Argon2. O texto puro nunca é gravado nem registrado em log.
- Rerodar com a mesma identidade não faz nada e preserva o hash existente.
- Rerodar com identidade diferente é recusado com código de saída diferente de
  zero, em vez de adivinhar a intenção.
- A inicialização normal da API não cria nem redefine credenciais.

### Sessões

| Rota | Função |
| --- | --- |
| `POST /api/v1/auth/token` | Login. Retorna o token de acesso e define o cookie de refresh |
| `POST /api/v1/auth/refresh` | Rotaciona a credencial e devolve novo token de acesso |
| `POST /api/v1/auth/logout` | Revoga a sessão |

A rotação é de uso único. Apresentar uma credencial já rotacionada é tratado
como replay: a requisição falha com `refresh_token_replayed` e todas as
credenciais daquela família são revogadas.

O cookie é `HttpOnly`, `SameSite`, restrito ao caminho `/api/v1/auth` e
`Secure` por padrão.

### Autorização

Dois níveis distintos:

- Autoridade global: o campo `is_administrator` no usuário.
- Autoridade por projeto: os papéis `owner`, `manager`, `annotator` e `viewer`,
  vindos da associação do usuário ao projeto.

Toda decisão de projeto passa por uma única função em
`dada_api/services/authorization.py`. Nenhuma rota decide sozinha. O
administrador global passa em qualquer verificação com autoridade equivalente à
de dono, e o campo `owner_id` continua registrando o criador verdadeiro.

## Decisões tomadas

| Decisão | Escolha | Motivo |
| --- | --- | --- |
| Docstrings | Manter o padrão do `PROJECT.md`: Google style em todas as classes e funções | Já é a convenção documentada e seguida por todo o código existente |
| Alcance da autorização na Fase 1 | Criar a persistência mínima de projeto e associação | O critério de saída exige provar negação por papel em requisições HTTP reais, o que não é possível sem projeto no banco |
| Representação do administrador global | Substituir o enum `role` por `is_administrator` | Com papéis por projeto existindo, um papel global chamado "annotator" perde sentido. Manter os dois criaria duas fontes de verdade para a mesma autoridade |
| Variáveis do bootstrap | Reaproveitar `DADA_SEED_ADMIN_USERNAME` e `DADA_SEED_ADMIN_PASSWORD`, criando apenas `DADA_SEED_ADMIN_DISPLAY_NAME` | Já existiam e não eram lidas por nada. Criar nomes novos duplicaria configuração |
| `DADA_SEED_SERVICE_*` | Mantidas como estão | Não são usadas hoje, mas não há como afirmar que não serão usadas depois. Remover seria uma decisão sem respaldo |
| Escopo do event loop nos testes | `session` | O engine do SQLAlchemy é um singleton de módulo, então suas conexões precisam viver em um único event loop durante toda a suíte |

## Pontos que ainda precisam de revisão

Estes foram implementados de uma forma defensável, mas o plano não os define de
forma explícita. Valem uma confirmação.

1. **Matriz de ações por papel.** O plano pede cobertura de todo par papel e
   ação, mas não lista as ações. Apenas `revoke_lease` (owner e manager) está
   escrito na documentação. As outras seis ações foram derivadas do propósito
   evidente de cada papel.

   - 1.1 Atualização: O mapeamento de ações por papel é definido no módulo dada_api.services.authorization.ROLE_ACTIONS 
2. **Efeito do `replace-bootstrap-admin` sobre o administrador anterior.** A
   escolha foi não destrutiva: a conta antiga continua existindo e continua
   administradora. Retirar acesso de alguém é um ato deliberado e separado.

   - 2.1 Atualização: ao executar replace-bootstrap-admin questionar o usuário se o administrador anterior deve ser removido e remover o status de administrador da conta.
3. **Formato de `GET /api/v1/auth/me`.** O campo `role` foi substituído por
   `is_administrator`, consequência direta da decisão sobre autoridade global.
   O tipo correspondente no dada-app ficou desatualizado, embora nada quebre em
   execução porque o app não lê esse campo.

   - 3.1 Atualização: a correção em dada-app deve ser realizada

## O que ficou de fora

| Item | Motivo |
| --- | --- |
| Limites de armazenamento em `/api/v1/capabilities` | A escolha foi feita depois da Fase 1: a Fase 3 implementará armazenamento local em volume persistente configurado |
| Ajustes no dada-app | Fora da fronteira deste plano, que trata apenas da API |
| Rotas de projeto além da leitura | Pertencem à Fase 2 |

## Verificação

Executado contra PostgreSQL e Redis reais dos containers do Compose.

- `ruff check` e `ruff format --check`: limpos.
- `alembic check`: sem divergência entre o modelo e a migração.
- Migração exercitada em upgrade, downgrade e upgrade novamente, preservando os
  administradores existentes na ida e na volta.
- Testes: 85 aprovados com `DADA_RUN_INTEGRATION=1`, e 40 aprovados com 45
  ignorados sem essa variável.
- `openapi.json` regenerado de forma determinística. Ganhou
  `/api/v1/auth/refresh`, `/api/v1/auth/logout` e
  `/api/v1/projects/{project_id}`.
- Bootstrap validado de ponta a ponta em um banco vazio separado: criação,
  reexecução segura, recusa de identidade diferente e substituição explícita.

### Cobertura do critério de saída

| Critério | Como foi provado |
| --- | --- |
| Instalação vazia migrada e com bootstrap sem endpoint HTTP | Comando executado em banco limpo, mais teste automatizado |
| Reexecução do bootstrap é segura | Teste confirma que o hash da senha não muda |
| Login | Requisição HTTP real |
| Rotação e rejeição de replay | Requisição HTTP real, incluindo a revogação da família |
| Logout | Requisição HTTP real |
| Expiração | Token de acesso e credencial de refresh expirados, ambos rejeitados |
| CORS | Preflight da origem configurada, teste herdado da Fase 0 |
| Acesso de administrador | Administrador entra, usuário comum recebe 403 |
| Negação por papel de projeto | Não membro recebe 403 por HTTP. As 28 combinações de papel e ação são cobertas duas vezes: como lógica pura e contra o banco real |

Observação: existe apenas uma rota de projeto nesta fase, então a matriz
completa de papéis não é exercitada inteiramente por HTTP. A Fase 2, ao criar
as demais rotas, deve estender essa cobertura.
