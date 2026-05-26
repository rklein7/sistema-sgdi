from datetime import datetime, timedelta, timezone

PRIORIDADES_VALIDAS = ["Alta", "Média", "Baixa"]
ORDEM_PRIORIDADE = {"Alta": 1, "Média": 2, "Baixa": 3}
SLA_DIAS_POR_PRIORIDADE = {"Alta": 2, "Média": 5, "Baixa": 10}
STATUS_DEMANDA_VALIDOS = ["Aberta", "Em andamento", "Parada", "Finalizada"]


def parse_iso_datetime(data_str):
    if not data_str:
        return None

    try:
        return datetime.fromisoformat(data_str.replace("Z", "+00:00"))
    except Exception:
        return None


def calcular_due_date(prioridade, data_base=None):
    data_referencia = data_base or datetime.now(timezone.utc)
    dias_sla = SLA_DIAS_POR_PRIORIDADE.get(prioridade, SLA_DIAS_POR_PRIORIDADE["Média"])
    return data_referencia + timedelta(days=dias_sla)


def montar_dados_criacao_demanda(
    titulo,
    descricao,
    solicitante,
    usuario_id,
    prioridade,
    assignee_id,
    agora=None,
):
    agora_dt = agora or datetime.now(timezone.utc)
    return {
        "titulo": titulo,
        "descricao": descricao,
        "solicitante": solicitante,
        "prioridade": prioridade,
        "status": "Aberta",
        "usuario_id": usuario_id,
        "assignee_id": assignee_id,
        "status_updated_at": agora_dt.isoformat(),
        "due_date": calcular_due_date(prioridade, agora_dt).isoformat(),
        "resolved_at": None,
    }


def aplicar_atualizacao_status(dados, status_atual, novo_status, agora=None):
    agora_dt = agora or datetime.now(timezone.utc)
    dados["status"] = novo_status
    dados["updated_at"] = agora_dt.isoformat()

    if status_atual != novo_status:
        dados["status_updated_at"] = agora_dt.isoformat()
        if novo_status == "Finalizada":
            dados["resolved_at"] = agora_dt.isoformat()
        elif status_atual == "Finalizada" and novo_status == "Aberta":
            dados["resolved_at"] = None

    return dados


def aplicar_atualizacao_prioridade(dados, demanda_atual, nova_prioridade, agora=None):
    dados["prioridade"] = nova_prioridade
    if nova_prioridade != demanda_atual.get("prioridade"):
        agora_dt = agora or datetime.now(timezone.utc)
        data_base = parse_iso_datetime(demanda_atual.get("data_criacao")) or agora_dt
        dados["due_date"] = calcular_due_date(nova_prioridade, data_base).isoformat()

    return dados
