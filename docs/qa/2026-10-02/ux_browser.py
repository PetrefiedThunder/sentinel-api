"""QA-only local documentation capture; no app lifespan, database, or providers."""

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic_settings import BaseSettings

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["READ_REPLICA_URL"] = ""
os.environ["SENTRY_DSN"] = ""
_settings_init = BaseSettings.__init__


def _without_env_file(self, **kwargs):
    kwargs["_env_file"] = None
    _settings_init(self, **kwargs)


with patch.object(BaseSettings, "__init__", _without_env_file):
    from app.main import app

# No TestClient context manager: lifespan never starts the decision bus.
client = TestClient(app)
docs = client.get("/docs")
pages = {
    "/docs": (docs.headers["content-type"], docs.content),
    "/openapi.json": ("application/json", json.dumps(app.openapi()).encode()),
}
client.close()


class DocsOnlyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        content_type, content = pages.get(
            self.path.split("?", 1)[0],
            ("application/json", b'{"detail":"QA harness blocks API execution"}'),
        )
        self.send_response(200 if self.path.split("?", 1)[0] in pages else 403)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, *_args):
        pass


server = ThreadingHTTPServer(("127.0.0.1", 8767), DocsOnlyHandler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    result = subprocess.run(
        ["node", str(Path(__file__).with_name("ux_browser.cjs"))],
        check=False,
        timeout=150,
    )
finally:
    server.shutdown()
    server.server_close()
raise SystemExit(result.returncode)
