from repositories import eventos_repository


def registrar_evento(
    supabase, demanda_id, tipo, before_data=None, after_data=None, autor_id=None
):
    if not demanda_id:
        return

    evento = {
        "demanda_id": demanda_id,
        "tipo": tipo,
        "autor_id": autor_id,
        "before_data": before_data or {},
        "after_data": after_data or {},
    }
    eventos_repository.inserir_evento(supabase, evento)


def registrar_eventos(supabase, demanda_id, eventos, autor_id=None):
    if not demanda_id or not eventos:
        return

    for evento in eventos:
        registrar_evento(
            supabase,
            demanda_id=demanda_id,
            tipo=evento["tipo"],
            before_data=evento.get("before_data"),
            after_data=evento.get("after_data"),
            autor_id=autor_id,
        )


def listar_eventos_demanda(supabase, demanda_id):
    return eventos_repository.listar_por_demanda(supabase, demanda_id)
