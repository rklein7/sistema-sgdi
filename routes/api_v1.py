from flask import Blueprint

from core.errors import api_success, register_api_error_handlers

api_v1_bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")
register_api_error_handlers(api_v1_bp)


@api_v1_bp.get("/health")
def health_check():
    return api_success(
        {
            "status": "ok",
            "service": "sistema-sgdi-api",
            "version": "v1",
            "auth": {"scheme": "api_key", "required": False},
        },
        message="healthy",
    )
