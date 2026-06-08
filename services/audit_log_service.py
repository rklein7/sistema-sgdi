import logging

from flask import g, request, session

from core.config import create_supabase_client
from repositories import audit_logs_repository

logger = logging.getLogger("sgdi.audit")

SENSITIVE_FIELD_MARKER = "[REDACTED]"
SENSITIVE_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "authorization",
    "cpf",
    "confirmar_senha",
    "cookie",
    "email",
    "csrf",
    "csrf_token",
    "password",
    "refresh_token",
    "secret",
    "senha",
    "senha_hash",
    "telefone",
    "token",
    "x_api_key",
    "x-api-key",
    "x-csrf-token",
}
SENSITIVE_KEY_MARKERS = (
    "api_key",
    "cpf",
    "csrf",
    "email",
    "password",
    "senha",
    "secret",
    "telefone",
    "token",
)
NON_SENSITIVE_IDENTIFIER_KEYS = {"api_key_id", "key_id"}
AUDITED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
MAX_STRING_LENGTH = 500
MAX_LIST_ITEMS = 50
MAX_DEPTH = 5

_SUPABASE_CLIENT = None


def _get_supabase_client():
    global _SUPABASE_CLIENT
    if _SUPABASE_CLIENT is None:
        _SUPABASE_CLIENT = create_supabase_client()
    return _SUPABASE_CLIENT


def _is_sensitive_key(key):
    normalized = str(key or "").strip().lower().replace("-", "_")
    if normalized in NON_SENSITIVE_IDENTIFIER_KEYS:
        return False
    return normalized in SENSITIVE_KEYS or any(
        marker in normalized for marker in SENSITIVE_KEY_MARKERS
    )


def sanitize_data(value, depth=0):
    if depth >= MAX_DEPTH:
        return "[MAX_DEPTH]"

    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            sanitized[key] = (
                SENSITIVE_FIELD_MARKER
                if _is_sensitive_key(key)
                else sanitize_data(item, depth + 1)
            )
        return sanitized

    if isinstance(value, (list, tuple)):
        return [sanitize_data(item, depth + 1) for item in value[:MAX_LIST_ITEMS]]

    if isinstance(value, str) and len(value) > MAX_STRING_LENGTH:
        return f"{value[:MAX_STRING_LENGTH]}...[TRUNCATED]"

    return value


def _request_payload():
    if request.is_json:
        return sanitize_data(request.get_json(silent=True) or {})

    if request.form:
        return sanitize_data(request.form.to_dict(flat=False))

    return {}


def _client_ip():
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip() or None
    return request.remote_addr


def _actor_user_id():
    session_user_id = session.get("usuario_id")
    if session_user_id:
        return session_user_id

    header_user_id = request.headers.get("X-User-Id", "").strip()
    if header_user_id.isdigit():
        return int(header_user_id)

    return None


def _actor_type():
    if getattr(g, "api_key_id", None):
        return "api_key"
    if session.get("usuario_id"):
        return "user"
    return "anonymous"


def build_http_audit_log(response):
    view_args = request.view_args or {}
    entity_id = view_args.get("id") or view_args.get("demanda_id")

    return {
        "event_type": "http_request",
        "actor_user_id": _actor_user_id(),
        "actor_type": _actor_type(),
        "entity_type": request.endpoint,
        "entity_id": str(entity_id) if entity_id is not None else None,
        "route": request.path,
        "method": request.method,
        "ip_address": _client_ip(),
        "user_agent": request.headers.get("User-Agent"),
        "status_code": response.status_code,
        "request_data": _request_payload(),
        "metadata": sanitize_data(
            {
                "api_key_id": getattr(g, "api_key_id", None),
                "blueprint": request.blueprint,
                "endpoint": request.endpoint,
                "query_params": request.args.to_dict(flat=False),
                "view_args": request.view_args or {},
            }
        ),
    }


def registrar_audit_log(supabase, audit_log):
    audit_logs_repository.inserir(supabase, audit_log)


def build_security_audit_log(
    event_type,
    actor_user_id=None,
    actor_type=None,
    entity_type=None,
    entity_id=None,
    status_code=None,
    request_data=None,
    metadata=None,
):
    return {
        "event_type": event_type,
        "actor_user_id": (
            actor_user_id if actor_user_id is not None else _actor_user_id()
        ),
        "actor_type": actor_type or _actor_type(),
        "entity_type": entity_type,
        "entity_id": str(entity_id) if entity_id is not None else None,
        "route": request.path,
        "method": request.method,
        "ip_address": _client_ip(),
        "user_agent": request.headers.get("User-Agent"),
        "status_code": status_code,
        "request_data": sanitize_data(
            request_data if request_data is not None else _request_payload()
        ),
        "metadata": sanitize_data(
            {
                "blueprint": request.blueprint,
                "endpoint": request.endpoint,
                **(metadata or {}),
            }
        ),
    }


def _api_metadata(extra_metadata=None):
    api_auth = getattr(g, "api_auth", {}) or {}
    api_key_id = getattr(g, "api_key_id", None) or api_auth.get("key_id")
    metadata = {
        "api_key_id": api_key_id,
        "api_scopes": api_auth.get("scopes", []),
        "blueprint": request.blueprint,
        "endpoint": request.endpoint,
    }
    metadata.update(extra_metadata or {})
    return metadata


def build_api_action_audit_log(
    event_type,
    actor_user_id=None,
    entity_type=None,
    entity_id=None,
    status_code=200,
    request_data=None,
    metadata=None,
):
    return build_security_audit_log(
        event_type,
        actor_user_id=actor_user_id,
        actor_type="api_key" if getattr(g, "api_key_id", None) else "anonymous",
        entity_type=entity_type,
        entity_id=entity_id,
        status_code=status_code,
        request_data=request_data,
        metadata=_api_metadata(metadata),
    )


def registrar_api_action_best_effort(event_type, **kwargs):
    try:
        registrar_audit_log(
            _get_supabase_client(), build_api_action_audit_log(event_type, **kwargs)
        )
    except Exception:
        logger.debug(
            "Nao foi possivel persistir audit_log de API event_type=%s",
            event_type,
            exc_info=True,
        )


def registrar_security_event_best_effort(event_type, **kwargs):
    try:
        registrar_audit_log(
            _get_supabase_client(), build_security_audit_log(event_type, **kwargs)
        )
    except Exception:
        logger.debug(
            "Nao foi possivel persistir audit_log de seguranca event_type=%s",
            event_type,
            exc_info=True,
        )


def registrar_http_request_best_effort(response):
    if request.method not in AUDITED_METHODS:
        return

    try:
        registrar_audit_log(_get_supabase_client(), build_http_audit_log(response))
    except Exception:
        logger.debug("Nao foi possivel persistir audit_log HTTP", exc_info=True)


def register_audit_logging(app):
    @app.after_request
    def _audit_http_request(response):
        registrar_http_request_best_effort(response)
        return response
