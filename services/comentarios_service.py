from repositories import comentarios_repository


def criar_comentario_demanda(supabase, demanda_id, comentario, autor_id, autor_nome):
    dados = {
        "demanda_id": demanda_id,
        "comentario": comentario,
        "autor": autor_nome,
        "autor_id": autor_id,
    }
    return comentarios_repository.inserir(supabase, dados)


def listar_comentarios_demanda(supabase, demanda_id):
    return comentarios_repository.listar_por_demanda(supabase, demanda_id)
