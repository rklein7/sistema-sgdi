from datetime import datetime, timezone

from flask import jsonify


def _utc_timestamp_iso():
    return datetime.now(timezone.utc).isoformat()


def api_success(data=None, message="ok", status_code=200):
    payload = {
        "success": True,
        "message": message,
        "data": data,
        "error": None,
        "meta": {"timestamp": _utc_timestamp_iso()},
    }
    return jsonify(payload), status_code


def api_error(code, message, status_code, details=None):
    payload = {
        "success": False,
        "message": message,
        "data": None,
        "error": {
            "code": code,
            "details": details or {},
        },
        "meta": {"timestamp": _utc_timestamp_iso()},
    }
    return jsonify(payload), status_code


def register_api_error_handlers(app):
    @app.errorhandler(400)
    def handle_bad_request(_error):
        return api_error("BAD_REQUEST", "Requisicao invalida.", 400)

    @app.errorhandler(401)
    def handle_unauthorized(_error):
        return api_error("UNAUTHORIZED", "Nao autorizado.", 401)

    @app.errorhandler(403)
    def handle_forbidden(_error):
        return api_error("FORBIDDEN", "Acesso negado.", 403)

    @app.errorhandler(404)
    def handle_not_found(_error):
        return api_error("NOT_FOUND", "Recurso nao encontrado.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(_error):
        return api_error("METHOD_NOT_ALLOWED", "Metodo nao permitido.", 405)

    @app.errorhandler(500)
    def handle_internal_error(_error):
        return api_error("INTERNAL_SERVER_ERROR", "Erro interno do servidor.", 500)
