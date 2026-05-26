import os
from datetime import timedelta

from dotenv import load_dotenv
from supabase import Client, create_client


def env_to_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def configure_flask_app(app):
    load_dotenv()

    secret_key = os.environ.get("SECRET_KEY")
    if not secret_key:
        raise RuntimeError(
            "SECRET_KEY is obrigatoria. Defina a variavel de ambiente SECRET_KEY."
        )

    app.config["SECRET_KEY"] = secret_key
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = env_to_bool(
        os.environ.get("SESSION_COOKIE_SECURE")
    )
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)
    app.config["API_KEY"] = os.environ.get("API_KEY", "").strip()
    app.config["API_KEYS_RAW"] = os.environ.get("API_KEYS", "").strip()
    app.config["API_RATE_LIMIT_MAX_REQUESTS"] = int(
        os.environ.get("API_RATE_LIMIT_MAX_REQUESTS", "120")
    )
    app.config["API_RATE_LIMIT_WINDOW_SECONDS"] = int(
        os.environ.get("API_RATE_LIMIT_WINDOW_SECONDS", "60")
    )


def create_supabase_client() -> Client:
    load_dotenv()

    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")

    if not supabase_url:
        raise RuntimeError(
            "SUPABASE_URL is obrigatoria. Defina a variavel de ambiente SUPABASE_URL."
        )

    if not supabase_key:
        raise RuntimeError(
            "SUPABASE_KEY is obrigatoria. Defina a variavel de ambiente SUPABASE_KEY."
        )

    return create_client(supabase_url, supabase_key)
