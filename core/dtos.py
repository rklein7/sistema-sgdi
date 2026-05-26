def serialize_demanda(demanda):
    if not demanda:
        return None

    assignee = demanda.get("assignee") if isinstance(demanda.get("assignee"), dict) else {}

    return {
        "id": demanda.get("id"),
        "titulo": demanda.get("titulo"),
        "descricao": demanda.get("descricao"),
        "prioridade": demanda.get("prioridade"),
        "status": demanda.get("status"),
        "solicitante": demanda.get("solicitante"),
        "usuario_id": demanda.get("usuario_id"),
        "assignee_id": demanda.get("assignee_id"),
        "assignee_nome": demanda.get("assignee_nome") or assignee.get("nome"),
        "data_criacao": demanda.get("data_criacao"),
        "updated_at": demanda.get("updated_at"),
        "status_updated_at": demanda.get("status_updated_at"),
        "due_date": demanda.get("due_date"),
        "resolved_at": demanda.get("resolved_at"),
    }
