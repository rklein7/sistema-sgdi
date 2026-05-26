from pathlib import Path

from flask import Blueprint, Response, send_file

api_docs_bp = Blueprint("api_docs", __name__, url_prefix="/api")


@api_docs_bp.get("/openapi.yaml")
def openapi_spec():
    spec_path = Path(__file__).resolve().parent.parent / "openapi" / "openapi.yaml"
    return send_file(spec_path, mimetype="application/yaml")


@api_docs_bp.get("/docs")
def swagger_ui():
    html = """<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>SGDI API Docs</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css" />
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    window.ui = SwaggerUIBundle({
      url: '/api/openapi.yaml',
      dom_id: '#swagger-ui',
      deepLinking: true,
      presets: [SwaggerUIBundle.presets.apis],
    });
  </script>
</body>
</html>"""
    return Response(html, mimetype="text/html")
