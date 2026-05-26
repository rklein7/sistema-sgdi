STATUS_TRANSITIONS = {
    "Aberta": {"Em andamento", "Parada"},
    "Em andamento": {"Parada", "Finalizada"},
    "Parada": {"Em andamento", "Finalizada"},
    "Finalizada": {"Aberta"},
}


def usuario_pode_gerenciar(demanda, usuario_id, role):
    if not demanda:
        return False

    return demanda.get("usuario_id") == usuario_id or role == "manager"


def usuario_pode_alterar_status(demanda, usuario_id, role):
    if not demanda:
        return False

    return (
        demanda.get("usuario_id") == usuario_id
        or demanda.get("assignee_id") == usuario_id
        or role == "manager"
    )


def transicao_status_valida(status_atual, novo_status):
    if status_atual == novo_status:
        return True

    return novo_status in STATUS_TRANSITIONS.get(status_atual, set())
