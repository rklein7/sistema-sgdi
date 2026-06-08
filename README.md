# SGDI - Sistema de Gestão de Demandas Internas

[![Status: MVP](https://img.shields.io/badge/Status-MVP-blue)](https://github.com)
[![Python](https://img.shields.io/badge/Python-3.8+-green)](https://www.python.org)
[![Flask](https://img.shields.io/badge/Flask-3.x-red)](https://flask.palletsprojects.com)
[![Database](https://img.shields.io/badge/Database-Supabase%20PostgreSQL-teal)](https://supabase.com)

O **SGDI** é uma aplicação Flask para registrar, acompanhar, priorizar, comentar e auditar demandas internas. O sistema oferece interface web server-rendered, painel gerencial e API REST v1 protegida por API key.

## Funcionalidades

- Cadastro, login e logout de usuários.
- Senhas armazenadas com hash via Werkzeug.
- Sessão web com Flask sessions, cookie `HttpOnly`, `SameSite=Lax` e `Secure` configurável.
- CSRF em rotas web mutáveis.
- Criação, listagem, busca, edição e exclusão de demandas conforme permissão.
- Filtros por prioridade, status, solicitante, período, responsável e minhas demandas.
- Paginação e ordenação na listagem principal.
- Status: `Aberta`, `Em andamento`, `Parada`, `Finalizada`.
- Prioridades: `Alta`, `Média`, `Baixa`.
- Responsável executor (`assignee_id`).
- Regras de transição de status e permissão por criador, responsável executor ou manager.
- Cálculo de SLA por prioridade e indicadores de atraso/vencimento.
- Comentários com autor textual e `autor_id`.
- Histórico funcional por demanda em `demanda_eventos`.
- Auditoria técnica e de segurança em `audit_logs`.
- API v1 com API key, escopos e rate limit simples.
- Logs operacionais de acesso da API em `api_access_logs` em modo best effort.
- Painel gerencial com indicadores, filtros e exportações CSV/PDF.
- Swagger UI em `/api/docs`.
- Tema claro/escuro com preferência no navegador.

## Stack

| Camada | Tecnologia |
| --- | --- |
| Backend | Flask |
| Templates | Jinja2 |
| Front-end | HTML, CSS e JavaScript puro |
| Banco | Supabase PostgreSQL |
| Client de banco | `supabase-py` |
| Autenticação web | Flask session + Werkzeug password hash |
| Autenticação API | API key com escopos |
| Configuração | `python-dotenv` |
| API docs | Swagger UI + OpenAPI YAML |
| Exportações | CSV e PDF via ReportLab |

## Estrutura Do Projeto

```text
sistema-sgdi/
├── app.py
├── requirements.txt
├── README.md
├── CONTEXTO_GERAL_PROJETO.md
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

## Como Rodar

Pré-requisitos:

- Python 3.8 ou superior.
- `pip`.
- Conta e projeto no Supabase.

Instalação em Linux/macOS:

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Instalação no Windows:

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Variáveis de ambiente em `.env`:

```env
SUPABASE_URL=https://seu-projeto.supabase.co
SUPABASE_KEY=sua-chave-anon-public
SECRET_KEY=troque-por-uma-chave-forte
API_KEYS=minha-integracao|minha-chave:health:read,demandas:read
```

Variáveis relevantes:

- `SUPABASE_URL`: URL do projeto Supabase.
- `SUPABASE_KEY`: chave usada pelo backend para acessar o Supabase.
- `SECRET_KEY`: obrigatória para sessão Flask e CSRF.
- `API_KEYS`: lista no formato `key_id|chave:escopo1,escopo2;outra-chave:*`.
- `API_KEY`: fallback legado; se configurada, concede escopo total (`*`).
- `API_RATE_LIMIT_MAX_REQUESTS`: padrão `120`.
- `API_RATE_LIMIT_WINDOW_SECONDS`: padrão `60`.
- `SESSION_COOKIE_SECURE`: use `true` em HTTPS.
- `FLASK_DEBUG`: use `true` apenas em desenvolvimento.

Executar:

```bash
python app.py
```

Acessos locais:

- Web: `http://localhost:5000`
- Swagger: `http://localhost:5000/api/docs`
- OpenAPI YAML: `http://localhost:5000/api/openapi.yaml`

## Banco De Dados

O projeto usa Supabase PostgreSQL. A migração versionada existente cria apenas `audit_logs`; as demais tabelas precisam existir no Supabase para a aplicação funcionar.

Schema base recomendado:

```sql
CREATE TABLE IF NOT EXISTS usuarios (
  id BIGSERIAL PRIMARY KEY,
  nome TEXT NOT NULL,
  email TEXT UNIQUE NOT NULL,
  senha_hash TEXT NOT NULL,
  cargo TEXT,
  role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'manager')),
  criado_em TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE TABLE IF NOT EXISTS demandas (
  id BIGSERIAL PRIMARY KEY,
  titulo TEXT NOT NULL,
  descricao TEXT NOT NULL,
  solicitante TEXT NOT NULL,
  prioridade TEXT NOT NULL DEFAULT 'Média' CHECK (prioridade IN ('Alta', 'Média', 'Baixa')),
  status TEXT NOT NULL DEFAULT 'Aberta' CHECK (status IN ('Aberta', 'Em andamento', 'Parada', 'Finalizada')),
  usuario_id BIGINT REFERENCES usuarios(id) ON DELETE CASCADE,
  assignee_id BIGINT REFERENCES usuarios(id) ON DELETE SET NULL,
  data_criacao TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
  status_updated_at TIMESTAMPTZ,
  due_date TIMESTAMPTZ,
  resolved_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS comentarios (
  id BIGSERIAL PRIMARY KEY,
  demanda_id BIGINT NOT NULL REFERENCES demandas(id) ON DELETE CASCADE,
  comentario TEXT NOT NULL,
  autor TEXT,
  autor_id BIGINT REFERENCES usuarios(id) ON DELETE SET NULL,
  data TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE TABLE IF NOT EXISTS demanda_eventos (
  id BIGSERIAL PRIMARY KEY,
  demanda_id BIGINT NOT NULL REFERENCES demandas(id) ON DELETE CASCADE,
  tipo TEXT NOT NULL CHECK (tipo IN (
    'criada',
    'status_alterado',
    'status_alterado_lote',
    'prioridade_alterada',
    'assignee_alterado',
    'reaberta'
  )),
  autor_id BIGINT REFERENCES usuarios(id) ON DELETE SET NULL,
  before_data JSONB NOT NULL DEFAULT '{}'::jsonb,
  after_data JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE TABLE IF NOT EXISTS audit_logs (
  id BIGSERIAL PRIMARY KEY,
  event_type TEXT NOT NULL,
  actor_user_id BIGINT REFERENCES usuarios(id) ON DELETE SET NULL,
  actor_type TEXT NOT NULL DEFAULT 'system',
  entity_type TEXT,
  entity_id TEXT,
  route TEXT,
  method TEXT,
  ip_address INET,
  user_agent TEXT,
  status_code INT,
  request_data JSONB NOT NULL DEFAULT '{}'::jsonb,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE TABLE IF NOT EXISTS api_keys (
  key_id TEXT PRIMARY KEY,
  nome TEXT,
  last_used_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS api_access_logs (
  id BIGSERIAL PRIMARY KEY,
  key_id TEXT,
  endpoint TEXT NOT NULL,
  status INT NOT NULL,
  latency_ms INT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE INDEX IF NOT EXISTS idx_demandas_usuario_id ON demandas(usuario_id);
CREATE INDEX IF NOT EXISTS idx_demandas_assignee_id ON demandas(assignee_id);
CREATE INDEX IF NOT EXISTS idx_demandas_prioridade ON demandas(prioridade);
CREATE INDEX IF NOT EXISTS idx_demandas_status ON demandas(status);
CREATE INDEX IF NOT EXISTS idx_demandas_solicitante ON demandas(solicitante);
CREATE INDEX IF NOT EXISTS idx_demandas_due_date ON demandas(due_date);
CREATE INDEX IF NOT EXISTS idx_comentarios_demanda_id ON comentarios(demanda_id);
CREATE INDEX IF NOT EXISTS idx_demanda_eventos_demanda_id ON demanda_eventos(demanda_id);
CREATE INDEX IF NOT EXISTS idx_demanda_eventos_created_at ON demanda_eventos(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_demanda_eventos_demanda_created_at ON demanda_eventos(demanda_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_actor_user_id ON audit_logs(actor_user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_event_type ON audit_logs(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_logs_route_method ON audit_logs(route, method);
CREATE INDEX IF NOT EXISTS idx_audit_logs_entity ON audit_logs(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_api_access_logs_key_id ON api_access_logs(key_id);
CREATE INDEX IF NOT EXISTS idx_api_access_logs_created_at ON api_access_logs(created_at DESC);
```

RLS/policies:

- No estado atual, considere o RLS desativado ou não configurado para as tabelas da aplicação.
- As permissões são aplicadas principalmente no backend Flask.
- Antes de expor a aplicação/API de forma mais ampla, recomenda-se ativar RLS e criar policies explícitas para `usuarios`, `demandas`, `comentarios`, `demanda_eventos`, `audit_logs`, `api_keys` e `api_access_logs`.
- Policies mal configuradas podem impedir a gravação de auditoria e logs operacionais quando o backend usa chave anon.

## Auditoria E Hardening

Estruturas de log:

| Tabela | Finalidade | Exemplos |
| --- | --- | --- |
| `demanda_eventos` | Trilha funcional de uma demanda | criação, status, prioridade, responsável, reabertura |
| `audit_logs` | Auditoria técnica e de segurança | login, logout, CSRF, falhas de API key, ações web/API |
| `api_access_logs` | Observabilidade da API v1 | endpoint, status HTTP, latência, `key_id` |

Eventos funcionais em `demanda_eventos`:

- `criada`
- `status_alterado`
- `status_alterado_lote`
- `prioridade_alterada`
- `assignee_alterado`
- `reaberta`

Eventos técnicos em `audit_logs` incluem:

- `http_request` para métodos mutáveis.
- `user_registered`.
- `login_success` e `login_failure`.
- `logout`.
- `csrf_invalid` e `csrf_missing`.
- `api_auth_failed` e `api_scope_insufficient`.
- Eventos explícitos da API, como criação, atualização e remoção de demanda.
- Eventos web operacionais com sufixo `_web`.

Política de dados sensíveis:

- Não registrar senhas, hashes, tokens, cookies, CSRF tokens, API keys, secrets, emails, CPFs, telefones ou headers de autorização.
- `audit_log_service.py` sanitiza campos sensíveis com `[REDACTED]`.
- `api_key_id` e `key_id` podem ser registrados por serem identificadores não sensíveis.
- Payloads auditados têm limite de profundidade, tamanho de string e quantidade de itens em listas.

## API v1

Autenticação:

- Envie API key via `X-API-Key`.
- Alternativamente, use `Authorization: ApiKey <chave>`.
- Configure escopos em `API_KEYS`.
- Para endpoints de negócio, envie `X-User-Id` e opcionalmente `X-User-Role` (`user` ou `manager`).

Endpoints:

| Método | Rota | Escopo | Descrição |
| --- | --- | --- | --- |
| GET | `/api/v1/health` | `health:read` | Healthcheck autenticado |
| GET | `/api/v1/demandas` | `demandas:read` | Lista demandas com filtros e paginação |
| GET | `/api/v1/demandas/<id>` | `demandas:read` | Busca demanda por ID |
| POST | `/api/v1/demandas` | `demandas:write` | Cria demanda |
| PATCH | `/api/v1/demandas/<id>` | `demandas:write` | Atualiza campos permitidos |
| DELETE | `/api/v1/demandas/<id>` | `demandas:write` | Remove demanda |
| GET | `/api/v1/demandas/<id>/comentarios` | `demandas:read` | Lista comentários |
| POST | `/api/v1/demandas/<id>/comentarios` | `demandas:write` | Cria comentário |
| GET | `/api/v1/demandas/<id>/eventos` | `demandas:read` | Lista histórico funcional |
| POST | `/api/v1/demandas/lote/status` | `demandas:write` | Atualiza status em lote |
| GET | `/api/v1/usuarios` | `usuarios:read` | Lista catálogo restrito de usuários |

Filtros de `GET /api/v1/demandas`:

- `prioridade`
- `solicitante`
- `status`
- `data_inicio`
- `data_fim`
- `assignee_id`
- `minhas_demandas=1`
- `sort_by=updated_at|prioridade|due_date|data_criacao`
- `sort_dir=asc|desc`
- `page`
- `per_page` até 50

Exemplo:

```bash
curl -H "X-API-Key: minha-chave" \
  -H "X-User-Id: 1" \
  -H "X-User-Role: manager" \
  "http://localhost:5000/api/v1/demandas?status=Aberta&page=1&per_page=10"
```

Limitação atual: a API key autentica a integração, mas `X-User-Id`/`X-User-Role` ainda definem a identidade de negócio. Para uso externo maduro, vincule a API key a um ator/usuário permitido no backend.

## Rotas Web Principais

| Método | Rota | Descrição | Proteção |
| --- | --- | --- | --- |
| GET/POST | `/cadastro` | Cadastro de usuário | Pública |
| GET/POST | `/login` | Login | Pública |
| GET | `/logout` | Encerra sessão | Sessão |
| GET | `/` | Lista demandas | Sessão |
| POST | `/demandas/lote/status` | Atualiza status em lote | Sessão |
| GET/POST | `/nova_demanda` | Cria demanda | Sessão |
| GET/POST | `/editar/<id>` | Edita demanda | Sessão |
| POST | `/deletar/<id>` | Exclui demanda | Sessão |
| GET | `/buscar` | Busca por título | Sessão |
| GET | `/detalhes/<id>` | Detalhe, comentários e histórico | Sessão |
| POST | `/adicionar_comentario/<id>` | Adiciona comentário | Sessão |
| GET | `/gerencial/dashboard` | Painel gerencial | Manager |
| GET | `/gerencial/dashboard/exportar/csv` | Exporta CSV | Manager |
| GET | `/gerencial/dashboard/exportar/pdf` | Exporta PDF | Manager |
| GET | `/dashboard` | Redireciona para painel | Sessão |
| GET | `/relatorios` | Redireciona para painel | Sessão |

## Limitações Técnicas

- `routes/web.py` ainda concentra muita lógica de apresentação, filtros e exportações.
- O schema completo do banco ainda não está todo versionado em migrations.
- Rate limit da API é em memória e não funciona de forma distribuída entre múltiplos processos.
- Identidade de negócio da API ainda depende de headers informados pelo cliente.
- O client Supabase é instanciado globalmente em alguns módulos.
- Não há suíte automatizada de testes no repositório.
- Persistência de `api_keys.last_used_at` e `api_access_logs` é best effort.

## Verificação Rápida

Validar sintaxe dos módulos relevantes:

```bash
python -m compileall app.py auth core repositories routes services
```

Validar um arquivo isolado:

```bash
python -m py_compile app.py
```

Verificar se a aplicação inicia:

```bash
python app.py
```

Testar healthcheck da API:

```bash
curl -H "X-API-Key: minha-chave" http://localhost:5000/api/v1/health
```

## Troubleshooting

### `ModuleNotFoundError: No module named 'flask'`

Instale as dependências:

```bash
pip install -r requirements.txt
```

### Erro Com `SECRET_KEY`

Defina `SECRET_KEY` no `.env`. A aplicação falha no bootstrap quando essa variável está ausente.

### Erro Com `SUPABASE_URL` Ou `SUPABASE_KEY`

Confirme se o `.env` existe e se as variáveis apontam para o projeto Supabase correto.

### `relation "usuarios" does not exist`

Crie as tabelas da seção [Banco De Dados](#banco-de-dados) no Supabase.

### API Retorna `401`

Verifique se a chave foi configurada em `API_KEYS` ou `API_KEY` e se está sendo enviada por `X-API-Key` ou `Authorization: ApiKey <chave>`.

### API Retorna `403`

Verifique se a API key possui o escopo exigido pelo endpoint.

## Licença

Projeto interno. Defina uma licença antes de publicar este repositório.
