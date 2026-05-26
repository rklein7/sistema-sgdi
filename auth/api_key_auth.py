import hashlib
import logging
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from functools import wraps

from flask import abort, current_app, g, request

from core.config import create_supabase_client

logger = logging.getLogger("sgdi.api")
_RATE_LIMIT_BUCKETS = defaultdict(deque)
_SUPABASE_CLIENT = None


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _api_key_id(raw_key):
    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    return digest[:12]


def _parse_api_keys(raw_value):
    parsed = {}
    if not raw_value:
        return parsed

    for item in raw_value.split(";"):
        chunk = item.strip()
        if not chunk:
            continue

        key_part, _, scopes_raw = chunk.partition(":")
        key_part = key_part.strip()
        key_id = None

        if "|" in key_part:
            key_id, _, key = key_part.partition("|")
            key_id = key_id.strip() or None
            key = key.strip()
        else:
            key = key_part

        if not key:
            continue

        scopes = {
            scope.strip()
            for scope in scopes_raw.split(",")
            if scope.strip()
        }
        parsed[key] = {
            "id": key_id or _api_key_id(key),
            "scopes": scopes,
        }

    return parsed


def get_request_api_key():
    header_key = request.headers.get("X-API-Key")
    if header_key:
        return header_key.strip()

    auth_header = request.headers.get("Authorization", "")
    prefix = "ApiKey "
    if auth_header.startswith(prefix):
        return auth_header[len(prefix) :].strip()

    return None


def _resolve_key_scopes(api_key):
    keys_map = current_app.config.get("API_KEYS", {})
    if api_key in keys_map:
        return keys_map[api_key]
    return None


def _rate_limit_allowed(api_key_id):
    max_requests = int(current_app.config.get("API_RATE_LIMIT_MAX_REQUESTS", 120))
    window_seconds = int(current_app.config.get("API_RATE_LIMIT_WINDOW_SECONDS", 60))
    now = time.time()
    bucket = _RATE_LIMIT_BUCKETS[api_key_id]

    while bucket and bucket[0] <= now - window_seconds:
        bucket.popleft()

    if len(bucket) >= max_requests:
        return False

    bucket.append(now)
    return True


def _get_supabase_client():
    global _SUPABASE_CLIENT
    if _SUPABASE_CLIENT is None:
        _SUPABASE_CLIENT = create_supabase_client()
    return _SUPABASE_CLIENT


def _update_last_used_at_best_effort(key_id):
    try:
        _get_supabase_client().table("api_keys").update({"last_used_at": _utc_now_iso()}).eq(
            "key_id", key_id
        ).execute()
    except Exception:
        logger.debug("Nao foi possivel atualizar last_used_at para key_id=%s", key_id)


def _persist_access_log_best_effort(key_id, endpoint, status_code, latency_ms):
    try:
        _get_supabase_client().table("api_access_logs").insert(
            {
                "key_id": key_id,
                "endpoint": endpoint,
                "status": status_code,
                "latency_ms": latency_ms,
            }
        ).execute()
    except Exception:
        logger.debug("Nao foi possivel persistir log de acesso para key_id=%s", key_id)


def _has_required_scopes(granted_scopes, required_scopes):
    if "*" in granted_scopes:
        return True
    return set(required_scopes).issubset(granted_scopes)


def require_api_key(scopes=None):
    required_scopes = set(scopes or [])

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            api_key = get_request_api_key()
            if not api_key:
                abort(401, description="API key ausente.")

            key_data = _resolve_key_scopes(api_key)
            if key_data is None:
                abort(401, description="API key invalida.")

            if not _rate_limit_allowed(key_data["id"]):
                abort(429, description="Limite de requisicoes excedido para esta API key.")

            granted_scopes = key_data["scopes"]

            if required_scopes and not _has_required_scopes(
                granted_scopes, required_scopes
            ):
                abort(403, description="Escopo insuficiente para este recurso.")

            g.request_started_at = time.perf_counter()
            g.api_key_id = key_data["id"]
            g.api_endpoint = request.path
            _update_last_used_at_best_effort(key_data["id"])

            g.api_auth = {
                "authenticated": True,
                "key_id": key_data["id"],
                "scopes": sorted(granted_scopes),
            }
            return view_func(*args, **kwargs)

        return wrapped

    return decorator


def configure_api_keys(app):
    api_keys = _parse_api_keys(app.config.get("API_KEYS_RAW", ""))
    fallback_api_key = app.config.get("API_KEY")

    if fallback_api_key and fallback_api_key not in api_keys:
        api_keys[fallback_api_key] = {
            "id": _api_key_id(fallback_api_key),
            "scopes": {"*"},
        }

    app.config["API_KEYS"] = {
        key: {
            "id": data["id"],
            "scopes": {scope for scope in data["scopes"] if scope},
        }
        for key, data in api_keys.items()
    }


def register_api_access_logging(app):
    @app.after_request
    def _log_api_access(response):
        if not request.path.startswith("/api/v1"):
            return response

        key_id = getattr(g, "api_key_id", "anonymous")
        started = getattr(g, "request_started_at", None)
        latency_ms = int((time.perf_counter() - started) * 1000) if started else 0

        logger.info(
            "api_access endpoint=%s status=%s latency_ms=%s key_id=%s",
            request.path,
            response.status_code,
            latency_ms,
            key_id,
        )
        _persist_access_log_best_effort(key_id, request.path, response.status_code, latency_ms)
        return response
