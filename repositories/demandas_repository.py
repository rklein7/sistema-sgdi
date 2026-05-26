def _aplicar_filtros(query, filtros):
    if filtros.get("prioridade") in {"Alta", "Média", "Baixa"}:
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


def listar_com_filtros_paginado(
    supabase,
    filtros,
    coluna_ordenacao,
    ordem_desc,
    inicio,
    fim,
):
    query = supabase.table("demandas").select(
        "*,assignee:assignee_id(nome)", count="exact"
    )

    if filtros.get("filtro_prioridade") in {"Alta", "Média", "Baixa"}:
        query = query.eq("prioridade", filtros["filtro_prioridade"])
    if filtros.get("filtro_solicitante"):
        query = query.eq("solicitante", filtros["filtro_solicitante"])
    if filtros.get("status_filtro"):
        query = query.in_("status", filtros["status_filtro"])
    if filtros.get("periodo_inicio"):
        query = query.gte("data_criacao", f"{filtros['periodo_inicio']}T00:00:00")
    if filtros.get("periodo_fim"):
        query = query.lte("data_criacao", f"{filtros['periodo_fim']}T23:59:59")
    if (filtros.get("assignee_id") or "").isdigit():
        query = query.eq("assignee_id", int(filtros["assignee_id"]))
    if filtros.get("minhas_demandas"):
        usuario_id = filtros.get("usuario_id")
        query = query.or_(f"usuario_id.eq.{usuario_id},assignee_id.eq.{usuario_id}")

    query = query.order(coluna_ordenacao, desc=ordem_desc, nullsfirst=False)
    return query.range(inicio, fim).execute()


def listar_para_gerencial(supabase, filtros):
    query = supabase.table("demandas").select("*,assignee:assignee_id(nome)")
    query = _aplicar_filtros(query, filtros)
    return query.execute()


def buscar_por_id(supabase, demanda_id):
    resposta = supabase.table("demandas").select("*").eq("id", demanda_id).execute()
    return resposta.data[0] if resposta.data else None


def buscar_por_id_com_assignee(supabase, demanda_id):
    return (
        supabase.table("demandas")
        .select("*,assignee:assignee_id(nome)")
        .eq("id", demanda_id)
        .single()
        .execute()
    )


def listar_por_ids_status(supabase, ids):
    return (
        supabase.table("demandas")
        .select("id,status,usuario_id,assignee_id")
        .in_("id", ids)
        .execute()
    )


def inserir(supabase, dados):
    return supabase.table("demandas").insert(dados).execute()


def atualizar(supabase, demanda_id, dados):
    return supabase.table("demandas").update(dados).eq("id", demanda_id).execute()


def remover(supabase, demanda_id):
    return supabase.table("demandas").delete().eq("id", demanda_id).execute()


def buscar_por_titulo(supabase, termo):
    return (
        supabase.table("demandas")
        .select("*,assignee:assignee_id(nome)")
        .ilike("titulo", f"%{termo}%")
        .execute()
    )


def listar_solicitantes(supabase):
    return supabase.table("demandas").select("solicitante").execute()
