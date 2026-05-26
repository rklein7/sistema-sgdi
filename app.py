import csv
import io
import os
import secrets
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from functools import wraps
from urllib.parse import urlencode

from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    session,
)
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from supabase import Client, create_client
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()

app = Flask(__name__)


def _env_to_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y", "on"}


secret_key = os.environ.get("SECRET_KEY")
if not secret_key:
    raise RuntimeError(
        "SECRET_KEY is obrigatoria. Defina a variavel de ambiente SECRET_KEY."
    )

app.config["SECRET_KEY"] = secret_key
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = _env_to_bool(
    os.environ.get("SESSION_COOKIE_SECURE")
)
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

PRIORIDADES_VALIDAS = ["Alta", "Média", "Baixa"]
ORDEM_PRIORIDADE = {"Alta": 1, "Média": 2, "Baixa": 3}
SLA_DIAS_POR_PRIORIDADE = {"Alta": 2, "Média": 5, "Baixa": 10}
STATUS_DEMANDA_VALIDOS = ["Aberta", "Em andamento", "Parada", "Finalizada"]
STATUS_TRANSITIONS = {
    "Aberta": {"Em andamento", "Parada"},
    "Em andamento": {"Parada", "Finalizada"},
    "Parada": {"Em andamento", "Finalizada"},
    "Finalizada": {"Aberta"},
}
DIAS_PARADA = 3  # configurável
ORDENACOES_LISTAGEM = {
    "updated_at": "updated_at",
    "prioridade": "prioridade",
    "due_date": "due_date",
}
ORDENS_DIRECAO = {"asc", "desc"}
ITENS_POR_PAGINA_PADRAO = 12
ITENS_POR_PAGINA_MAX = 50


# ---------------------------------------------------------------------------
# Helpers de domínio
# ---------------------------------------------------------------------------


def _parse_iso_datetime(data_str):
    if not data_str:
        return None

    try:
        return datetime.fromisoformat(data_str.replace("Z", "+00:00"))
    except Exception:
        return None


def _formatar_data_hora(data_str):
    data = _parse_iso_datetime(data_str)
    return data.strftime("%d/%m/%Y %H:%M") if data else "-"


def _formatar_data(data_str):
    data = _parse_iso_datetime(data_str)
    return data.strftime("%d/%m/%Y") if data else "-"


def calcular_due_date(prioridade, data_base=None):
    data_referencia = data_base or datetime.now(timezone.utc)
    dias_sla = SLA_DIAS_POR_PRIORIDADE.get(prioridade, SLA_DIAS_POR_PRIORIDADE["Média"])
    return data_referencia + timedelta(days=dias_sla)


def calcular_dias_parada(demanda):
    """Retorna dias desde que a demanda entrou em Parada."""
    status = demanda.get("status") or "Aberta"
    if status != "Parada":
        return 0

    data_base = (
        demanda.get("status_updated_at")
        or demanda.get("updated_at")
        or demanda.get("data_criacao")
    )
    data = _parse_iso_datetime(data_base)
    if not data:
        return 0

    agora = datetime.now(timezone.utc)
    return max((agora - data).days, 0)


def calcular_indicadores_prazo(demanda):
    status = demanda.get("status") or "Aberta"
    due_dt = _parse_iso_datetime(demanda.get("due_date"))
    agora = datetime.now(timezone.utc)

    dias_para_vencimento = None
    dias_atraso = 0
    esta_atrasada = False

    if due_dt:
        dias_para_vencimento = (due_dt - agora).days
        if status != "Finalizada" and due_dt < agora:
            esta_atrasada = True
            dias_atraso = max((agora - due_dt).days, 0)

    demanda["due_date_fmt"] = _formatar_data_hora(demanda.get("due_date"))
    demanda["status_updated_at_fmt"] = _formatar_data_hora(
        demanda.get("status_updated_at")
    )
    demanda["resolved_at_fmt"] = _formatar_data_hora(demanda.get("resolved_at"))
    demanda["dias_para_vencimento"] = dias_para_vencimento
    demanda["dias_atraso"] = dias_atraso
    demanda["esta_atrasada"] = esta_atrasada


def preparar_demandas(demandas):
    dados = sorted(
        demandas or [],
        key=lambda d: (
            ORDEM_PRIORIDADE.get(d.get("prioridade", "Média"), 2),
            d.get("data_criacao", ""),
        ),
    )
    for demanda in dados:
        demanda["dias_parada"] = calcular_dias_parada(demanda)
        calcular_indicadores_prazo(demanda)
        demanda["data_criacao_fmt"] = _formatar_data(demanda.get("data_criacao"))
        demanda["data_criacao_hora_fmt"] = _formatar_data_hora(
            demanda.get("data_criacao")
        )
        demanda["updated_at_fmt"] = _formatar_data_hora(demanda.get("updated_at"))
        assignee = demanda.get("assignee")
        assignee_nome = None
        if isinstance(assignee, dict):
            assignee_nome = assignee.get("nome")
        if not assignee_nome and demanda.get("assignee_nome"):
            assignee_nome = demanda.get("assignee_nome")
        if not assignee_nome and demanda.get("assignee_id") == demanda.get(
            "usuario_id"
        ):
            assignee_nome = demanda.get("solicitante")
        demanda["assignee_nome"] = assignee_nome or "Nao atribuido"
    return dados


def _descricao_evento_historico(evento, usuarios_por_id):
    before_data = evento.get("before_data") or {}
    after_data = evento.get("after_data") or {}
    tipo = evento.get("tipo")

    status_antes = before_data.get("status") or "-"
    status_depois = after_data.get("status") or "-"
    prioridade_antes = before_data.get("prioridade") or "-"
    prioridade_depois = after_data.get("prioridade") or "-"

    assignee_antes_id = before_data.get("assignee_id")
    assignee_depois_id = after_data.get("assignee_id")
    assignee_antes = (
        usuarios_por_id.get(assignee_antes_id, "Nao atribuido")
        if assignee_antes_id
        else "Nao atribuido"
    )
    assignee_depois = (
        usuarios_por_id.get(assignee_depois_id, "Nao atribuido")
        if assignee_depois_id
        else "Nao atribuido"
    )

    if tipo in {"status_alterado", "status_alterado_lote", "reaberta"}:
        return f"Status: {status_antes} -> {status_depois}"
    if tipo == "prioridade_alterada":
        return f"Prioridade: {prioridade_antes} -> {prioridade_depois}"
    if tipo == "assignee_alterado":
        return f"Responsavel: {assignee_antes} -> {assignee_depois}"
    if tipo == "criada":
        return (
            "Demanda criada "
            f"(Status: {status_depois}; Prioridade: {prioridade_depois}; Responsavel: {assignee_depois})"
        )
    return "Alteracao registrada"


def listar_usuarios():
    resposta = supabase.table("usuarios").select("id,nome").order("nome").execute()
    return resposta.data or []


def listar_solicitantes(demandas):
    return sorted(
        {
            demanda.get("solicitante")
            for demanda in demandas or []
            if demanda.get("solicitante")
        },
        key=str.lower,
    )


def parse_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalizar_status_filtros(status_values):
    return [status for status in status_values if status in STATUS_DEMANDA_VALIDOS]


def _parse_filtros_listagem(args):
    status_filtro = _normalizar_status_filtros(args.getlist("status"))
    if not status_filtro:
        status_unico = args.get("status", "").strip()
        if status_unico in STATUS_DEMANDA_VALIDOS:
            status_filtro = [status_unico]

    page = max(parse_int(args.get("page", 1), 1), 1)
    per_page_raw = max(
        parse_int(
            args.get("per_page", ITENS_POR_PAGINA_PADRAO), ITENS_POR_PAGINA_PADRAO
        ),
        1,
    )
    per_page = min(per_page_raw, ITENS_POR_PAGINA_MAX)

    sort_by = args.get("sort_by", "updated_at")
    if sort_by not in ORDENACOES_LISTAGEM:
        sort_by = "updated_at"

    sort_dir = args.get("sort_dir", "desc").lower()
    if sort_dir not in ORDENS_DIRECAO:
        sort_dir = "desc"

    return {
        "filtro_prioridade": args.get("prioridade", "Todas"),
        "filtro_solicitante": args.get("solicitante", "").strip(),
        "status_filtro": status_filtro,
        "periodo_inicio": args.get("data_inicio", "").strip(),
        "periodo_fim": args.get("data_fim", "").strip(),
        "assignee_id": args.get("assignee_id", "").strip(),
        "minhas_demandas": args.get("minhas_demandas") == "1",
        "sort_by": sort_by,
        "sort_dir": sort_dir,
        "page": page,
        "per_page": per_page,
    }


def _parse_filtros_gerencial(args):
    status_filtro = _normalizar_status_filtros(args.getlist("status"))
    if not status_filtro:
        status_unico = args.get("status", "").strip()
        if status_unico in STATUS_DEMANDA_VALIDOS:
            status_filtro = [status_unico]

    prioridade = args.get("prioridade", "Todas").strip()
    if prioridade not in {"Todas", *PRIORIDADES_VALIDAS}:
        prioridade = "Todas"

    assignee_id = args.get("assignee_id", "").strip()
    if assignee_id and not assignee_id.isdigit():
        assignee_id = ""

    data_inicio = args.get("data_inicio", "").strip()
    data_fim = args.get("data_fim", "").strip()
    try:
        dt_inicio = (
            datetime.strptime(data_inicio, "%Y-%m-%d").date() if data_inicio else None
        )
    except ValueError:
        dt_inicio = None
        data_inicio = ""
    try:
        dt_fim = datetime.strptime(data_fim, "%Y-%m-%d").date() if data_fim else None
    except ValueError:
        dt_fim = None
        data_fim = ""

    if dt_inicio and dt_fim and dt_inicio > dt_fim:
        data_inicio, data_fim = data_fim, data_inicio

    sla_status = args.get("sla_status", "").strip()
    if sla_status not in {"", "no_prazo", "vencendo", "atrasadas"}:
        sla_status = ""

    agregacao = args.get("agregacao", "dia").strip().lower()
    if agregacao not in {"dia", "semana"}:
        agregacao = "dia"

    return {
        "prioridade": prioridade,
        "status_filtro": status_filtro,
        "assignee_id": assignee_id,
        "data_inicio": data_inicio,
        "data_fim": data_fim,
        "sla_status": sla_status,
        "agregacao": agregacao,
    }


def _aplicar_filtros_demanda_query(query, filtros):
    if filtros.get("prioridade") in PRIORIDADES_VALIDAS:
        query = query.eq("prioridade", filtros["prioridade"])
    if filtros.get("status_filtro"):
        query = query.in_("status", filtros["status_filtro"])
    if filtros.get("data_inicio"):
        query = query.gte("data_criacao", f"{filtros['data_inicio']}T00:00:00")
    if filtros.get("data_fim"):
        query = query.lte("data_criacao", f"{filtros['data_fim']}T23:59:59")
    if (filtros.get("assignee_id") or "").isdigit():
        query = query.eq("assignee_id", int(filtros["assignee_id"]))
    return query


def _classificar_sla_demanda(demanda):
    status = demanda.get("status") or "Aberta"
    if status == "Finalizada":
        return "no_prazo"

    dias_para_vencimento = demanda.get("dias_para_vencimento")
    if demanda.get("esta_atrasada"):
        return "atrasadas"
    if dias_para_vencimento is not None and dias_para_vencimento <= 1:
        return "vencendo"
    return "no_prazo"


def _agrupar_evolucao_temporal(demandas, agregacao):
    buckets = defaultdict(lambda: {"criadas": 0, "finalizadas": 0})
    intervalos = {}

    for demanda in demandas:
        created_dt = _parse_iso_datetime(demanda.get("data_criacao"))
        resolved_dt = _parse_iso_datetime(demanda.get("resolved_at"))

        if created_dt:
            chave = created_dt.date().isoformat()
            if agregacao == "semana":
                ano, semana, _ = created_dt.isocalendar()
                chave = f"{ano}-W{semana:02d}"
                inicio_semana = created_dt.date() - timedelta(days=created_dt.weekday())
                fim_semana = inicio_semana + timedelta(days=6)
                intervalos[chave] = (inicio_semana.isoformat(), fim_semana.isoformat())
            else:
                intervalos[chave] = (chave, chave)
            buckets[chave]["criadas"] += 1

        if resolved_dt:
            chave = resolved_dt.date().isoformat()
            if agregacao == "semana":
                ano, semana, _ = resolved_dt.isocalendar()
                chave = f"{ano}-W{semana:02d}"
                inicio_semana = resolved_dt.date() - timedelta(
                    days=resolved_dt.weekday()
                )
                fim_semana = inicio_semana + timedelta(days=6)
                intervalos[chave] = (inicio_semana.isoformat(), fim_semana.isoformat())
            else:
                intervalos[chave] = (chave, chave)
            buckets[chave]["finalizadas"] += 1

    labels = sorted(buckets.keys())
    return {
        "labels": labels,
        "criadas": [buckets[label]["criadas"] for label in labels],
        "finalizadas": [buckets[label]["finalizadas"] for label in labels],
        "intervalos": [intervalos.get(label, ("", "")) for label in labels],
    }


def _coletar_dados_dashboard_gerencial(demandas, filtros):
    status_ordem = ["Aberta", "Em andamento", "Parada", "Finalizada"]
    total_por_status = {status: 0 for status in status_ordem}
    por_usuario = {}
    atraso = []

    sla_totais = {"no_prazo": 0, "vencendo": 0, "atrasadas": 0}
    prioridade_totais = {prioridade: 0 for prioridade in PRIORIDADES_VALIDAS}

    for demanda in demandas:
        status = demanda.get("status") or "Aberta"
        if status in total_por_status:
            total_por_status[status] += 1

        prioridade = demanda.get("prioridade")
        if prioridade in prioridade_totais:
            prioridade_totais[prioridade] += 1

        sla_bucket = _classificar_sla_demanda(demanda)
        sla_totais[sla_bucket] += 1

        if demanda.get("esta_atrasada"):
            atraso.append(
                {
                    "id": demanda.get("id"),
                    "titulo": demanda.get("titulo"),
                    "responsavel": demanda.get("assignee_nome", "Nao atribuido"),
                    "prioridade": demanda.get("prioridade", "Média"),
                    "dias_atraso": demanda.get("dias_atraso", 0),
                    "due_date_fmt": demanda.get("due_date_fmt", "-"),
                }
            )

        usuario_id = demanda.get("assignee_id")
        if not usuario_id:
            continue
        nome = demanda.get("assignee_nome") or f"Usuario #{usuario_id}"

        if usuario_id not in por_usuario:
            por_usuario[usuario_id] = {
                "nome": nome,
                "total": 0,
                "em_andamento": 0,
                "finalizadas": 0,
            }

        por_usuario[usuario_id]["total"] += 1
        if status == "Em andamento":
            por_usuario[usuario_id]["em_andamento"] += 1
        if status == "Finalizada":
            por_usuario[usuario_id]["finalizadas"] += 1

    atraso.sort(key=lambda item: item["dias_atraso"], reverse=True)
    demandas_por_usuario = sorted(
        por_usuario.values(), key=lambda item: (-item["total"], item["nome"].lower())
    )
    ultimas_atualizadas = sorted(
        demandas,
        key=lambda item: item.get("updated_at") or item.get("data_criacao") or "",
        reverse=True,
    )[:10]
    evolucao = _agrupar_evolucao_temporal(demandas, filtros.get("agregacao", "dia"))

    return {
        "total_demandas": len(demandas),
        "total_por_status": total_por_status,
        "demandas_atraso": atraso,
        "demandas_por_usuario": demandas_por_usuario,
        "ultimas_atualizadas": ultimas_atualizadas,
        "chart_labels": status_ordem,
        "chart_values": [total_por_status[status] for status in status_ordem],
        "chart_prioridade_labels": PRIORIDADES_VALIDAS,
        "chart_prioridade_values": [prioridade_totais[p] for p in PRIORIDADES_VALIDAS],
        "chart_sla_labels": ["No prazo", "Vencendo", "Atrasadas"],
        "chart_sla_values": [
            sla_totais["no_prazo"],
            sla_totais["vencendo"],
            sla_totais["atrasadas"],
        ],
        "chart_temporal_labels": evolucao["labels"],
        "chart_temporal_criadas": evolucao["criadas"],
        "chart_temporal_finalizadas": evolucao["finalizadas"],
        "chart_temporal_ranges": evolucao["intervalos"],
    }


def _formatar_filtros_gerencial(filtros):
    filtros_txt = []
    if filtros.get("prioridade") in PRIORIDADES_VALIDAS:
        filtros_txt.append(f"Prioridade: {filtros['prioridade']}")
    if filtros.get("status_filtro"):
        filtros_txt.append("Status: " + ", ".join(filtros["status_filtro"]))
    if filtros.get("assignee_id"):
        filtros_txt.append(f"Responsavel ID: {filtros['assignee_id']}")
    if filtros.get("data_inicio") or filtros.get("data_fim"):
        inicio = filtros.get("data_inicio") or "-"
        fim = filtros.get("data_fim") or "-"
        filtros_txt.append(f"Periodo: {inicio} ate {fim}")
    if filtros.get("sla_status"):
        mapa_sla = {
            "no_prazo": "No prazo",
            "vencendo": "Vencendo",
            "atrasadas": "Atrasadas",
        }
        filtros_txt.append(
            f"SLA: {mapa_sla.get(filtros['sla_status'], filtros['sla_status'])}"
        )
    return filtros_txt


def _coletar_dataset_gerencial(filtros):
    query = supabase.table("demandas").select("*,assignee:assignee_id(nome)")
    query = _aplicar_filtros_demanda_query(query, filtros)
    demandas_res = query.execute()
    demandas = preparar_demandas(demandas_res.data or [])

    if filtros.get("sla_status"):
        demandas = [
            demanda
            for demanda in demandas
            if _classificar_sla_demanda(demanda) == filtros["sla_status"]
        ]

    dados_dashboard = _coletar_dados_dashboard_gerencial(demandas, filtros)
    return {
        "demandas": demandas,
        "dados_dashboard": dados_dashboard,
        "filtros_txt": _formatar_filtros_gerencial(filtros),
    }


def usuario_pode_gerenciar(demanda):
    if not demanda:
        return False

    return (
        demanda.get("usuario_id") == session.get("usuario_id")
        or session.get("role") == "manager"
    )


def usuario_pode_alterar_status(demanda):
    if not demanda:
        return False

    return (
        demanda.get("usuario_id") == session.get("usuario_id")
        or demanda.get("assignee_id") == session.get("usuario_id")
        or session.get("role") == "manager"
    )


def transicao_status_valida(status_atual, novo_status):
    if status_atual == novo_status:
        return True

    return novo_status in STATUS_TRANSITIONS.get(status_atual, set())


def buscar_demanda(id):
    resposta = supabase.table("demandas").select("*").eq("id", id).execute()
    return resposta.data[0] if resposta.data else None


def registrar_evento_demanda(
    demanda_id, tipo, before_data=None, after_data=None, autor_id=None
):
    if not demanda_id:
        return

    evento = {
        "demanda_id": demanda_id,
        "tipo": tipo,
        "autor_id": autor_id if autor_id is not None else session.get("usuario_id"),
        "before_data": before_data or {},
        "after_data": after_data or {},
    }
    supabase.table("demanda_eventos").insert(evento).execute()


def listar_eventos_demanda(demanda_id):
    resposta = (
        supabase.table("demanda_eventos")
        .select(
            "id,tipo,before_data,after_data,created_at,autor_id,autor:autor_id(nome)"
        )
        .eq("demanda_id", demanda_id)
        .order("created_at", desc=True)
        .execute()
    )
    return resposta.data or []


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def login_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if not session.get("usuario_id"):
            flash("Faça login para continuar")
            return redirect("/login")
        return view_func(*args, **kwargs)

    return wrapped_view


def manager_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if session.get("role") != "manager":
            flash("Acesso permitido apenas para perfil gerencial.")
            return redirect("/dashboard")
        return view_func(*args, **kwargs)

    return wrapped_view


def _get_or_create_csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


@app.before_request
def csrf_protect():
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        session_token = session.get("_csrf_token")
        request_token = request.form.get("_csrf_token") or request.headers.get(
            "X-CSRF-Token"
        )
        if not session_token or not request_token:
            abort(400, description="CSRF token ausente.")
        if not secrets.compare_digest(session_token, request_token):
            abort(400, description="CSRF token invalido.")


@app.context_processor
def inject_usuario_logado():
    return {
        "usuario_logado": {
            "id": session.get("usuario_id"),
            "nome": session.get("usuario_nome"),
            "cargo": session.get("usuario_cargo"),
            "role": session.get("role", "user"),
        },
        "csrf_token": _get_or_create_csrf_token(),
    }


# ---------------------------------------------------------------------------
# Rotas de autenticação
# ---------------------------------------------------------------------------


@app.route("/cadastro", methods=["GET", "POST"])
def cadastro():
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "")
        confirmar_senha = request.form.get("confirmar_senha", "")
        cargo = request.form.get("cargo", "").strip()

        if senha != confirmar_senha:
            flash("As senhas não coincidem")
            return redirect("/cadastro")

        usuario_existente = (
            supabase.table("usuarios").select("id").eq("email", email).execute()
        )

        if usuario_existente.data:
            flash("E-mail já cadastrado")
            return redirect("/cadastro")

        senha_hash = generate_password_hash(senha)
        dados = {
            "nome": nome,
            "email": email,
            "senha_hash": senha_hash,
            "cargo": cargo,
            "criado_em": datetime.now(timezone.utc).isoformat(),
        }
        supabase.table("usuarios").insert(dados).execute()
        flash("Cadastro realizado com sucesso!")
        return redirect("/login")

    return render_template("cadastro.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "")
        resposta = supabase.table("usuarios").select("*").eq("email", email).execute()

        usuario = resposta.data[0] if resposta.data else None
        if not usuario or not check_password_hash(usuario["senha_hash"], senha):
            flash("E-mail ou senha incorretos")
            return redirect("/login")

        session["usuario_id"] = usuario["id"]
        session["usuario_nome"] = usuario["nome"]
        session["usuario_cargo"] = usuario["cargo"]
        session["role"] = usuario.get("role", "user")
        session.permanent = True

        flash(f"Bem-vindo, {usuario['nome']}!")
        return redirect("/")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# ---------------------------------------------------------------------------
# Rotas principais
# ---------------------------------------------------------------------------


@app.route("/")
@login_required
def index():
    filtros = _parse_filtros_listagem(request.args)
    query = supabase.table("demandas").select(
        "*,assignee:assignee_id(nome)", count="exact"
    )

    if filtros["filtro_prioridade"] in PRIORIDADES_VALIDAS:
        query = query.eq("prioridade", filtros["filtro_prioridade"])
    if filtros["filtro_solicitante"]:
        query = query.eq("solicitante", filtros["filtro_solicitante"])
    if filtros["status_filtro"]:
        query = query.in_("status", filtros["status_filtro"])
    if filtros["periodo_inicio"]:
        query = query.gte("data_criacao", f"{filtros['periodo_inicio']}T00:00:00")
    if filtros["periodo_fim"]:
        query = query.lte("data_criacao", f"{filtros['periodo_fim']}T23:59:59")
    if filtros["assignee_id"].isdigit():
        query = query.eq("assignee_id", int(filtros["assignee_id"]))
    if filtros["minhas_demandas"]:
        usuario_id = session.get("usuario_id")
        query = query.or_(f"usuario_id.eq.{usuario_id},assignee_id.eq.{usuario_id}")

    coluna_ordenacao = ORDENACOES_LISTAGEM[filtros["sort_by"]]
    query = query.order(
        coluna_ordenacao, desc=filtros["sort_dir"] == "desc", nullsfirst=False
    )

    inicio = (filtros["page"] - 1) * filtros["per_page"]
    fim = inicio + filtros["per_page"] - 1
    res = query.range(inicio, fim).execute()

    total_registros = res.count or 0
    total_paginas = max(
        (total_registros + filtros["per_page"] - 1) // filtros["per_page"], 1
    )
    if filtros["page"] > total_paginas:
        filtros["page"] = total_paginas
        inicio = (filtros["page"] - 1) * filtros["per_page"]
        fim = inicio + filtros["per_page"] - 1
        res = query.range(inicio, fim).execute()

    dados = preparar_demandas(res.data)

    base_qs = request.args.to_dict(flat=False)
    base_qs.pop("page", None)

    def _build_page_url(page_number):
        params = {k: list(v) for k, v in base_qs.items()}
        params["page"] = [str(page_number)]
        return "/?" + urlencode(params, doseq=True)

    prev_page_url = (
        _build_page_url(filtros["page"] - 1) if filtros["page"] > 1 else None
    )
    next_page_url = (
        _build_page_url(filtros["page"] + 1)
        if filtros["page"] < total_paginas
        else None
    )

    solicitantes_res = supabase.table("demandas").select("solicitante").execute()
    solicitantes = listar_solicitantes(solicitantes_res.data)
    usuarios = listar_usuarios()

    return render_template(
        "index.html",
        demandas=dados,
        filtro=filtros["filtro_prioridade"],
        solicitante=filtros["filtro_solicitante"],
        status_filtro=filtros["status_filtro"],
        data_inicio=filtros["periodo_inicio"],
        data_fim=filtros["periodo_fim"],
        assignee_id_filtro=filtros["assignee_id"],
        minhas_demandas=filtros["minhas_demandas"],
        sort_by=filtros["sort_by"],
        sort_dir=filtros["sort_dir"],
        page=filtros["page"],
        per_page=filtros["per_page"],
        total_paginas=total_paginas,
        total_registros=total_registros,
        prev_page_url=prev_page_url,
        next_page_url=next_page_url,
        solicitantes=solicitantes,
        usuarios=usuarios,
        status_validos=STATUS_DEMANDA_VALIDOS,
        prioridades=PRIORIDADES_VALIDAS,
        dias_parada_limite=DIAS_PARADA,
    )


@app.route("/demandas/lote/status", methods=["POST"])
@login_required
def atualizar_status_lote():
    ids = request.form.getlist("demanda_ids")
    novo_status = request.form.get("novo_status", "").strip()
    redirect_to = request.form.get("redirect_to", "").strip()

    def _redirect_listagem():
        if redirect_to.startswith("/"):
            return redirect(redirect_to)
        return redirect("/")

    if not ids:
        flash("Selecione ao menos uma demanda para atualizar em lote.")
        return _redirect_listagem()

    if novo_status not in STATUS_DEMANDA_VALIDOS:
        flash("Status inválido para atualização em lote.")
        return _redirect_listagem()

    ids_validos = []
    for item in ids:
        if str(item).isdigit():
            ids_validos.append(int(item))

    if not ids_validos:
        flash("Nenhuma demanda válida foi selecionada.")
        return _redirect_listagem()

    resposta = (
        supabase.table("demandas")
        .select("id,status,usuario_id,assignee_id")
        .in_("id", ids_validos)
        .execute()
    )
    demandas = resposta.data or []

    atualizadas = 0
    sem_permissao = 0
    transicao_invalida = 0
    agora_iso = datetime.now(timezone.utc).isoformat()

    for demanda in demandas:
        if not usuario_pode_alterar_status(demanda):
            sem_permissao += 1
            continue

        status_atual = (demanda.get("status") or "Aberta").strip()
        if not transicao_status_valida(status_atual, novo_status):
            transicao_invalida += 1
            continue

        dados_update = {
            "status": novo_status,
            "updated_at": agora_iso,
        }
        if status_atual != novo_status:
            dados_update["status_updated_at"] = agora_iso
            if novo_status == "Finalizada":
                dados_update["resolved_at"] = agora_iso
            elif status_atual == "Finalizada" and novo_status == "Aberta":
                dados_update["resolved_at"] = None

        supabase.table("demandas").update(dados_update).eq(
            "id", demanda["id"]
        ).execute()
        registrar_evento_demanda(
            demanda_id=demanda["id"],
            tipo="status_alterado_lote",
            before_data={"status": status_atual},
            after_data={"status": novo_status},
        )
        atualizadas += 1

    if atualizadas:
        flash(f"{atualizadas} demanda(s) atualizada(s) em lote.")
    if sem_permissao:
        flash(f"{sem_permissao} demanda(s) ignorada(s) por falta de permissão.")
    if transicao_invalida:
        flash(
            f"{transicao_invalida} demanda(s) ignorada(s) por transição de status inválida."
        )

    return _redirect_listagem()


@app.route("/dashboard")
@login_required
def dashboard_redirect():
    return redirect("/")


@app.route("/gerencial/dashboard")
@login_required
@manager_required
def gerencial_dashboard():
    filtros = _parse_filtros_gerencial(request.args)
    dataset = _coletar_dataset_gerencial(filtros)
    dados_dashboard = dataset["dados_dashboard"]
    usuarios = listar_usuarios()
    export_qs = urlencode(request.args.to_dict(flat=False), doseq=True)

    return render_template(
        "gerencial/dashboard.html",
        total_demandas=dados_dashboard["total_demandas"],
        total_por_status=dados_dashboard["total_por_status"],
        demandas_atraso=dados_dashboard["demandas_atraso"],
        demandas_por_usuario=dados_dashboard["demandas_por_usuario"],
        ultimas_atualizadas=dados_dashboard["ultimas_atualizadas"],
        chart_labels=dados_dashboard["chart_labels"],
        chart_values=dados_dashboard["chart_values"],
        chart_prioridade_labels=dados_dashboard["chart_prioridade_labels"],
        chart_prioridade_values=dados_dashboard["chart_prioridade_values"],
        chart_sla_labels=dados_dashboard["chart_sla_labels"],
        chart_sla_values=dados_dashboard["chart_sla_values"],
        chart_temporal_labels=dados_dashboard["chart_temporal_labels"],
        chart_temporal_criadas=dados_dashboard["chart_temporal_criadas"],
        chart_temporal_finalizadas=dados_dashboard["chart_temporal_finalizadas"],
        chart_temporal_ranges=dados_dashboard["chart_temporal_ranges"],
        usuarios=usuarios,
        prioridades=PRIORIDADES_VALIDAS,
        status_validos=STATUS_DEMANDA_VALIDOS,
        filtros=filtros,
        export_querystring=export_qs,
    )


@app.route("/gerencial/dashboard/exportar/csv")
@login_required
@manager_required
def exportar_gerencial_csv():
    filtros = _parse_filtros_gerencial(request.args)
    dataset = _coletar_dataset_gerencial(filtros)
    dados_dashboard = dataset["dados_dashboard"]
    demandas = dataset["demandas"]
    filtros_txt = dataset["filtros_txt"]

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")

    writer.writerow(["PAINEL GERENCIAL - DEMANDAS"])
    writer.writerow([f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}"])
    writer.writerow(
        [
            "Filtros aplicados: "
            + (" | ".join(filtros_txt) if filtros_txt else "Sem filtros aplicados")
        ]
    )
    writer.writerow([])

    writer.writerow(["RESUMO DO DASHBOARD"])
    writer.writerow(["Total de demandas", dados_dashboard["total_demandas"]])
    writer.writerow(["Abertas", dados_dashboard["total_por_status"]["Aberta"]])
    writer.writerow(
        ["Em andamento", dados_dashboard["total_por_status"]["Em andamento"]]
    )
    writer.writerow(["Paradas", dados_dashboard["total_por_status"]["Parada"]])
    writer.writerow(["Finalizadas", dados_dashboard["total_por_status"]["Finalizada"]])
    writer.writerow([])

    writer.writerow(["DEMANDAS POR USUARIO"])
    writer.writerow(["Nome", "Total", "Em andamento", "Finalizadas"])
    for item in dados_dashboard["demandas_por_usuario"]:
        writer.writerow(
            [
                item["nome"],
                item["total"],
                item["em_andamento"],
                item["finalizadas"],
            ]
        )
    writer.writerow([])

    writer.writerow(["DEMANDAS EM ATRASO"])
    writer.writerow(
        [
            "ID",
            "Titulo",
            "Responsavel",
            "Dias de atraso",
            "Vencimento SLA",
            "Prioridade",
        ]
    )
    for item in dados_dashboard["demandas_atraso"]:
        writer.writerow(
            [
                item.get("id", ""),
                item.get("titulo", ""),
                item.get("responsavel", ""),
                item.get("dias_atraso", 0),
                item.get("due_date_fmt", "-"),
                item.get("prioridade", ""),
            ]
        )
    writer.writerow([])

    writer.writerow(["ULTIMAS 10 ATUALIZADAS"])
    writer.writerow(["ID", "Titulo", "Solicitante", "Status", "Prioridade"])
    for d in dados_dashboard["ultimas_atualizadas"]:
        writer.writerow(
            [
                d.get("id", ""),
                d.get("titulo", ""),
                d.get("solicitante", ""),
                d.get("status", "Aberta"),
                d.get("prioridade", ""),
            ]
        )
    writer.writerow([])

    writer.writerow(["BASE FILTRADA COMPLETA"])
    writer.writerow(
        [
            "ID",
            "Titulo",
            "Descricao",
            "Solicitante",
            "Responsavel Executor",
            "Prioridade",
            "Status",
            "Data de Criacao",
            "Vencimento SLA",
            "Dias Parada",
            "Em Atraso",
            "Dias Atraso",
        ]
    )
    for d in demandas:
        writer.writerow(
            [
                d.get("id", ""),
                d.get("titulo", ""),
                d.get("descricao", ""),
                d.get("solicitante", ""),
                d.get("assignee_nome", ""),
                d.get("prioridade", ""),
                d.get("status", ""),
                _formatar_data_hora(d.get("data_criacao")),
                d.get("due_date_fmt", "-"),
                d.get("dias_parada", 0),
                "Sim" if d.get("esta_atrasada") else "Nao",
                d.get("dias_atraso", 0),
            ]
        )

    csv_bytes = "\ufeff" + output.getvalue()
    response = make_response(csv_bytes.encode("utf-8"))
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = (
        f'attachment; filename="gerencial_dashboard_{datetime.now().strftime("%Y%m%d_%H%M")}.csv"'
    )
    return response


@app.route("/gerencial/dashboard/exportar/pdf")
@login_required
@manager_required
def exportar_gerencial_pdf():
    filtros = _parse_filtros_gerencial(request.args)
    dataset = _coletar_dataset_gerencial(filtros)
    dados_dashboard = dataset["dados_dashboard"]
    demandas = dataset["demandas"]
    filtros_txt = dataset["filtros_txt"]

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=1.3 * cm,
        leftMargin=1.3 * cm,
        topMargin=1.8 * cm,
        bottomMargin=1.2 * cm,
    )

    styles = getSampleStyleSheet()
    cor_azul = colors.HexColor("#2563EB")
    cor_cinza = colors.HexColor("#6B7280")

    estilo_titulo = ParagraphStyle(
        "TituloGerencial",
        parent=styles["Title"],
        fontSize=15,
        textColor=colors.white,
        alignment=TA_CENTER,
        spaceAfter=0,
    )
    estilo_sub = ParagraphStyle(
        "SubGerencial",
        parent=styles["Normal"],
        fontSize=10,
        textColor=cor_azul,
        fontName="Helvetica-Bold",
        spaceBefore=10,
        spaceAfter=4,
    )
    estilo_meta = ParagraphStyle(
        "MetaGerencial",
        parent=styles["Normal"],
        fontSize=8,
        textColor=cor_cinza,
        alignment=TA_CENTER,
    )
    estilo_cel = ParagraphStyle(
        "CelGerencial", parent=styles["Normal"], fontSize=7, leading=8
    )

    elementos = []
    titulo_tabela = Table(
        [[Paragraph("PAINEL GERENCIAL - DEMANDAS", estilo_titulo)]],
        colWidths=[doc.width],
    )
    titulo_tabela.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), cor_azul),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    elementos.append(titulo_tabela)
    elementos.append(Spacer(1, 0.2 * cm))
    elementos.append(
        Paragraph(
            f"Gerado em {datetime.now().strftime('%d/%m/%Y as %H:%M')}",
            estilo_meta,
        )
    )
    elementos.append(
        Paragraph(
            "Filtros aplicados: "
            + (" | ".join(filtros_txt) if filtros_txt else "Sem filtros aplicados"),
            estilo_meta,
        )
    )
    elementos.append(Spacer(1, 0.4 * cm))

    elementos.append(Paragraph("Resumo por Status", estilo_sub))
    linhas_status = [["Status", "Total"]] + [
        [status, str(dados_dashboard["total_por_status"][status])]
        for status in ["Aberta", "Em andamento", "Parada", "Finalizada"]
    ]
    linhas_status.append(["Total geral", str(dados_dashboard["total_demandas"])])
    tabela_status = Table(
        linhas_status, colWidths=[doc.width * 0.25, doc.width * 0.1], repeatRows=1
    )
    tabela_status.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), cor_azul),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("ALIGN", (1, 0), (1, -1), "CENTER"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -2),
                    [colors.white, colors.HexColor("#F9FAFB")],
                ),
            ]
        )
    )
    elementos.append(tabela_status)
    elementos.append(Spacer(1, 0.4 * cm))

    elementos.append(Paragraph("Demandas por Usuario", estilo_sub))
    linhas_usuario = [["Nome", "Total", "Em andamento", "Finalizadas"]] + [
        [
            item["nome"],
            str(item["total"]),
            str(item["em_andamento"]),
            str(item["finalizadas"]),
        ]
        for item in dados_dashboard["demandas_por_usuario"]
    ]
    tabela_usuario = Table(
        linhas_usuario,
        colWidths=[
            doc.width * 0.34,
            doc.width * 0.1,
            doc.width * 0.13,
            doc.width * 0.12,
        ],
        repeatRows=1,
    )
    tabela_usuario.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), cor_azul),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.white, colors.HexColor("#F9FAFB")],
                ),
            ]
        )
    )
    elementos.append(tabela_usuario)
    elementos.append(Spacer(1, 0.4 * cm))

    elementos.append(Paragraph("Base Filtrada (linhas exportadas)", estilo_sub))
    cab_det = [
        [
            "ID",
            "Titulo",
            "Solicitante",
            "Responsavel",
            "Prioridade",
            "Status",
            "Criacao",
            "SLA",
            "Parada",
            "Atraso",
        ]
    ]
    linhas_det = cab_det + [
        [
            str(d.get("id", "")),
            Paragraph(d.get("titulo", ""), estilo_cel),
            d.get("solicitante", ""),
            d.get("assignee_nome", ""),
            d.get("prioridade", ""),
            d.get("status", ""),
            _formatar_data_hora(d.get("data_criacao")).replace(" ", "\n"),
            d.get("due_date_fmt", "-").replace(" ", "\n"),
            str(d.get("dias_parada", 0)),
            "Sim" if d.get("esta_atrasada") else "Nao",
        ]
        for d in demandas
    ]
    tabela_det = Table(
        linhas_det,
        colWidths=[
            doc.width * 0.05,
            doc.width * 0.23,
            doc.width * 0.13,
            doc.width * 0.14,
            doc.width * 0.08,
            doc.width * 0.10,
            doc.width * 0.10,
            doc.width * 0.10,
            doc.width * 0.04,
            doc.width * 0.03,
        ],
        repeatRows=1,
    )
    tabela_det.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), cor_azul),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 8),
                ("FONTSIZE", (0, 1), (-1, -1), 7),
                ("ALIGN", (0, 0), (0, -1), "CENTER"),
                ("ALIGN", (4, 0), (9, -1), "CENTER"),
                ("ALIGN", (1, 0), (3, -1), "LEFT"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.white, colors.HexColor("#F9FAFB")],
                ),
            ]
        )
    )
    elementos.append(tabela_det)

    def rodape(canvas, doc_obj):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(cor_cinza)
        canvas.drawCentredString(
            doc_obj.pagesize[0] / 2,
            0.7 * cm,
            f"Pagina {doc_obj.page} - Exportacao do painel gerencial",
        )
        canvas.restoreState()

    doc.build(elementos, onFirstPage=rodape, onLaterPages=rodape)

    buffer.seek(0)
    response = make_response(buffer.read())
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = (
        f'attachment; filename="gerencial_dashboard_{datetime.now().strftime("%Y%m%d_%H%M")}.pdf"'
    )
    return response


@app.route("/nova_demanda", methods=["GET", "POST"])
@login_required
def nova_demanda():
    usuarios = listar_usuarios()
    usuarios_ids = {usuario.get("id") for usuario in usuarios}
    if request.method == "POST":
        prioridade = request.form.get("prioridade", "Média")
        if prioridade not in PRIORIDADES_VALIDAS:
            flash("Prioridade inválida.")
            return redirect("/nova_demanda")

        assignee_id = session["usuario_id"]
        if session.get("role") == "manager":
            assignee_form = request.form.get("assignee_id", "").strip()
            if assignee_form:
                try:
                    assignee_id = int(assignee_form)
                except ValueError:
                    flash("Responsavel executor invalido.")
                    return redirect("/nova_demanda")
                if assignee_id not in usuarios_ids:
                    flash("Responsavel executor nao encontrado.")
                    return redirect("/nova_demanda")

        dados = {
            "titulo": request.form["titulo"],
            "descricao": request.form["descricao"],
            "solicitante": session["usuario_nome"],
            "prioridade": prioridade,
            "status": "Aberta",
            "usuario_id": session["usuario_id"],
            "assignee_id": assignee_id,
            "status_updated_at": datetime.now(timezone.utc).isoformat(),
            "due_date": calcular_due_date(prioridade).isoformat(),
            "resolved_at": None,
        }
        resposta = supabase.table("demandas").insert(dados).execute()
        demanda_criada = resposta.data[0] if resposta.data else None
        if demanda_criada:
            registrar_evento_demanda(
                demanda_id=demanda_criada.get("id"),
                tipo="criada",
                before_data={},
                after_data={
                    "status": demanda_criada.get("status", "Aberta"),
                    "prioridade": demanda_criada.get("prioridade"),
                    "assignee_id": demanda_criada.get("assignee_id"),
                },
            )
        flash("Demanda criada com sucesso!")
        return redirect("/")
    return render_template(
        "nova_demanda.html",
        prioridades=PRIORIDADES_VALIDAS,
        usuarios=usuarios,
    )


@app.route("/editar/<int:id>", methods=["GET", "POST"])
@login_required
def editar(id):
    demanda_atual = buscar_demanda(id)
    if not demanda_atual:
        flash("Demanda não encontrada.")
        return redirect("/")

    pode_gerenciar = usuario_pode_gerenciar(demanda_atual)
    pode_alterar_status = usuario_pode_alterar_status(demanda_atual)
    usuarios = listar_usuarios() if session.get("role") == "manager" else []
    usuarios_ids = {usuario.get("id") for usuario in usuarios}

    if request.method == "POST":
        if not pode_alterar_status:
            flash("Você não tem permissão para alterar o status desta demanda.")
            return redirect(f"/editar/{id}")

        status_atual = (demanda_atual.get("status") or "Aberta").strip()
        novo_status = request.form.get(
            "status", demanda_atual.get("status") or "Aberta"
        ).strip()

        if novo_status not in STATUS_DEMANDA_VALIDOS:
            flash("Status inválido.")
            return redirect(f"/editar/{id}")

        if not transicao_status_valida(status_atual, novo_status):
            flash(f"Transição de status inválida: {status_atual} -> {novo_status}.")
            return redirect(f"/editar/{id}")

        agora = datetime.now(timezone.utc)
        dados = {
            "status": novo_status,
            "updated_at": agora.isoformat(),
        }
        eventos_para_registrar = []

        if pode_gerenciar:
            nova_prioridade = request.form.get(
                "prioridade", demanda_atual["prioridade"]
            )

            if ORDEM_PRIORIDADE.get(nova_prioridade, 2) < ORDEM_PRIORIDADE.get(
                demanda_atual["prioridade"], 2
            ):
                flash("Não é permitido aumentar a prioridade.")
                return redirect(f"/editar/{id}")

            if nova_prioridade not in PRIORIDADES_VALIDAS:
                flash("Prioridade inválida.")
                return redirect(f"/editar/{id}")

            dados.update(
                {
                    "titulo": request.form["titulo"],
                    "descricao": request.form["descricao"],
                    "solicitante": request.form["solicitante"],
                    "prioridade": nova_prioridade,
                }
            )

            if nova_prioridade != demanda_atual.get("prioridade"):
                data_base = (
                    _parse_iso_datetime(demanda_atual.get("data_criacao")) or agora
                )
                dados["due_date"] = calcular_due_date(
                    nova_prioridade, data_base
                ).isoformat()

            assignee_form = request.form.get("assignee_id", "").strip()
            if assignee_form:
                try:
                    dados["assignee_id"] = int(assignee_form)
                except ValueError:
                    flash("Responsavel executor invalido.")
                    return redirect(f"/editar/{id}")
                if dados["assignee_id"] not in usuarios_ids:
                    flash("Responsavel executor nao encontrado.")
                    return redirect(f"/editar/{id}")

        status_original = demanda_atual.get("status") or "Aberta"
        prioridade_original = demanda_atual.get("prioridade")
        assignee_original = demanda_atual.get("assignee_id")

        status_final = dados.get("status", status_original)
        prioridade_final = dados.get("prioridade", prioridade_original)
        assignee_final = dados.get("assignee_id", assignee_original)

        if status_final != status_original:
            dados["status_updated_at"] = agora.isoformat()
            if status_final == "Finalizada":
                dados["resolved_at"] = agora.isoformat()
            elif status_original == "Finalizada" and status_final == "Aberta":
                dados["resolved_at"] = None

        if status_final != status_original:
            tipo_evento_status = (
                "reaberta"
                if status_original == "Finalizada" and status_final == "Aberta"
                else "status_alterado"
            )
            eventos_para_registrar.append(
                {
                    "tipo": tipo_evento_status,
                    "before_data": {"status": status_original},
                    "after_data": {"status": status_final},
                }
            )

        if prioridade_final != prioridade_original:
            eventos_para_registrar.append(
                {
                    "tipo": "prioridade_alterada",
                    "before_data": {"prioridade": prioridade_original},
                    "after_data": {"prioridade": prioridade_final},
                }
            )

        if assignee_final != assignee_original:
            eventos_para_registrar.append(
                {
                    "tipo": "assignee_alterado",
                    "before_data": {"assignee_id": assignee_original},
                    "after_data": {"assignee_id": assignee_final},
                }
            )

        supabase.table("demandas").update(dados).eq("id", id).execute()
        for evento in eventos_para_registrar:
            registrar_evento_demanda(
                demanda_id=id,
                tipo=evento["tipo"],
                before_data=evento["before_data"],
                after_data=evento["after_data"],
            )
        flash("Demanda atualizada!")
        return redirect("/")

    demanda_view = preparar_demandas([demanda_atual])[0]

    return render_template(
        "editar.html",
        demanda=demanda_view,
        pode_gerenciar=pode_gerenciar,
        pode_alterar_status=pode_alterar_status,
        prioridades=PRIORIDADES_VALIDAS,
        usuarios=usuarios,
        status_validos=STATUS_DEMANDA_VALIDOS,
        status_transitions=STATUS_TRANSITIONS,
    )


@app.route("/deletar/<int:id>", methods=["POST"])
@login_required
def deletar(id):
    demanda = buscar_demanda(id)
    if not demanda:
        flash("Demanda não encontrada.")
        return redirect("/")

    if not usuario_pode_gerenciar(demanda):
        flash("Você não pode excluir demanda de outro usuário.")
        return redirect("/")

    supabase.table("demandas").delete().eq("id", id).execute()
    flash("Demanda deletada!")
    return redirect("/")


@app.route("/buscar")
@login_required
def buscar():
    termo = request.args.get("q", "")
    res = (
        supabase.table("demandas")
        .select("*,assignee:assignee_id(nome)")
        .ilike("titulo", f"%{termo}%")
        .execute()
    )
    todos = supabase.table("demandas").select("solicitante").execute()

    dados = preparar_demandas(res.data)

    return render_template(
        "index.html",
        demandas=dados,
        filtro="Todas",
        solicitante="",
        status_filtro=[],
        data_inicio="",
        data_fim="",
        assignee_id_filtro="",
        minhas_demandas=False,
        sort_by="updated_at",
        sort_dir="desc",
        page=1,
        per_page=len(dados) if dados else ITENS_POR_PAGINA_PADRAO,
        total_paginas=1,
        total_registros=len(dados),
        solicitantes=listar_solicitantes(todos.data),
        usuarios=listar_usuarios(),
        status_validos=STATUS_DEMANDA_VALIDOS,
        prioridades=PRIORIDADES_VALIDAS,
        dias_parada_limite=DIAS_PARADA,
    )


@app.route("/relatorios")
@login_required
def relatorios_redirect():
    return redirect("/gerencial/dashboard")


# ---------------------------------------------------------------------------
# Detalhes e comentários
# ---------------------------------------------------------------------------


@app.route("/detalhes/<int:id>")
@login_required
def detalhes(id):
    demanda = (
        supabase.table("demandas")
        .select("*,assignee:assignee_id(nome)")
        .eq("id", id)
        .single()
        .execute()
    )
    eventos = listar_eventos_demanda(id)
    usuarios_por_id = {u.get("id"): u.get("nome") for u in listar_usuarios()}

    for evento in eventos:
        evento["created_at_fmt"] = _formatar_data_hora(evento.get("created_at"))
        evento["descricao"] = _descricao_evento_historico(evento, usuarios_por_id)

    comentarios = (
        supabase.table("comentarios")
        .select("*,usuarios:autor_id(nome)")
        .eq("demanda_id", id)
        .order("data")
        .execute()
    )

    comentarios_data = comentarios.data or []
    for comentario in comentarios_data:
        comentario["data_fmt"] = _formatar_data_hora(comentario.get("data"))

    return render_template(
        "detalhes.html",
        demanda=preparar_demandas([demanda.data])[0],
        eventos=eventos,
        comentarios=comentarios_data,
        pode_gerenciar=usuario_pode_gerenciar(demanda.data),
    )


@app.route("/adicionar_comentario/<int:demanda_id>", methods=["POST"])
@login_required
def adicionar_comentario(demanda_id):
    dados = {
        "demanda_id": demanda_id,
        "comentario": request.form["comentario"],
        "autor": session.get("usuario_nome"),
        "autor_id": session.get("usuario_id"),
    }
    supabase.table("comentarios").insert(dados).execute()
    return redirect(f"/detalhes/{demanda_id}")


if __name__ == "__main__":
    app.run(debug=_env_to_bool(os.environ.get("FLASK_DEBUG")), host="0.0.0.0")
