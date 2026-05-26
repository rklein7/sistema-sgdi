def inserir_evento(supabase, evento):
    return supabase.table("demanda_eventos").insert(evento).execute()


def listar_por_demanda(supabase, demanda_id):
    resposta = (
        supabase.table("demanda_eventos")
        .select("id,tipo,before_data,after_data,created_at,autor_id,autor:autor_id(nome)")
        .eq("demanda_id", demanda_id)
        .order("created_at", desc=True)
        .execute()
    )
    return resposta.data or []
