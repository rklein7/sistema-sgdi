import secrets
from functools import wraps

from flask import abort, flash, redirect, request, session


def login_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if not session.get("usuario_id"):
            flash("Faça login para continuar")
            return redirect("/login")
        return view_func(*args, **kwargs)

    return wrapped_view


def manager_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if session.get("role") != "manager":
            flash("Acesso permitido apenas para perfil gerencial.")
            return redirect("/dashboard")
        return view_func(*args, **kwargs)

    return wrapped_view


def _get_or_create_csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def register_auth_handlers(app):
    @app.before_request
    def csrf_protect():
        if request.path.startswith("/api/"):
            return None

        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            session_token = session.get("_csrf_token")
            request_token = request.form.get("_csrf_token") or request.headers.get(
                "X-CSRF-Token"
            )
            if not session_token or not request_token:
                abort(400, description="CSRF token ausente.")
            if not secrets.compare_digest(session_token, request_token):
                abort(400, description="CSRF token invalido.")

    @app.context_processor
    def inject_usuario_logado():
        return {
            "usuario_logado": {
                "id": session.get("usuario_id"),
                "nome": session.get("usuario_nome"),
                "cargo": session.get("usuario_cargo"),
                "role": session.get("role", "user"),
            },
            "csrf_token": _get_or_create_csrf_token(),
        }
