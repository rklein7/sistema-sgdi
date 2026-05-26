def listar_para_selecao(supabase):
    resposta = supabase.table("usuarios").select("id,nome").order("nome").execute()
    return resposta.data or []


def buscar_por_email(supabase, email):
    resposta = supabase.table("usuarios").select("*").eq("email", email).execute()
    return resposta.data[0] if resposta.data else None


def existe_email(supabase, email):
    resposta = supabase.table("usuarios").select("id").eq("email", email).execute()
    return bool(resposta.data)


def inserir(supabase, dados):
    return supabase.table("usuarios").insert(dados).execute()
