import csv
import io
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from flask import (
    Blueprint,
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
from werkzeug.security import check_password_hash, generate_password_hash

from auth.session_auth import login_required, manager_required
from core.config import create_supabase_client
from repositories import (
    demandas_repository,
    usuarios_repository,
)
from services import (
    audit_log_service,
    auditoria_service,
    authz_service,
    comentarios_service,
    demandas_service,
)

web_bp = Blueprint("web", __name__)
supabase = create_supabase_client()

PRIORIDADES_VALIDAS = demandas_service.PRIORIDADES_VALIDAS
ORDEM_PRIORIDADE = demandas_service.ORDEM_PRIORIDADE
STATUS_DEMANDA_VALIDOS = demandas_service.STATUS_DEMANDA_VALIDOS
STATUS_TRANSITIONS = authz_service.STATUS_TRANSITIONS
DIAS_PARADA = 3  # configuravel
ORDENACOES_LISTAGEM = {
    "updated_at": "updated_at",
    "prioridade": "prioridade",
    "due_date": "due_date",
}
ORDENS_DIRECAO = {"asc", "desc"}
ITENS_POR_PAGINA_PADRAO = 12
ITENS_POR_PAGINA_MAX = 50


def _parse_iso_datetime(data_str):
    return demandas_service.parse_iso_datetime(data_str)


def _formatar_data_hora(data_str):
    data = _parse_iso_datetime(data_str)
    return data.strftime("%d/%m/%Y %H:%M") if data else "-"


def _formatar_data(data_str):
    data = _parse_iso_datetime(data_str)
    return data.strftime("%d/%m/%Y") if data else "-"


def calcular_dias_parada(demanda):
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
    if tipo == "editada":
        campos = after_data.get("campos") or []
        return "Demanda editada" + (f" ({', '.join(campos)})" if campos else "")
    if tipo == "excluida":
        return "Demanda excluida"
    if tipo == "comentario_criado":
        return "Comentario criado"
    return "Alteracao registrada"


def _registrar_operacao_demanda_web(event_type, demanda_id=None, status_code=200, metadata=None):
    audit_log_service.registrar_security_event_best_effort(
        event_type,
        actor_user_id=session.get("usuario_id"),
        actor_type="user",
        entity_type="demanda",
        entity_id=demanda_id,
        status_code=status_code,
        metadata=metadata or {},
    )


def _registrar_log_gerencial(event_type, filtros, status_code=200, metadata=None):
    audit_log_service.registrar_security_event_best_effort(
        event_type,
        actor_user_id=session.get("usuario_id"),
        actor_type="user",
        entity_type="gerencial_dashboard",
        status_code=status_code,
        request_data={"filtros": filtros},
        metadata={
            "filtros": filtros,
            "filtros_aplicados": bool(_formatar_filtros_gerencial(filtros)),
            **(metadata or {}),
        },
    )


def listar_usuarios():
    return usuarios_repository.listar_para_selecao(supabase)


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

    atraso = sorted(atraso, key=lambda d: d.get("dias_atraso", 0), reverse=True)
    atraso = atraso[:10]

    demandas_por_usuario = sorted(
        por_usuario.values(), key=lambda d: (d["total"], d["nome"].lower()), reverse=True
    )

    ultimas_atualizadas = sorted(
        demandas,
        key=lambda d: _parse_iso_datetime(d.get("updated_at"))
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )[:10]

    evolucao_temporal = _agrupar_evolucao_temporal(demandas, filtros.get("agregacao", "dia"))

    return {
        "total_demandas": len(demandas),
        "total_por_status": total_por_status,
        "demandas_atraso": atraso,
        "demandas_por_usuario": demandas_por_usuario,
        "ultimas_atualizadas": ultimas_atualizadas,
        "chart_labels": list(total_por_status.keys()),
        "chart_values": list(total_por_status.values()),
        "chart_prioridade_labels": list(prioridade_totais.keys()),
        "chart_prioridade_values": list(prioridade_totais.values()),
        "chart_sla_labels": ["No prazo", "Vencendo", "Atrasadas"],
        "chart_sla_values": [
            sla_totais["no_prazo"],
            sla_totais["vencendo"],
            sla_totais["atrasadas"],
        ],
        "chart_temporal_labels": evolucao_temporal["labels"],
        "chart_temporal_criadas": evolucao_temporal["criadas"],
        "chart_temporal_finalizadas": evolucao_temporal["finalizadas"],
        "chart_temporal_ranges": evolucao_temporal["intervalos"],
    }


def _formatar_filtros_gerencial(filtros):
    filtros_txt = []
    if filtros.get("prioridade") and filtros["prioridade"] != "Todas":
        filtros_txt.append(f"Prioridade: {filtros['prioridade']}")
    if filtros.get("status_filtro"):
        filtros_txt.append(f"Status: {', '.join(filtros['status_filtro'])}")
    if filtros.get("assignee_id"):
        filtros_txt.append(f"Responsavel ID: {filtros['assignee_id']}")
    if filtros.get("data_inicio"):
        filtros_txt.append(f"Data inicio: {filtros['data_inicio']}")
    if filtros.get("data_fim"):
        filtros_txt.append(f"Data fim: {filtros['data_fim']}")
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
    demandas_res = demandas_repository.listar_para_gerencial(supabase, filtros)
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


def buscar_demanda(id):
    return demandas_repository.buscar_por_id(supabase, id)


@web_bp.route("/cadastro", methods=["GET", "POST"])
def cadastro():
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "")
        confirmar_senha = request.form.get("confirmar_senha", "")
        cargo = request.form.get("cargo", "").strip()

        if senha != confirmar_senha:
            flash("As senhas nao coincidem")
            return redirect("/cadastro")

        if usuarios_repository.existe_email(supabase, email):
            flash("E-mail ja cadastrado")
            return redirect("/cadastro")

        senha_hash = generate_password_hash(senha)
        dados = {
            "nome": nome,
            "email": email,
            "senha_hash": senha_hash,
            "cargo": cargo,
            "criado_em": datetime.now(timezone.utc).isoformat(),
        }
        resposta = usuarios_repository.inserir(supabase, dados)
        usuario_criado = resposta.data[0] if getattr(resposta, "data", None) else {}
        audit_log_service.registrar_security_event_best_effort(
            "user_registered",
            actor_type="anonymous",
            entity_type="usuario",
            entity_id=usuario_criado.get("id"),
            status_code=201,
            metadata={"role": usuario_criado.get("role", "user")},
        )
        flash("Cadastro realizado com sucesso!")
        return redirect("/login")

    return render_template("cadastro.html")


@web_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "")
        usuario = usuarios_repository.buscar_por_email(supabase, email)
        if not usuario or not check_password_hash(usuario["senha_hash"], senha):
            audit_log_service.registrar_security_event_best_effort(
                "login_failure",
                actor_type="anonymous",
                entity_type="usuario",
                entity_id=usuario.get("id") if usuario else None,
                status_code=401,
                metadata={"reason": "invalid_credentials"},
            )
            flash("E-mail ou senha incorretos")
            return redirect("/login")

        session["usuario_id"] = usuario["id"]
        session["usuario_nome"] = usuario["nome"]
        session["usuario_cargo"] = usuario["cargo"]
        session["role"] = usuario.get("role", "user")
        session.permanent = True
        audit_log_service.registrar_security_event_best_effort(
            "login_success",
            actor_user_id=usuario["id"],
            actor_type="user",
            entity_type="usuario",
            entity_id=usuario["id"],
            status_code=200,
            metadata={"role": session["role"]},
        )

        flash(f"Bem-vindo, {usuario['nome']}!")
        return redirect("/")

    return render_template("login.html")


@web_bp.route("/logout")
def logout():
    usuario_id = session.get("usuario_id")
    audit_log_service.registrar_security_event_best_effort(
        "logout",
        actor_user_id=usuario_id,
        actor_type="user" if usuario_id else "anonymous",
        entity_type="usuario",
        entity_id=usuario_id,
        status_code=302,
        metadata={"role": session.get("role")},
    )
    session.clear()
    return redirect("/login")


@web_bp.route("/")
@login_required
def index():
    filtros = _parse_filtros_listagem(request.args)
    coluna_ordenacao = ORDENACOES_LISTAGEM[filtros["sort_by"]]

    inicio = (filtros["page"] - 1) * filtros["per_page"]
    fim = inicio + filtros["per_page"] - 1
    filtros_repo = {**filtros, "usuario_id": session.get("usuario_id")}
    res = demandas_repository.listar_com_filtros_paginado(
        supabase,
        filtros_repo,
        coluna_ordenacao,
        filtros["sort_dir"] == "desc",
        inicio,
        fim,
    )

    total_registros = res.count or 0
    total_paginas = max(
        (total_registros + filtros["per_page"] - 1) // filtros["per_page"], 1
    )
    if filtros["page"] > total_paginas:
        filtros["page"] = total_paginas
        inicio = (filtros["page"] - 1) * filtros["per_page"]
        fim = inicio + filtros["per_page"] - 1
        res = demandas_repository.listar_com_filtros_paginado(
            supabase,
            filtros_repo,
            coluna_ordenacao,
            filtros["sort_dir"] == "desc",
            inicio,
            fim,
        )

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

    solicitantes_res = demandas_repository.listar_solicitantes(supabase)
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


@web_bp.route("/demandas/lote/status", methods=["POST"])
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
        flash("Status invalido para atualizacao em lote.")
        return _redirect_listagem()

    ids_validos = []
    for item in ids:
        if str(item).isdigit():
            ids_validos.append(int(item))

    if not ids_validos:
        flash("Nenhuma demanda valida foi selecionada.")
        return _redirect_listagem()

    resposta = demandas_repository.listar_por_ids_status(supabase, ids_validos)
    demandas = resposta.data or []

    atualizadas = 0
    sem_permissao = 0
    transicao_invalida = 0
    ids_atualizados = []
    agora = datetime.now(timezone.utc)

    for demanda in demandas:
        if not authz_service.usuario_pode_alterar_status(
            demanda,
            session.get("usuario_id"),
            session.get("role"),
        ):
            sem_permissao += 1
            continue

        status_atual = (demanda.get("status") or "Aberta").strip()
        if not authz_service.transicao_status_valida(status_atual, novo_status):
            transicao_invalida += 1
            continue

        dados_update = demandas_service.aplicar_atualizacao_status(
            {}, status_atual, novo_status, agora
        )

        demandas_repository.atualizar(supabase, demanda["id"], dados_update)
        auditoria_service.registrar_evento(
            supabase,
            demanda_id=demanda["id"],
            tipo="status_alterado_lote",
            before_data={"status": status_atual},
            after_data={"status": novo_status},
            autor_id=session.get("usuario_id"),
        )
        atualizadas += 1
        ids_atualizados.append(demanda["id"])

    if atualizadas:
        _registrar_operacao_demanda_web(
            "demanda_status_batch_updated_web",
            metadata={
                "status": novo_status,
                "updated_count": atualizadas,
                "forbidden_count": sem_permissao,
                "invalid_transition_count": transicao_invalida,
                "demanda_ids": ids_atualizados,
            },
        )
        flash(f"{atualizadas} demanda(s) atualizada(s) em lote.")
    if sem_permissao:
        flash(f"{sem_permissao} demanda(s) ignorada(s) por falta de permissao.")
    if transicao_invalida:
        flash(
            f"{transicao_invalida} demanda(s) ignorada(s) por transicao de status invalida."
        )

    return _redirect_listagem()


@web_bp.route("/dashboard")
@login_required
def dashboard_redirect():
    return redirect("/")


@web_bp.route("/gerencial/dashboard")
@login_required
@manager_required
def gerencial_dashboard():
    filtros = _parse_filtros_gerencial(request.args)
    dataset = _coletar_dataset_gerencial(filtros)
    dados_dashboard = dataset["dados_dashboard"]
    usuarios = listar_usuarios()
    export_qs = urlencode(request.args.to_dict(flat=False), doseq=True)
    _registrar_log_gerencial(
        "management_dashboard_access",
        filtros,
        metadata={"quantidade_registros_consultados": dados_dashboard["total_demandas"]},
    )

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


@web_bp.route("/gerencial/dashboard/exportar/csv")
@login_required
@manager_required
def exportar_gerencial_csv():
    filtros = _parse_filtros_gerencial(request.args)
    dataset = _coletar_dataset_gerencial(filtros)
    dados_dashboard = dataset["dados_dashboard"]
    demandas = dataset["demandas"]
    filtros_txt = dataset["filtros_txt"]
    quantidade_exportada = len(demandas)

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
    _registrar_log_gerencial(
        "management_export_csv",
        filtros,
        metadata={
            "formato": "csv",
            "quantidade_registros_exportados": quantidade_exportada,
            "total_demandas": dados_dashboard["total_demandas"],
        },
    )
    return response


@web_bp.route("/gerencial/dashboard/exportar/pdf")
@login_required
@manager_required
def exportar_gerencial_pdf():
    filtros = _parse_filtros_gerencial(request.args)
    dataset = _coletar_dataset_gerencial(filtros)
    dados_dashboard = dataset["dados_dashboard"]
    demandas = dataset["demandas"]
    filtros_txt = dataset["filtros_txt"]
    quantidade_exportada = len(demandas)

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
    _registrar_log_gerencial(
        "management_export_pdf",
        filtros,
        metadata={
            "formato": "pdf",
            "quantidade_registros_exportados": quantidade_exportada,
            "total_demandas": dados_dashboard["total_demandas"],
        },
    )
    return response


@web_bp.route("/nova_demanda", methods=["GET", "POST"])
@login_required
def nova_demanda():
    usuarios = listar_usuarios()
    usuarios_ids = {usuario.get("id") for usuario in usuarios}
    if request.method == "POST":
        prioridade = request.form.get("prioridade", "Média")
        if prioridade not in PRIORIDADES_VALIDAS:
            flash("Prioridade invalida.")
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

        dados = demandas_service.montar_dados_criacao_demanda(
            titulo=request.form["titulo"],
            descricao=request.form["descricao"],
            solicitante=session["usuario_nome"],
            usuario_id=session["usuario_id"],
            prioridade=prioridade,
            assignee_id=assignee_id,
        )
        resposta = demandas_repository.inserir(supabase, dados)
        demanda_criada = resposta.data[0] if resposta.data else None
        if demanda_criada:
            auditoria_service.registrar_evento(
                supabase,
                demanda_id=demanda_criada.get("id"),
                tipo="criada",
                before_data={},
                after_data={
                    "status": demanda_criada.get("status", "Aberta"),
                    "prioridade": demanda_criada.get("prioridade"),
                    "assignee_id": demanda_criada.get("assignee_id"),
                },
                autor_id=session.get("usuario_id"),
            )
            _registrar_operacao_demanda_web(
                "demanda_created_web",
                demanda_id=demanda_criada.get("id"),
                status_code=201,
                metadata={
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


@web_bp.route("/editar/<int:id>", methods=["GET", "POST"])
@login_required
def editar(id):
    demanda_atual = buscar_demanda(id)
    if not demanda_atual:
        flash("Demanda nao encontrada.")
        return redirect("/")

    pode_gerenciar = authz_service.usuario_pode_gerenciar(
        demanda_atual,
        session.get("usuario_id"),
        session.get("role"),
    )
    pode_alterar_status = authz_service.usuario_pode_alterar_status(
        demanda_atual,
        session.get("usuario_id"),
        session.get("role"),
    )
    usuarios = listar_usuarios() if session.get("role") == "manager" else []
    usuarios_ids = {usuario.get("id") for usuario in usuarios}

    if request.method == "POST":
        if not pode_alterar_status:
            flash("Voce nao tem permissao para alterar o status desta demanda.")
            return redirect(f"/editar/{id}")

        status_atual = (demanda_atual.get("status") or "Aberta").strip()
        novo_status = request.form.get(
            "status", demanda_atual.get("status") or "Aberta"
        ).strip()

        if novo_status not in STATUS_DEMANDA_VALIDOS:
            flash("Status invalido.")
            return redirect(f"/editar/{id}")

        if not authz_service.transicao_status_valida(status_atual, novo_status):
            flash(f"Transicao de status invalida: {status_atual} -> {novo_status}.")
            return redirect(f"/editar/{id}")

        agora = datetime.now(timezone.utc)
        dados = demandas_service.aplicar_atualizacao_status(
            {}, status_atual, novo_status, agora
        )
        eventos_para_registrar = []

        if pode_gerenciar:
            nova_prioridade = request.form.get(
                "prioridade", demanda_atual["prioridade"]
            )

            if ORDEM_PRIORIDADE.get(nova_prioridade, 2) < ORDEM_PRIORIDADE.get(
                demanda_atual["prioridade"], 2
            ):
                flash("Nao e permitido aumentar a prioridade.")
                return redirect(f"/editar/{id}")

            if nova_prioridade not in PRIORIDADES_VALIDAS:
                flash("Prioridade invalida.")
                return redirect(f"/editar/{id}")

            dados.update(
                {
                    "titulo": request.form["titulo"],
                    "descricao": request.form["descricao"],
                    "solicitante": request.form["solicitante"],
                }
            )
            dados = demandas_service.aplicar_atualizacao_prioridade(
                dados, demanda_atual, nova_prioridade, agora
            )

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

        campos_editados = {}
        for campo in ("titulo", "descricao", "solicitante"):
            if campo in dados and dados[campo] != demanda_atual.get(campo):
                campos_editados[campo] = {
                    "antes": demanda_atual.get(campo),
                    "depois": dados[campo],
                }

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

        if campos_editados:
            eventos_para_registrar.append(
                {
                    "tipo": "editada",
                    "before_data": {
                        campo: valores["antes"]
                        for campo, valores in campos_editados.items()
                    },
                    "after_data": {
                        "campos": list(campos_editados.keys()),
                        **{
                            campo: valores["depois"]
                            for campo, valores in campos_editados.items()
                        },
                    },
                }
            )

        demandas_repository.atualizar(supabase, id, dados)
        auditoria_service.registrar_eventos(
            supabase,
            demanda_id=id,
            eventos=eventos_para_registrar,
            autor_id=session.get("usuario_id"),
        )
        _registrar_operacao_demanda_web(
            "demanda_updated_web",
            demanda_id=id,
            metadata={
                "eventos": [evento["tipo"] for evento in eventos_para_registrar],
                "campos": sorted(dados.keys()),
            },
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


@web_bp.route("/deletar/<int:id>", methods=["POST"])
@login_required
def deletar(id):
    demanda = buscar_demanda(id)
    if not demanda:
        flash("Demanda nao encontrada.")
        return redirect("/")

    if not authz_service.usuario_pode_gerenciar(
        demanda,
        session.get("usuario_id"),
        session.get("role"),
    ):
        flash("Voce nao pode excluir demanda de outro usuario.")
        return redirect("/")

    auditoria_service.registrar_evento(
        supabase,
        demanda_id=id,
        tipo="excluida",
        before_data={
            "status": demanda.get("status"),
            "prioridade": demanda.get("prioridade"),
            "assignee_id": demanda.get("assignee_id"),
        },
        after_data={},
        autor_id=session.get("usuario_id"),
    )
    demandas_repository.remover(supabase, id)
    _registrar_operacao_demanda_web(
        "demanda_deleted_web",
        demanda_id=id,
        metadata={
            "status": demanda.get("status"),
            "prioridade": demanda.get("prioridade"),
            "assignee_id": demanda.get("assignee_id"),
        },
    )
    flash("Demanda deletada!")
    return redirect("/")


@web_bp.route("/buscar")
@login_required
def buscar():
    termo = request.args.get("q", "")
    res = demandas_repository.buscar_por_titulo(supabase, termo)
    todos = demandas_repository.listar_solicitantes(supabase)

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


@web_bp.route("/relatorios")
@login_required
def relatorios_redirect():
    return redirect("/gerencial/dashboard")


@web_bp.route("/detalhes/<int:id>")
@login_required
def detalhes(id):
    demanda = demandas_repository.buscar_por_id_com_assignee(supabase, id)
    eventos = auditoria_service.listar_eventos_demanda(supabase, id)
    usuarios_por_id = {u.get("id"): u.get("nome") for u in listar_usuarios()}

    for evento in eventos:
        evento["created_at_fmt"] = _formatar_data_hora(evento.get("created_at"))
        evento["descricao"] = _descricao_evento_historico(evento, usuarios_por_id)

    comentarios_data = comentarios_service.listar_comentarios_demanda(supabase, id)
    for comentario in comentarios_data:
        comentario["data_fmt"] = _formatar_data_hora(comentario.get("data"))

    return render_template(
        "detalhes.html",
        demanda=preparar_demandas([demanda.data])[0],
        eventos=eventos,
        comentarios=comentarios_data,
        pode_gerenciar=authz_service.usuario_pode_gerenciar(
            demanda.data,
            session.get("usuario_id"),
            session.get("role"),
        ),
    )


@web_bp.route("/adicionar_comentario/<int:demanda_id>", methods=["POST"])
@login_required
def adicionar_comentario(demanda_id):
    comentarios_service.criar_comentario_demanda(
        supabase,
        demanda_id=demanda_id,
        comentario=request.form["comentario"],
        autor_id=session.get("usuario_id"),
        autor_nome=session.get("usuario_nome"),
    )
    auditoria_service.registrar_evento(
        supabase,
        demanda_id=demanda_id,
        tipo="comentario_criado",
        before_data={},
        after_data={"comentario": "adicionado"},
        autor_id=session.get("usuario_id"),
    )
    _registrar_operacao_demanda_web(
        "demanda_comment_created_web",
        demanda_id=demanda_id,
    )
    return redirect(f"/detalhes/{demanda_id}")
