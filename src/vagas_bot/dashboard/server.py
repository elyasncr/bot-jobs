"""Local HTTP server (stdlib): JSON API under /api, the built Angular app everywhere else.

Binds to 127.0.0.1 only. Static files never leave the dist folder; unknown routes without
a file extension fall back to index.html (Angular routing).
"""

import json
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from vagas_bot.config import Settings
from vagas_bot.dashboard import data
from vagas_bot.dashboard.data import DashboardError
from vagas_bot.log import get_logger

log = get_logger("dashboard")

MAX_BODY_BYTES = 64 * 1024
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".png": "image/png",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
}


def find_dist(root: Path) -> Path | None:
    """The Angular build output: dashboard/dist/<app>/browser (or dist/<app>) with index.html."""
    base = root / "dashboard" / "dist"
    for candidate in [*sorted(base.glob("*/browser")), *sorted(base.glob("*"))]:
        if (candidate / "index.html").is_file():
            return candidate
    return None


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "vagas-bot-dashboard"

    def __init__(self, *args: Any, settings: Settings, dist: Path, **kwargs: Any) -> None:
        self.settings = settings
        self.dist = dist.resolve()
        super().__init__(*args, **kwargs)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 — assinatura da stdlib
        log.debug("%s %s", self.address_string(), format % args)

    # --- roteamento ---

    def do_GET(self) -> None:  # noqa: N802 — nome exigido pela stdlib
        url = urlsplit(self.path)
        if url.path.startswith("/api/"):
            query = parse_qs(url.query)
            routes = {
                "/api/jobs": lambda: data.job_rows(self.settings),
                "/api/benchmark/runs": lambda: data.benchmark_runs(self.settings),
                "/api/benchmark": lambda: data.benchmark_payload(self.settings, (query.get("run") or [None])[0]),
            }
            handler = routes.get(url.path)
            self._api(handler if handler else _not_found)
            return
        self._static(url.path)

    def do_PUT(self) -> None:  # noqa: N802
        url = urlsplit(self.path)
        prefix = "/api/labels/"
        if not url.path.startswith(prefix) or len(url.path) == len(prefix):
            self._api(_not_found)
            return
        job_id = unquote(url.path[len(prefix):])
        self._api(lambda: data.save_label(self.settings, job_id, self._json_body()))

    # --- API ---

    def _json_body(self) -> Any:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            raise DashboardError(413, "Corpo grande demais.")
        try:
            return json.loads(self.rfile.read(length) or b"null")
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise DashboardError(400, "JSON inválido.") from exc

    def _api(self, produce: Any) -> None:
        try:
            self._send_json(HTTPStatus.OK, produce())
        except DashboardError as exc:
            self._send_json(exc.status, {"error": exc.message})
        except Exception as exc:  # noqa: BLE001 — a tela recebe a mensagem em vez de uma conexão caída
            log.exception("Erro na API do dashboard")
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"Erro interno: {exc}"})

    def _send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # --- arquivos estáticos ---

    def _static(self, raw_path: str) -> None:
        relative = unquote(raw_path).replace("\\", "/").lstrip("/")
        target = (self.dist / relative).resolve()
        inside = target == self.dist or target.is_relative_to(self.dist)
        if inside and target.is_file():
            self._send_file(target)
        elif Path(relative).suffix:  # pediu um arquivo (.js, .css...) que não existe
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Arquivo não encontrado."})
        else:  # rota do Angular (/vagas, /benchmark...)
            self._send_file(self.dist / "index.html")

    def _send_file(self, path: Path) -> None:
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        if path.name == "index.html":
            self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)


def _not_found() -> Any:
    raise DashboardError(404, "Rota não encontrada.")


def make_server(settings: Settings, dist: Path, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    handler = partial(DashboardHandler, settings=settings, dist=dist)
    return ThreadingHTTPServer((host, port), handler)
