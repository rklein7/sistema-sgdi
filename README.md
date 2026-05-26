# SGDI - Sistema de Gestão de Demandas Internas

[![Status: MVP](https://img.shields.io/badge/Status-MVP-blue)](https://github.com)
[![Python](https://img.shields.io/badge/Python-3.8+-green)](https://www.python.org)
[![Flask](https://img.shields.io/badge/Flask-3.x-red)](https://flask.palletsprojects.com)
[![Database](https://img.shields.io/badge/Database-Supabase%20PostgreSQL-teal)](https://supabase.com)

O **SGDI** é uma aplicação web em Flask para registrar, acompanhar, filtrar e comentar demandas internas. O projeto centraliza solicitações por prioridade, solicitante e histórico de comentários, com os indicadores consolidados no painel gerencial.


## Índice

- [Funcionalidades](#funcionalidades)
- [Stack](#stack)
- [Estrutura do Projeto](#estrutura-do-projeto)
- [Como Rodar](#como-rodar)
- [Banco de Dados](#banco-de-dados)
- [Fluxo de Uso](#fluxo-de-uso)
- [Endpoints](#endpoints)
- [Painel Gerencial](#painel-gerencial)
- [Troubleshooting](#troubleshooting)

## Funcionalidades

- Cadastro e login de usuários.
- Senhas armazenadas com hash via Werkzeug.
- Sessão de usuário com Flask sessions.
- Criação de demandas com título, descrição, solicitante e prioridade.
- Prioridades disponíveis: `Alta`, `Média` e `Baixa`.
- Ordenação automática por prioridade e data de criação.
- Edição de demandas apenas pelo usuário que criou a demanda.
- Regra de prioridade na edição: só é permitido manter ou reduzir a prioridade.
- Exclusão de demandas apenas pelo usuário que criou a demanda.
- Confirmação antes de excluir uma demanda.
- Visualização detalhada de cada demanda.
- Comentários por demanda, com autor e data.
- Busca de demandas por título usando comparação case-insensitive.
- Filtros por prioridade e solicitante na tela principal.
- Painel gerencial com indicadores consolidados, filtros avançados e exportações.
- Tema claro/escuro com preferência salva no navegador.
- Layout responsivo com HTML, Jinja2, CSS e JavaScript puro.

## Stack

| Camada | Tecnologia |
| --- | --- |
| Backend | Flask |
| Templates | Jinja2 |
| Estilos | CSS |
| JavaScript | Vanilla JS |
| Banco | Supabase PostgreSQL |
| Autenticação | Flask session + Werkzeug password hash |
| Configuração | python-dotenv |

## Estrutura do Projeto

```text
sistema-sgdi/
├── app.py
├── requirements.txt
├── README.md
├── .gitignore
├── templates/
│   ├── base.html
│   ├── cadastro.html
│   ├── detalhes.html
│   ├── editar.html
│   ├── index.html
│   ├── login.html
│   ├── nova_demanda.html
│   └── gerencial/
│       └── dashboard.html
└── static/
    ├── style.css
    └── theme.js
```

## Como Rodar

### Pré-requisitos

- Python 3.8 ou superior.
- pip.
- Conta e projeto no Supabase.

### Instalação

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

No Windows:

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### Variáveis de Ambiente

Crie um arquivo `.env` na raiz do projeto:

```env
SUPABASE_URL=https://seu-projeto.supabase.co
SUPABASE_KEY=sua-chave-anon-public
SECRET_KEY=troque-por-uma-chave-forte
API_KEYS=minha-chave-interna:health:read
```

Observações:

- O arquivo `.env` não deve ser versionado.
- `SECRET_KEY` deve ser forte e exclusiva por ambiente.
- O projeto atual usa a chave `anon public` do Supabase.
- Para API, configure `API_KEYS` no formato `chave:escopo1,escopo2;outra-chave:*`.
- Opcionalmente, use `id|chave` para rastreio de uso: `integracao-a|minha-chave:demandas:read`.
- Como fallback, `API_KEY` (chave unica) concede acesso com escopo total (`*`).
- Hardening opcional:
  - `API_RATE_LIMIT_MAX_REQUESTS` (padrao: `120`)
  - `API_RATE_LIMIT_WINDOW_SECONDS` (padrao: `60`)

### Executar

```bash
python app.py
```

Acesse:

```text
http://localhost:5000
```

Documentacao Swagger:

```text
http://localhost:5000/api/docs
```

## Banco de Dados

Execute este SQL no editor SQL do Supabase:

```sql
CREATE TABLE usuarios (
  id BIGSERIAL PRIMARY KEY,
  nome TEXT NOT NULL,
  email TEXT UNIQUE NOT NULL,
  senha_hash TEXT NOT NULL,
  cargo TEXT,
  criado_em TIMESTAMP DEFAULT NOW()
);

CREATE TABLE demandas (
  id BIGSERIAL PRIMARY KEY,
  titulo TEXT NOT NULL,
  descricao TEXT,
  solicitante TEXT,
  prioridade TEXT DEFAULT 'Média'
    CHECK (prioridade IN ('Alta', 'Média', 'Baixa')),
  usuario_id BIGINT REFERENCES usuarios(id) ON DELETE CASCADE,
  data_criacao TIMESTAMP DEFAULT NOW()
);

CREATE TABLE comentarios (
  id BIGSERIAL PRIMARY KEY,
  demanda_id BIGINT REFERENCES demandas(id) ON DELETE CASCADE,
  comentario TEXT NOT NULL,
  autor TEXT,
  data TIMESTAMP DEFAULT NOW()
);

CREATE TABLE demanda_eventos (
  id BIGSERIAL PRIMARY KEY,
  demanda_id BIGINT NOT NULL REFERENCES demandas(id) ON DELETE CASCADE,
  tipo TEXT NOT NULL CHECK (tipo IN (
    'criada',
    'status_alterado',
    'prioridade_alterada',
    'assignee_alterado',
    'reaberta'
  )),
  autor_id BIGINT REFERENCES usuarios(id) ON DELETE SET NULL,
  before_data JSONB NOT NULL DEFAULT '{}'::jsonb,
  after_data JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE INDEX idx_demandas_usuario_id ON demandas(usuario_id);
CREATE INDEX idx_demandas_prioridade ON demandas(prioridade);
CREATE INDEX idx_demandas_solicitante ON demandas(solicitante);
CREATE INDEX idx_comentarios_demanda_id ON comentarios(demanda_id);
CREATE INDEX idx_demanda_eventos_demanda_id ON demanda_eventos(demanda_id);
CREATE INDEX idx_demanda_eventos_created_at ON demanda_eventos(created_at DESC);
CREATE INDEX idx_demanda_eventos_demanda_created_at ON demanda_eventos(demanda_id, created_at DESC);
```

Se RLS estiver ativa nas tabelas, inclua policies equivalentes para `demanda_eventos` (ao menos `SELECT` e `INSERT`) para os perfis que já podem ver/alterar demandas; sem isso, o backend com chave anon não conseguirá gravar/ler a trilha de auditoria.

## Fluxo de Uso

1. Acesse `/cadastro` e crie um usuário.
2. Faça login em `/login`.
3. Crie uma demanda em `/nova_demanda`.
4. Acompanhe a lista principal em `/`.
5. Use filtros por prioridade e solicitante.
6. Abra os detalhes de uma demanda para comentar.
7. Se for gerente, acesse `/gerencial/dashboard` para visualizar indicadores consolidados.

## Endpoints

| Método | Rota | Descrição | Login |
| --- | --- | --- | --- |
| GET/POST | `/cadastro` | Cadastro de usuário | Não |
| GET/POST | `/login` | Login de usuário | Não |
| GET | `/logout` | Encerra sessão | Não |
| GET | `/` | Lista demandas, com filtros por prioridade e solicitante | Sim |
| GET/POST | `/nova_demanda` | Cria demanda | Sim |
| GET/POST | `/editar/<id>` | Edita demanda | Sim |
| POST | `/deletar/<id>` | Exclui demanda, apenas se o usuário logado for o criador | Sim |
| GET | `/buscar?q=termo` | Busca demandas por título | Sim |
| GET | `/detalhes/<id>` | Exibe detalhes e comentários | Sim |
| POST | `/adicionar_comentario/<id>` | Adiciona comentário | Sim |
| GET | `/gerencial/dashboard` | Exibe painel gerencial consolidado | Sim (manager) |
| GET | `/gerencial/dashboard/exportar/csv` | Exporta painel gerencial em CSV | Sim (manager) |
| GET | `/gerencial/dashboard/exportar/pdf` | Exporta painel gerencial em PDF | Sim (manager) |
| GET | `/relatorios` | Redirecionamento temporário para `/gerencial/dashboard` | Sim |
| GET | `/api/docs` | Swagger UI da API | Não |
| GET | `/api/v1/health` | Healthcheck protegido por API key (`health:read`) | Não |
| GET | `/api/v1/demandas` | Lista demandas com filtros/paginação (`demandas:read`) | Não |
| GET | `/api/v1/demandas/<id>` | Busca demanda por ID (`demandas:read`) | Não |
| POST | `/api/v1/demandas` | Cria demanda (`demandas:write`) | Não |
| PATCH | `/api/v1/demandas/<id>` | Atualiza demanda (`demandas:write`) | Não |
| DELETE | `/api/v1/demandas/<id>` | Remove demanda (`demandas:write`) | Não |
| GET | `/api/v1/demandas/<id>/comentarios` | Lista comentarios (`demandas:read`) | Não |
| POST | `/api/v1/demandas/<id>/comentarios` | Cria comentario (`demandas:write`) | Não |
| GET | `/api/v1/demandas/<id>/eventos` | Lista trilha de eventos (`demandas:read`) | Não |
| POST | `/api/v1/demandas/lote/status` | Atualiza status em lote (`demandas:write`) | Não |
| GET | `/api/v1/usuarios` | Catálogo restrito de usuários (`usuarios:read`) | Não |

## API v1 - Operação e hardening

- Rate limit básico por API key (janela fixa em memória do processo Flask).
- Atualização best effort de `api_keys.last_used_at` por `key_id`.
- Logs de acesso API no logger e persistência best effort em `api_access_logs`.

SQL recomendado para observabilidade operacional:

```sql
CREATE TABLE api_keys (
  key_id TEXT PRIMARY KEY,
  nome TEXT,
  last_used_at TIMESTAMPTZ
);

CREATE TABLE api_access_logs (
  id BIGSERIAL PRIMARY KEY,
  key_id TEXT,
  endpoint TEXT NOT NULL,
  status INT NOT NULL,
  latency_ms INT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE INDEX idx_api_access_logs_key_id ON api_access_logs(key_id);
CREATE INDEX idx_api_access_logs_created_at ON api_access_logs(created_at DESC);
```

## Painel Gerencial

A página `/gerencial/dashboard` concentra os indicadores da operação:

- Total geral de demandas e resumo por status.
- Demandas por responsável executor.
- Demandas em atraso por SLA.
- Evolução temporal de criadas/finalizadas.
- Filtros por prioridade, status, responsável e período.
- Exportação consolidada em CSV e PDF.

Critério atual de demanda parada:

```text
data atual - data_criacao >= 3 dias
```


## Troubleshooting

### `ModuleNotFoundError: No module named 'flask'`

Instale as dependências:

```bash
pip install -r requirements.txt
```

### Erro com `SUPABASE_URL` ou `SUPABASE_KEY`

Verifique se o `.env` existe e se as variáveis estão preenchidas:

```env
SUPABASE_URL=https://seu-projeto.supabase.co
SUPABASE_KEY=sua-chave-anon-public
SECRET_KEY=troque-por-uma-chave-forte
```

### `relation "usuarios" does not exist`

As tabelas ainda não foram criadas no Supabase. Execute o SQL da seção [Banco de Dados](#banco-de-dados).

### Login sempre falha

Confira se:

- O usuário foi cadastrado.
- O email está correto.
- A senha digitada é a mesma do cadastro.
- As tabelas foram criadas no mesmo projeto Supabase configurado no `.env`.

## Verificação Rápida

Para validar sintaxe Python:

```bash
python -m py_compile app.py
```

Para rodar a aplicação:

```bash
python app.py
```

## Licença

Projeto interno. Defina uma licença antes de publicar este repositório.
