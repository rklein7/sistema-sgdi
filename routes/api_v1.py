from datetime import datetime, timezone

from flask import Blueprint, request

from auth.api_key_auth import require_api_key
from core.config import create_supabase_client
from core.dtos import serialize_demanda
from core.errors import api_error, api_success, register_api_error_handlers
from repositories import demandas_repository, usuarios_repository
from services import auditoria_service, authz_service, comentarios_service, demandas_service

api_v1_bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")
register_api_error_handlers(api_v1_bp)
supabase = create_supabase_client()

ORDENACOES_LISTAGEM = {
    "updated_at": "updated_at",
    "prioridade": "prioridade",
    "due_date": "due_date",
    "data_criacao": "data_criacao",
}
ORDENS_DIRECAO = {"asc", "desc"}
ITENS_POR_PAGINA_PADRAO = 12
ITENS_POR_PAGINA_MAX = 50


def _parse_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _request_actor():
    usuario_id_raw = request.headers.get("X-User-Id", "").strip()
    if not usuario_id_raw.isdigit():
        return None, api_error(
            "UNPROCESSABLE_ENTITY",
            "Cabecalho X-User-Id invalido.",
            422,
            {"fields": {"X-User-Id": "deve ser um inteiro positivo"}},
        )

    role = request.headers.get("X-User-Role", "user").strip().lower() or "user"
    if role not in {"user", "manager"}:
        return None, api_error(
            "UNPROCESSABLE_ENTITY",
            "Cabecalho X-User-Role invalido.",
            422,
            {"fields": {"X-User-Role": "valores permitidos: user, manager"}},
        )

    return {"usuario_id": int(usuario_id_raw), "role": role}, None


def _normalizar_status_filtros(status_values):
    validos = set(demandas_service.STATUS_DEMANDA_VALIDOS)
    return [status for status in status_values if status in validos]


def _parse_filtros_listagem(args, usuario_id):
    status_filtro = _normalizar_status_filtros(args.getlist("status"))
    if not status_filtro:
        status_unico = args.get("status", "").strip()
        if status_unico in demandas_service.STATUS_DEMANDA_VALIDOS:
            status_filtro = [status_unico]

    page = max(_parse_int(args.get("page", 1), 1), 1)
    per_page_raw = max(
        _parse_int(args.get("per_page", ITENS_POR_PAGINA_PADRAO), ITENS_POR_PAGINA_PADRAO),
        1,
    )
    per_page = min(per_page_raw, ITENS_POR_PAGINA_MAX)

    sort_by = args.get("sort_by", "updated_at")
    if sort_by not in ORDENACOES_LISTAGEM:
        sort_by = "updated_at"

    sort_dir = args.get("sort_dir", "desc").lower()
    if sort_dir not in ORDENS_DIRECAO:
        sort_dir = "desc"

    assignee_id = args.get("assignee_id", "").strip()
    if assignee_id and not assignee_id.isdigit():
        assignee_id = ""

    return {
        "filtro_prioridade": args.get("prioridade", "Todas"),
        "filtro_solicitante": args.get("solicitante", "").strip(),
        "status_filtro": status_filtro,
        "periodo_inicio": args.get("data_inicio", "").strip(),
        "periodo_fim": args.get("data_fim", "").strip(),
        "assignee_id": assignee_id,
        "minhas_demandas": args.get("minhas_demandas") == "1",
        "sort_by": sort_by,
        "sort_dir": sort_dir,
        "page": page,
        "per_page": per_page,
        "usuario_id": usuario_id,
    }


def _usuarios_ids_validos():
    usuarios = usuarios_repository.listar_para_selecao(supabase)
    return {usuario.get("id") for usuario in usuarios}


def _validar_payload_criacao(payload):
    erros = {}
    titulo = str(payload.get("titulo") or "").strip()
    descricao = str(payload.get("descricao") or "").strip()
    solicitante = str(payload.get("solicitante") or "").strip()
    prioridade = str(payload.get("prioridade") or "Média").strip()

    if not titulo:
        erros["titulo"] = "obrigatorio"
    if not descricao:
        erros["descricao"] = "obrigatorio"
    if not solicitante:
        erros["solicitante"] = "obrigatorio"
    if prioridade not in demandas_service.PRIORIDADES_VALIDAS:
        erros["prioridade"] = "valor invalido"

    assignee_id = payload.get("assignee_id")
    if assignee_id is not None:
        try:
            assignee_id = int(assignee_id)
        except (TypeError, ValueError):
            erros["assignee_id"] = "deve ser inteiro"

    return {
        "titulo": titulo,
        "descricao": descricao,
        "solicitante": solicitante,
        "prioridade": prioridade,
        "assignee_id": assignee_id,
    }, erros


def _validar_payload_patch(payload):
    permitidos = {"titulo", "descricao", "solicitante", "prioridade", "status", "assignee_id"}
    erros = {}
    dados = {}

    for chave in payload.keys():
        if chave not in permitidos:
            erros[chave] = "campo nao permitido"

    if "titulo" in payload:
        titulo = str(payload.get("titulo") or "").strip()
        if not titulo:
            erros["titulo"] = "nao pode ser vazio"
        else:
            dados["titulo"] = titulo

    if "descricao" in payload:
        descricao = str(payload.get("descricao") or "").strip()
        if not descricao:
            erros["descricao"] = "nao pode ser vazio"
        else:
            dados["descricao"] = descricao

    if "solicitante" in payload:
        solicitante = str(payload.get("solicitante") or "").strip()
        if not solicitante:
            erros["solicitante"] = "nao pode ser vazio"
        else:
            dados["solicitante"] = solicitante

    if "prioridade" in payload:
        prioridade = str(payload.get("prioridade") or "").strip()
        if prioridade not in demandas_service.PRIORIDADES_VALIDAS:
            erros["prioridade"] = "valor invalido"
        else:
            dados["prioridade"] = prioridade

    if "status" in payload:
        status = str(payload.get("status") or "").strip()
        if status not in demandas_service.STATUS_DEMANDA_VALIDOS:
            erros["status"] = "valor invalido"
        else:
            dados["status"] = status

    if "assignee_id" in payload:
        assignee_id = payload.get("assignee_id")
        if assignee_id is None:
            dados["assignee_id"] = None
        else:
            try:
                dados["assignee_id"] = int(assignee_id)
            except (TypeError, ValueError):
                erros["assignee_id"] = "deve ser inteiro ou null"

    return dados, erros


def _validar_payload_comentario(payload):
    comentario = str(payload.get("comentario") or "").strip()
    if not comentario:
        return None, {"comentario": "obrigatorio"}
    if len(comentario) > 2000:
        return None, {"comentario": "tamanho maximo de 2000 caracteres"}
    return comentario, {}


def _validar_payload_lote_status(payload):
    erros = {}
    ids = payload.get("ids")
    status = str(payload.get("status") or "").strip()

    if not isinstance(ids, list) or not ids:
        erros["ids"] = "deve ser uma lista nao vazia"
    else:
        ids_invalidos = [item for item in ids if not isinstance(item, int) or item <= 0]
        if ids_invalidos:
            erros["ids"] = "todos os ids devem ser inteiros positivos"

    if status not in demandas_service.STATUS_DEMANDA_VALIDOS:
        erros["status"] = "valor invalido"

    if isinstance(ids, list) and len(ids) > 100:
        erros["ids"] = "maximo de 100 ids por requisicao"

    return {"ids": list(dict.fromkeys(ids or [])), "status": status}, erros


@api_v1_bp.get("/health")
@require_api_key(scopes={"health:read"})
def health_check():
    return api_success(
        {
            "status": "ok",
            "service": "sistema-sgdi-api",
            "version": "v1",
            "auth": {"scheme": "api_key", "required": True},
        },
        message="healthy",
    )


@api_v1_bp.get("/demandas")
@require_api_key(scopes={"demandas:read"})
def listar_demandas():
    actor, error_response = _request_actor()
    if error_response:
        return error_response

    filtros = _parse_filtros_listagem(request.args, actor["usuario_id"])
    coluna_ordenacao = ORDENACOES_LISTAGEM[filtros["sort_by"]]

    inicio = (filtros["page"] - 1) * filtros["per_page"]
    fim = inicio + filtros["per_page"] - 1
    res = demandas_repository.listar_com_filtros_paginado(
        supabase,
        filtros,
        coluna_ordenacao,
        filtros["sort_dir"] == "desc",
        inicio,
        fim,
    )

    total_items = res.count or 0
    total_pages = max((total_items + filtros["per_page"] - 1) // filtros["per_page"], 1)

    data = {
        "items": [serialize_demanda(item) for item in (res.data or [])],
        "pagination": {
            "page": filtros["page"],
            "per_page": filtros["per_page"],
            "total_items": total_items,
            "total_pages": total_pages,
        },
        "sort": {"sort_by": filtros["sort_by"], "sort_dir": filtros["sort_dir"]},
        "filters": {
            "prioridade": filtros["filtro_prioridade"],
            "solicitante": filtros["filtro_solicitante"],
            "status": filtros["status_filtro"],
            "data_inicio": filtros["periodo_inicio"],
            "data_fim": filtros["periodo_fim"],
            "assignee_id": filtros["assignee_id"],
            "minhas_demandas": filtros["minhas_demandas"],
        },
    }
    return api_success(data, message="demandas_listadas")


@api_v1_bp.get("/demandas/<int:demanda_id>")
@require_api_key(scopes={"demandas:read"})
def buscar_demanda(demanda_id):
    actor, error_response = _request_actor()
    if error_response:
        return error_response

    demanda = demandas_repository.buscar_por_id(supabase, demanda_id)
    if not demanda:
        return api_error("NOT_FOUND", "Demanda nao encontrada.", 404)

    if not authz_service.usuario_pode_alterar_status(
        demanda,
        actor["usuario_id"],
        actor["role"],
    ):
        return api_error("FORBIDDEN", "Acesso negado.", 403)

    demanda_com_assignee = demandas_repository.buscar_por_id_com_assignee(supabase, demanda_id)
    return api_success(serialize_demanda(demanda_com_assignee.data), message="demanda_encontrada")


@api_v1_bp.post("/demandas")
@require_api_key(scopes={"demandas:write"})
def criar_demanda():
    actor, error_response = _request_actor()
    if error_response:
        return error_response

    payload = request.get_json(silent=True) or {}
    dados_validos, erros = _validar_payload_criacao(payload)
    if erros:
        return api_error(
            "UNPROCESSABLE_ENTITY",
            "Payload invalido.",
            422,
            {"fields": erros},
        )

    assignee_id = dados_validos["assignee_id"] or actor["usuario_id"]
    if dados_validos["assignee_id"] is not None and actor["role"] != "manager":
        return api_error(
            "FORBIDDEN",
            "Apenas manager pode atribuir responsavel na criacao.",
            403,
        )

    if assignee_id not in _usuarios_ids_validos():
        return api_error(
            "UNPROCESSABLE_ENTITY",
            "Responsavel executor nao encontrado.",
            422,
            {"fields": {"assignee_id": "usuario inexistente"}},
        )

    dados_insert = demandas_service.montar_dados_criacao_demanda(
        titulo=dados_validos["titulo"],
        descricao=dados_validos["descricao"],
        solicitante=dados_validos["solicitante"],
        usuario_id=actor["usuario_id"],
        prioridade=dados_validos["prioridade"],
        assignee_id=assignee_id,
    )
    resposta = demandas_repository.inserir(supabase, dados_insert)
    demanda_criada = resposta.data[0] if resposta.data else None
    if not demanda_criada:
        return api_error("INTERNAL_SERVER_ERROR", "Erro ao criar demanda.", 500)

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
            autor_id=actor["usuario_id"],
        )

    demanda_serializada = serialize_demanda(
        demandas_repository.buscar_por_id_com_assignee(supabase, demanda_criada.get("id")).data
    )
    return api_success(demanda_serializada, message="demanda_criada", status_code=201)


@api_v1_bp.patch("/demandas/<int:demanda_id>")
@require_api_key(scopes={"demandas:write"})
def atualizar_demanda(demanda_id):
    actor, error_response = _request_actor()
    if error_response:
        return error_response

    demanda_atual = demandas_repository.buscar_por_id(supabase, demanda_id)
    if not demanda_atual:
        return api_error("NOT_FOUND", "Demanda nao encontrada.", 404)

    payload = request.get_json(silent=True) or {}
    dados_patch, erros = _validar_payload_patch(payload)
    if erros:
        return api_error("UNPROCESSABLE_ENTITY", "Payload invalido.", 422, {"fields": erros})
    if not dados_patch:
        return api_error(
            "UNPROCESSABLE_ENTITY",
            "Payload vazio. Informe ao menos um campo para atualizar.",
            422,
        )

    pode_gerenciar = authz_service.usuario_pode_gerenciar(
        demanda_atual,
        actor["usuario_id"],
        actor["role"],
    )
    pode_alterar_status = authz_service.usuario_pode_alterar_status(
        demanda_atual,
        actor["usuario_id"],
        actor["role"],
    )

    campos_gerenciais = {"titulo", "descricao", "solicitante", "prioridade", "assignee_id"}
    solicitou_campos_gerenciais = any(campo in dados_patch for campo in campos_gerenciais)
    if solicitou_campos_gerenciais and not pode_gerenciar:
        return api_error("FORBIDDEN", "Acesso negado.", 403)

    if "status" in dados_patch and not pode_alterar_status:
        return api_error("FORBIDDEN", "Acesso negado.", 403)

    agora = datetime.now(timezone.utc)
    dados_update = {}
    eventos_para_registrar = []

    if "status" in dados_patch:
        status_atual = (demanda_atual.get("status") or "Aberta").strip()
        novo_status = dados_patch["status"]
        if not authz_service.transicao_status_valida(status_atual, novo_status):
            return api_error(
                "CONFLICT",
                "Transicao de status invalida.",
                409,
                {"from": status_atual, "to": novo_status},
            )

        dados_update = demandas_service.aplicar_atualizacao_status(
            dados_update,
            status_atual,
            novo_status,
            agora,
        )
        if status_atual != novo_status:
            tipo_evento_status = (
                "reaberta" if status_atual == "Finalizada" and novo_status == "Aberta" else "status_alterado"
            )
            eventos_para_registrar.append(
                {
                    "tipo": tipo_evento_status,
                    "before_data": {"status": status_atual},
                    "after_data": {"status": novo_status},
                }
            )

    if "prioridade" in dados_patch:
        nova_prioridade = dados_patch["prioridade"]
        if demandas_service.ORDEM_PRIORIDADE.get(nova_prioridade, 2) < demandas_service.ORDEM_PRIORIDADE.get(
            demanda_atual.get("prioridade", "Média"), 2
        ):
            return api_error(
                "CONFLICT",
                "Nao e permitido aumentar a prioridade.",
                409,
            )
        dados_update = demandas_service.aplicar_atualizacao_prioridade(
            dados_update,
            demanda_atual,
            nova_prioridade,
            agora,
        )
        if nova_prioridade != demanda_atual.get("prioridade"):
            eventos_para_registrar.append(
                {
                    "tipo": "prioridade_alterada",
                    "before_data": {"prioridade": demanda_atual.get("prioridade")},
                    "after_data": {"prioridade": nova_prioridade},
                }
            )

    if "assignee_id" in dados_patch:
        assignee_id = dados_patch["assignee_id"]
        if assignee_id is not None and assignee_id not in _usuarios_ids_validos():
            return api_error(
                "UNPROCESSABLE_ENTITY",
                "Responsavel executor nao encontrado.",
                422,
                {"fields": {"assignee_id": "usuario inexistente"}},
            )
        dados_update["assignee_id"] = assignee_id
        if assignee_id != demanda_atual.get("assignee_id"):
            eventos_para_registrar.append(
                {
                    "tipo": "assignee_alterado",
                    "before_data": {"assignee_id": demanda_atual.get("assignee_id")},
                    "after_data": {"assignee_id": assignee_id},
                }
            )

    for campo in ("titulo", "descricao", "solicitante"):
        if campo in dados_patch:
            dados_update[campo] = dados_patch[campo]

    if not dados_update:
        return api_success(
            serialize_demanda(demandas_repository.buscar_por_id_com_assignee(supabase, demanda_id).data),
            message="demanda_sem_alteracoes",
        )

    if "updated_at" not in dados_update:
        dados_update["updated_at"] = agora.isoformat()

    demandas_repository.atualizar(supabase, demanda_id, dados_update)
    auditoria_service.registrar_eventos(
        supabase,
        demanda_id=demanda_id,
        eventos=eventos_para_registrar,
        autor_id=actor["usuario_id"],
    )

    demanda_atualizada = demandas_repository.buscar_por_id_com_assignee(supabase, demanda_id)
    return api_success(serialize_demanda(demanda_atualizada.data), message="demanda_atualizada")


@api_v1_bp.delete("/demandas/<int:demanda_id>")
@require_api_key(scopes={"demandas:write"})
def remover_demanda(demanda_id):
    actor, error_response = _request_actor()
    if error_response:
        return error_response

    demanda = demandas_repository.buscar_por_id(supabase, demanda_id)
    if not demanda:
        return api_error("NOT_FOUND", "Demanda nao encontrada.", 404)

    if not authz_service.usuario_pode_gerenciar(
        demanda,
        actor["usuario_id"],
        actor["role"],
    ):
        return api_error("FORBIDDEN", "Acesso negado.", 403)

    demandas_repository.remover(supabase, demanda_id)
    return api_success({"id": demanda_id}, message="demanda_removida")


@api_v1_bp.get("/demandas/<int:demanda_id>/comentarios")
@require_api_key(scopes={"demandas:read"})
def listar_comentarios_demanda(demanda_id):
    actor, error_response = _request_actor()
    if error_response:
        return error_response

    demanda = demandas_repository.buscar_por_id(supabase, demanda_id)
    if not demanda:
        return api_error("NOT_FOUND", "Demanda nao encontrada.", 404)

    if not authz_service.usuario_pode_alterar_status(demanda, actor["usuario_id"], actor["role"]):
        return api_error("FORBIDDEN", "Acesso negado.", 403)

    comentarios = comentarios_service.listar_comentarios_demanda(supabase, demanda_id)
    itens = [
        {
            "id": item.get("id"),
            "demanda_id": item.get("demanda_id"),
            "comentario": item.get("comentario"),
            "autor": item.get("autor") or (item.get("usuarios") or {}).get("nome"),
            "autor_id": item.get("autor_id"),
            "data": item.get("data"),
        }
        for item in comentarios
    ]
    return api_success(itens, message="comentarios_listados")


@api_v1_bp.post("/demandas/<int:demanda_id>/comentarios")
@require_api_key(scopes={"demandas:write"})
def criar_comentario_demanda(demanda_id):
    actor, error_response = _request_actor()
    if error_response:
        return error_response

    demanda = demandas_repository.buscar_por_id(supabase, demanda_id)
    if not demanda:
        return api_error("NOT_FOUND", "Demanda nao encontrada.", 404)

    if not authz_service.usuario_pode_alterar_status(demanda, actor["usuario_id"], actor["role"]):
        return api_error("FORBIDDEN", "Acesso negado.", 403)

    payload = request.get_json(silent=True) or {}
    comentario, erros = _validar_payload_comentario(payload)
    if erros:
        return api_error("UNPROCESSABLE_ENTITY", "Payload invalido.", 422, {"fields": erros})

    comentarios_service.criar_comentario_demanda(
        supabase,
        demanda_id=demanda_id,
        comentario=comentario,
        autor_id=actor["usuario_id"],
        autor_nome=payload.get("autor") or "API User",
    )
    auditoria_service.registrar_evento(
        supabase,
        demanda_id=demanda_id,
        tipo="status_alterado",
        before_data={},
        after_data={"comentario": "adicionado"},
        autor_id=actor["usuario_id"],
    )

    return api_success({"demanda_id": demanda_id, "comentario": comentario}, message="comentario_criado", status_code=201)


@api_v1_bp.get("/demandas/<int:demanda_id>/eventos")
@require_api_key(scopes={"demandas:read"})
def listar_eventos_demanda(demanda_id):
    actor, error_response = _request_actor()
    if error_response:
        return error_response

    demanda = demandas_repository.buscar_por_id(supabase, demanda_id)
    if not demanda:
        return api_error("NOT_FOUND", "Demanda nao encontrada.", 404)

    if not authz_service.usuario_pode_alterar_status(demanda, actor["usuario_id"], actor["role"]):
        return api_error("FORBIDDEN", "Acesso negado.", 403)

    eventos = auditoria_service.listar_eventos_demanda(supabase, demanda_id)
    itens = [
        {
            "id": item.get("id"),
            "demanda_id": demanda_id,
            "tipo": item.get("tipo"),
            "before_data": item.get("before_data") or {},
            "after_data": item.get("after_data") or {},
            "autor_id": item.get("autor_id"),
            "autor_nome": (item.get("autor") or {}).get("nome"),
            "created_at": item.get("created_at"),
        }
        for item in eventos
    ]
    return api_success(itens, message="eventos_listados")


@api_v1_bp.post("/demandas/lote/status")
@require_api_key(scopes={"demandas:write"})
def atualizar_status_lote():
    actor, error_response = _request_actor()
    if error_response:
        return error_response

    payload = request.get_json(silent=True) or {}
    dados, erros = _validar_payload_lote_status(payload)
    if erros:
        return api_error("UNPROCESSABLE_ENTITY", "Payload invalido.", 422, {"fields": erros})

    demandas_resposta = demandas_repository.listar_por_ids_status(supabase, dados["ids"])
    demandas_por_id = {item.get("id"): item for item in (demandas_resposta.data or [])}

    atualizadas = []
    falhas = []
    agora = datetime.now(timezone.utc)

    for demanda_id in dados["ids"]:
        demanda = demandas_por_id.get(demanda_id)
        if not demanda:
            falhas.append({"id": demanda_id, "code": "NOT_FOUND", "message": "Demanda nao encontrada."})
            continue

        if not authz_service.usuario_pode_alterar_status(demanda, actor["usuario_id"], actor["role"]):
            falhas.append({"id": demanda_id, "code": "FORBIDDEN", "message": "Acesso negado."})
            continue

        status_atual = (demanda.get("status") or "Aberta").strip()
        novo_status = dados["status"]
        if not authz_service.transicao_status_valida(status_atual, novo_status):
            falhas.append(
                {
                    "id": demanda_id,
                    "code": "CONFLICT",
                    "message": "Transicao de status invalida.",
                    "details": {"from": status_atual, "to": novo_status},
                }
            )
            continue

        dados_update = demandas_service.aplicar_atualizacao_status({}, status_atual, novo_status, agora)
        demandas_repository.atualizar(supabase, demanda_id, dados_update)
        auditoria_service.registrar_evento(
            supabase,
            demanda_id=demanda_id,
            tipo="reaberta" if status_atual == "Finalizada" and novo_status == "Aberta" else "status_alterado",
            before_data={"status": status_atual},
            after_data={"status": novo_status},
            autor_id=actor["usuario_id"],
        )
        atualizadas.append({"id": demanda_id, "from": status_atual, "to": novo_status})

    return api_success(
        {
            "status_aplicado": dados["status"],
            "updated_count": len(atualizadas),
            "failed_count": len(falhas),
            "updated": atualizadas,
            "failed": falhas,
        },
        message="lote_processado",
    )


@api_v1_bp.get("/usuarios")
@require_api_key(scopes={"usuarios:read"})
def listar_usuarios_catalogo():
    usuarios = usuarios_repository.listar_para_selecao(supabase)
    return api_success(
        [{"id": item.get("id"), "nome": item.get("nome")} for item in usuarios],
        message="usuarios_listados",
    )
