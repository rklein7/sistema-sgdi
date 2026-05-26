import os

from flask import Flask

from auth.api_key_auth import configure_api_keys, register_api_access_logging
from auth.session_auth import register_auth_handlers
from core.config import configure_flask_app, env_to_bool
from routes import api_docs_bp, api_v1_bp, web_bp

app = Flask(__name__)
configure_flask_app(app)
configure_api_keys(app)
register_api_access_logging(app)
register_auth_handlers(app)
app.register_blueprint(web_bp)
app.register_blueprint(api_v1_bp)
app.register_blueprint(api_docs_bp)


if __name__ == "__main__":
    app.run(debug=env_to_bool(os.environ.get("FLASK_DEBUG")), host="0.0.0.0")
