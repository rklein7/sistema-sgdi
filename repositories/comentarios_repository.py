def listar_por_demanda(supabase, demanda_id):
    resposta = (
        supabase.table("comentarios")
        .select("*,usuarios:autor_id(nome)")
        .eq("demanda_id", demanda_id)
        .order("data")
        .execute()
    )
    return resposta.data or []


def inserir(supabase, dados):
    return supabase.table("comentarios").insert(dados).execute()
