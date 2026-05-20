# SGDI - Sistema de Gestão de Demandas Internas

[![Status: MVP](https://img.shields.io/badge/Status-MVP-blue)](https://github.com)
[![Python](https://img.shields.io/badge/Python-3.8+-green)](https://www.python.org)
[![Flask](https://img.shields.io/badge/Flask-3.x-red)](https://flask.palletsprojects.com)
[![Database](https://img.shields.io/badge/Database-Supabase%20PostgreSQL-teal)](https://supabase.com)

O **SGDI** é uma aplicação web em Flask para registrar, acompanhar, filtrar e comentar demandas internas. O projeto centraliza solicitações por prioridade, solicitante e histórico de comentários, além de oferecer uma tela de relatórios para visualizar a quantidade de demandas por usuário/solicitante.


## Índice

- [Funcionalidades](#funcionalidades)
- [Stack](#stack)
- [Estrutura do Projeto](#estrutura-do-projeto)
- [Como Rodar](#como-rodar)
- [Banco de Dados](#banco-de-dados)
- [Fluxo de Uso](#fluxo-de-uso)
- [Endpoints](#endpoints)
- [Relatórios](#relatórios)
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
- Relatórios por solicitante, com totais por prioridade e demandas paradas.
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
│   └── relatorios.html
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
```

Observações:

- O arquivo `.env` não deve ser versionado.
- `SECRET_KEY` deve ser forte e exclusiva por ambiente.
- O projeto atual usa a chave `anon public` do Supabase.

### Executar

```bash
python app.py
```

Acesse:

```text
http://localhost:5000
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
7. Acesse `/relatorios` para visualizar indicadores por solicitante.

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
| GET | `/relatorios` | Exibe relatórios por solicitante | Sim |

## Relatórios

A página `/relatorios` mostra:

- Total geral de demandas.
- Total de solicitantes.
- Total de demandas paradas.
- Tabela de demandas por solicitante.
- Contagem por prioridade: Alta, Média e Baixa.
- Contagem de demandas paradas por solicitante.
- Filtros por solicitante e prioridade.
- Lista de demandas filtradas.

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
