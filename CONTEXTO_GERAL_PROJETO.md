# Contexto Geral do Projeto SGDI

## Visão Geral

O **SGDI (Sistema de Gestão de Demandas Internas)** é uma aplicação Flask para registrar, acompanhar, priorizar, comentar e auditar demandas internas.

O projeto possui dois canais principais:

- Interface web server-rendered com Jinja2 para operação interna.
- API REST v1 com autenticação por API key para integrações.

As regras de negócio e persistência foram parcialmente separadas em camadas, mas ainda há lógica de orquestração relevante nas rotas, principalmente em `routes/web.py`.

## Objetivo Do Sistema

- Centralizar demandas internas.
- Permitir cadastro, login e operação por usuário autenticado.
- Acompanhar status, prioridade, responsável executor e SLA.
- Registrar comentários e histórico funcional por demanda.
- Registrar auditoria técnica e de segurança.
- Expor dados operacionais por API v1 documentada em OpenAPI.
- Consolidar indicadores em painel gerencial com exportações.

## Stack Atual

| Camada | Tecnologia |
| --- | --- |
| Backend | Flask |
| Templates | Jinja2 |
| Front-end | HTML, CSS e JavaScript puro |
| Banco | Supabase PostgreSQL |
| Client de banco | `supabase-py` |
| Auth web | Flask session + Werkzeug password hash |
| Auth API | API key com escopos |
| Configuração | `python-dotenv` |
| Docs API | Swagger UI + OpenAPI YAML |
| Exportações | CSV e PDF via ReportLab |

## Estrutura Atual

```text
sistema-sgdi/
├── app.py
├── CONTEXTO_GERAL_PROJETO.md
├── README.md
├── requirements.txt
├── auth/
│   ├── api_key_auth.py
│   └── session_auth.py
├── core/
│   ├── config.py
│   ├── dtos.py
│   └── errors.py
├── openapi/
│   └── openapi.yaml
├── repositories/
│   ├── audit_logs_repository.py
│   ├── comentarios_repository.py
│   ├── demandas_repository.py
│   ├── eventos_repository.py
│   └── usuarios_repository.py
├── routes/
│   ├── api_docs.py
│   ├── api_v1.py
│   └── web.py
├── services/
│   ├── audit_log_service.py
│   ├── auditoria_service.py
│   ├── authz_service.py
│   ├── comentarios_service.py
│   └── demandas_service.py
├── static/
│   ├── style.css
│   └── theme.js
├── supabase/
│   └── migrations/
│       └── 20260608000000_create_audit_logs.sql
└── templates/
    ├── base.html
    ├── cadastro.html
    ├── detalhes.html
    ├── editar.html
    ├── index.html
    ├── login.html
    ├── nova_demanda.html
    └── gerencial/
        └── dashboard.html
```

## Arquitetura Por Camadas

### `app.py`

`app.py` é o ponto de bootstrap da aplicação e deve permanecer pequeno.

Responsabilidades atuais:

- Criar a instância Flask.
- Aplicar configuração central via `core.config.configure_flask_app`.
- Carregar e normalizar API keys via `auth.api_key_auth.configure_api_keys`.
- Registrar logging operacional da API via `register_api_access_logging`.
- Registrar auditoria HTTP técnica via `services.audit_log_service.register_audit_logging`.
- Registrar handlers de autenticação/sessão/CSRF via `auth.session_auth.register_auth_handlers`.
- Registrar os blueprints `web_bp`, `api_v1_bp` e `api_docs_bp`.
- Iniciar o servidor local quando executado diretamente.

Responsabilidades que **não** devem voltar para `app.py`:

- Regras de negócio de demanda, status, SLA ou auditoria.
- Queries Supabase.
- Renderização de páginas específicas.
- Validação detalhada de payloads da API.
- Serialização de respostas.

### `routes/`

Camada HTTP. Recebe requests, valida entradas de rota/form/payload, chama services/repositories e monta respostas.

- `web.py`: rotas HTML, painel gerencial, exportações, filtros, paginação e orquestração dos fluxos web.
- `api_v1.py`: endpoints REST JSON, validação de payloads, paginação, autorização por ator e envelopes de resposta.
- `api_docs.py`: entrega do Swagger UI e do arquivo `openapi/openapi.yaml`.

### `services/`

Camada de regra de negócio e serviços transversais.

- `audit_log_service.py`: auditoria técnica/segurança, sanitização de dados sensíveis, montagem de logs HTTP, eventos de segurança e eventos explícitos da API.
- `auditoria_service.py`: histórico funcional de demandas em `demanda_eventos`.
- `authz_service.py`: permissões por usuário/papel e transições válidas de status.
- `comentarios_service.py`: criação e listagem de comentários de demanda.
- `demandas_service.py`: constantes de prioridade/status, cálculo de SLA, montagem de dados de criação e aplicação de mudanças de status/prioridade.

### `repositories/`

Camada de acesso ao Supabase. Deve concentrar queries e operações diretas nas tabelas.

- `audit_logs_repository.py`: inserção em `audit_logs`.
- `comentarios_repository.py`: listagem e inserção em `comentarios`.
- `demandas_repository.py`: listagem paginada, filtros, busca, criação, atualização e remoção de demandas.
- `eventos_repository.py`: inserção e listagem de `demanda_eventos`.
- `usuarios_repository.py`: busca por email, validação de email existente, criação e listagem resumida de usuários.

### `core/`

Infraestrutura transversal.

- `config.py`: carregamento de `.env`, configuração Flask e criação do client Supabase.
- `dtos.py`: serialização de entidades para a API.
- `errors.py`: envelopes padrão de sucesso/erro e handlers de erro da API.

### `auth/`

Autenticação e proteção por canal.

- `session_auth.py`: sessão web, `login_required`, `manager_required`, CSRF e contexto de sessão.
- `api_key_auth.py`: API key, escopos, rate limit em memória, `last_used_at` best effort e log de acesso da API.

## Módulo Web

Funcionalidades atuais:

- Cadastro, login e logout.
- Sessão com duração configurada e cookies endurecidos.
- CSRF para rotas web mutáveis.
- Listagem de demandas com filtros, ordenação e paginação.
- Criação, edição e exclusão de demandas conforme permissão.
- Atualização individual e em lote de status.
- Responsável executor (`assignee_id`).
- Comentários por demanda.
- Histórico funcional na tela de detalhes.
- Painel gerencial com filtros, indicadores e exportações CSV/PDF.
- Tema claro/escuro via JavaScript local.

Regras principais:

- `user` gerencia demandas que criou; status também pode ser alterado pelo responsável executor.
- `manager` tem acesso ampliado a operações gerenciais.
- Status válidos: `Aberta`, `Em andamento`, `Parada`, `Finalizada`.
- Transições válidas ficam em `authz_service.STATUS_TRANSITIONS`.
- Prioridades válidas: `Alta`, `Média`, `Baixa`.
- SLA atual por prioridade: Alta 2 dias, Média 5 dias, Baixa 10 dias.

## API REST v1

Documentação:

- Swagger UI: `/api/docs`
- OpenAPI YAML: `/api/openapi.yaml`

Endpoints atuais:

| Método | Rota | Escopo |
| --- | --- | --- |
| GET | `/api/v1/health` | `health:read` |
| GET | `/api/v1/demandas` | `demandas:read` |
| GET | `/api/v1/demandas/<id>` | `demandas:read` |
| POST | `/api/v1/demandas` | `demandas:write` |
| PATCH | `/api/v1/demandas/<id>` | `demandas:write` |
| DELETE | `/api/v1/demandas/<id>` | `demandas:write` |
| GET | `/api/v1/demandas/<id>/comentarios` | `demandas:read` |
| POST | `/api/v1/demandas/<id>/comentarios` | `demandas:write` |
| GET | `/api/v1/demandas/<id>/eventos` | `demandas:read` |
| POST | `/api/v1/demandas/lote/status` | `demandas:write` |
| GET | `/api/v1/usuarios` | `usuarios:read` |

Contrato geral de sucesso:

```json
{
  "success": true,
  "message": "ok",
  "data": {},
  "error": null,
  "meta": {
    "timestamp": "2026-01-01T12:00:00+00:00"
  }
}
```

Contrato geral de erro:

```json
{
  "success": false,
  "message": "Nao autorizado.",
  "data": null,
  "error": {
    "code": "UNAUTHORIZED",
    "details": {}
  },
  "meta": {
    "timestamp": "2026-01-01T12:00:00+00:00"
  }
}
```

Observação crítica: a API autentica a integração por API key, mas a identidade de negócio ainda é informada por `X-User-Id` e `X-User-Role`. Isso é aceitável para MVP controlado, mas é frágil para exposição externa ampla.

## Auditoria E Comentários

O projeto separa três tipos de registro:

| Estrutura | Finalidade | Onde é usada |
| --- | --- | --- |
| `demanda_eventos` | Histórico funcional da demanda | detalhes da demanda e API de eventos |
| `audit_logs` | Auditoria técnica e de segurança | login, logout, CSRF, ações web/API e requests mutáveis |
| `api_access_logs` | Observabilidade operacional da API | endpoint, status, latência e `key_id` |

Eventos funcionais em `demanda_eventos`:

- `criada`
- `status_alterado`
- `status_alterado_lote`
- `prioridade_alterada`
- `assignee_alterado`
- `reaberta`

Eventos técnicos e de segurança em `audit_logs` incluem:

- `http_request` para métodos `POST`, `PUT`, `PATCH` e `DELETE`.
- `user_registered`.
- `login_success` e `login_failure`.
- `logout`.
- `csrf_invalid` e `csrf_missing`.
- `api_auth_failed`.
- `api_scope_insufficient`.
- Eventos explícitos da API como `api_demanda_criada`, `api_demanda_atualizada` e `api_demanda_removida`.
- Eventos web operacionais com sufixo `_web`.

Política de hardening dos logs:

- Não registrar senhas, hashes, tokens, cookies, CSRF tokens, API keys, secrets, emails, CPFs, telefones ou headers de autorização.
- Sanitizar campos sensíveis com `[REDACTED]` em `request_data` e `metadata`.
- Permitir identificadores não sensíveis como `api_key_id` e `key_id` para rastreabilidade.
- Truncar strings grandes e limitar profundidade/listas no payload auditado.
- Registrar o mínimo necessário para investigação e operação.

Comentários:

- São persistidos em `comentarios`.
- Têm `demanda_id`, texto, autor textual e `autor_id`.
- São exibidos no detalhe da demanda e expostos pela API v1.

## Banco De Dados

Banco atual: Supabase PostgreSQL acessado diretamente pelo backend via `supabase-py`.

Tabelas usadas pelo código:

- `usuarios`: usuários web, senha com hash, cargo e papel (`role`).
- `demandas`: dados principais da demanda, status, SLA, responsável executor e timestamps.
- `comentarios`: comentários vinculados à demanda.
- `demanda_eventos`: histórico funcional por demanda.
- `audit_logs`: auditoria técnica e de segurança.
- `api_keys`: tabela opcional/operacional para `last_used_at` por `key_id`.
- `api_access_logs`: logs operacionais da API v1.

Campos relevantes esperados pelo código:

- `usuarios`: `id`, `nome`, `email`, `senha_hash`, `cargo`, `role`, `criado_em`.
- `demandas`: `id`, `titulo`, `descricao`, `solicitante`, `prioridade`, `status`, `usuario_id`, `assignee_id`, `data_criacao`, `updated_at`, `status_updated_at`, `due_date`, `resolved_at`.
- `comentarios`: `id`, `demanda_id`, `comentario`, `autor`, `autor_id`, `data`.
- `demanda_eventos`: `id`, `demanda_id`, `tipo`, `autor_id`, `before_data`, `after_data`, `created_at`.
- `audit_logs`: `id`, `event_type`, `actor_user_id`, `actor_type`, `entity_type`, `entity_id`, `route`, `method`, `ip_address`, `user_agent`, `status_code`, `request_data`, `metadata`, `created_at`.
- `api_keys`: `key_id`, `nome`, `last_used_at`.
- `api_access_logs`: `id`, `key_id`, `endpoint`, `status`, `latency_ms`, `created_at`.

Migrações versionadas no repositório:

- `supabase/migrations/20260608000000_create_audit_logs.sql` cria apenas `audit_logs` e índices relacionados.

Ponto de atenção: o schema completo de `usuarios`, `demandas`, `comentarios`, `demanda_eventos`, `api_keys` e `api_access_logs` ainda está documentado no README, mas não está totalmente versionado em migrações Supabase neste repositório.

### RLS E Policies

No estado atual, o RLS do Supabase deve ser considerado desativado ou não configurado para as tabelas da aplicação. As permissões são aplicadas principalmente no backend Flask.

Recomendação: antes de exposição externa madura, ativar RLS e criar policies explícitas para as tabelas principais e de auditoria. As policies devem preservar os fluxos autorizados de leitura/escrita em `demanda_eventos`, `audit_logs` e `api_access_logs`; caso contrário, o backend com chave anon pode perder capacidade de auditoria.

## Limitações Técnicas Atuais

- `routes/web.py` ainda é grande e concentra lógica de apresentação, filtros, exportações e agregações gerenciais.
- A identidade da API depende de `X-User-Id` e `X-User-Role`, sem vínculo forte com a API key.
- Rate limit da API é em memória do processo, não distribuído.
- O client Supabase é criado globalmente em alguns módulos, dificultando testes isolados e injeção de dependência.
- O schema completo do banco não está totalmente versionado em migrações.
- RLS/policies ainda não estão modelados/aplicados no repositório.
- Não há suíte automatizada de testes no estado atual do repositório.
- A persistência de `api_keys.last_used_at` e `api_access_logs` é best effort; falhas são toleradas para não bloquear a API.
- A API v1 ainda não implementa autenticação forte de usuário final ou assinatura de requests.

## Próximos Passos Recomendados

Curto prazo:

- Versionar em migrations o schema completo usado pela aplicação.
- Criar checklist de smoke test web/API.
- Adicionar testes automatizados para `services/`, `auth/` e validações da API.
- Manter a política de sanitização de logs em qualquer novo evento.
- Revisar `openapi/openapi.yaml` sempre que endpoints ou payloads mudarem.

Médio prazo:

- Reduzir `routes/web.py`, movendo agregações gerenciais e validações reutilizáveis para services.
- Fortalecer a identidade da API, vinculando API key a ator técnico, tenant ou usuário permitido.
- Substituir rate limit em memória por backend compartilhado quando houver múltiplos processos/instâncias.
- Criar matriz de permissões e RLS para Supabase.
- Introduzir fixtures/mocks do Supabase para testes sem banco real.

Longo prazo:

- Ativar RLS gradualmente com policies por papel, ownership e fluxos técnicos de auditoria.
- Implementar rotação/revogação de API keys persistida em banco.
- Evoluir integrações externas com webhooks e observabilidade estruturada.
- Separar domínios maiores em módulos mais testáveis conforme o produto crescer.

## Fonte De Verdade

Se houver divergência entre este documento, o README e o comportamento observado, o código atual e `openapi/openapi.yaml` devem ser tratados como fonte principal de verdade.
