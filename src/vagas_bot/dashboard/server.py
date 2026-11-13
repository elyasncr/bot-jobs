"""Local HTTP server (stdlib): JSON API under /api, the built Angular app everywhere else.

Default: 127.0.0.1 only. LAN mode (--lan) listens on the home network and requires an
access code (cookie set by opening /?t=<code> once); requests from this PC stay free.
Static files never leave the dist folder; routes without a file extension fall back to
index.html (Angular routing).
"""

import hmac
import json
import secrets
import socket
from functools import partial
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import SplitResult, parse_qs, unquote, urlencode, urlsplit, urlunsplit

from vagas_bot.config import Settings
from vagas_bot.dashboard import data
from vagas_bot.dashboard.benchmark_job import ALREADY_RUNNING, BenchmarkJob
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


TOKEN_COOKIE = "vb_token"
TOKEN_MAX_AGE_S = 365 * 24 * 3600
DENIED_HTML = (
    "<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
    "<title>vagas-pj-bot</title><body style='font-family:system-ui;padding:24px'>"
    "<h1>Acesso restrito</h1><p>Abra o link com o código de acesso que o comando "
    "<code>vagas_bot dashboard --lan</code> mostra no terminal do PC.</p></body>"
)


def load_or_create_token(path: Path) -> str:
    """Access code for LAN mode, kept across restarts so the phone bookmark keeps working."""
    if path.is_file() and (token := path.read_text(encoding="utf-8").strip()):
        return token
    token = secrets.token_urlsafe(16)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token, encoding="utf-8")
    return token


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "vagas-bot-dashboard"

    def __init__(
        self, *args: Any, settings: Settings, dist: Path, benchmark: BenchmarkJob, token: str | None = None,
        trust_local: bool = True,
        **kwargs: Any,
    ) -> None:
        self.settings = settings
        self.dist = dist.resolve()
        self.benchmark = benchmark
        self.token = token
        self.trust_local = trust_local
        super().__init__(*args, **kwargs)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 — assinatura da stdlib
        log.debug("%s %s", self.address_string(), format % args)

    # --- acesso pela rede local ---

    def _authorized(self) -> bool:
        """No token (localhost mode) or a local request: free. Else the cookie must match."""
        if self.token is None or (self.trust_local and self.client_address[0] in ("127.0.0.1", "::1")):
            return True
        cookies = SimpleCookie(self.headers.get("Cookie") or "")
        sent = cookies[TOKEN_COOKIE].value if TOKEN_COOKIE in cookies else ""
        return hmac.compare_digest(sent, self.token)

    def _guard(self, url: SplitResult) -> bool:
        """True = go on. Handles ?t=<token> (sets the cookie and redirects) and denials."""
        if self.token is not None:
            query = parse_qs(url.query)
            given = (query.pop("t", None) or [""])[0]
            if given and hmac.compare_digest(given, self.token):
                clean = urlunsplit(("", "", url.path, urlencode(query, doseq=True), ""))
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", clean or "/")
                self.send_header("Set-Cookie", f"{TOKEN_COOKIE}={self.token}; Max-Age={TOKEN_MAX_AGE_S}; "
                                               "Path=/; HttpOnly; SameSite=Strict")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return False
        if self._authorized():
            return True
        if url.path.startswith("/api/"):
            self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "Acesso restrito: abra o link com o código de acesso."})
        else:
            body = DENIED_HTML.encode("utf-8")
            self.send_response(HTTPStatus.UNAUTHORIZED)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        return False

    # --- roteamento ---

    def do_GET(self) -> None:  # noqa: N802 — nome exigido pela stdlib
        url = urlsplit(self.path)
        if not self._guard(url):
            return
        if url.path.startswith("/api/"):
            query = parse_qs(url.query)
            routes = {
                "/api/jobs": lambda: data.job_rows(self.settings),
                "/api/benchmark/runs": lambda: data.benchmark_runs(self.settings),
                "/api/benchmark/models": lambda: data.benchmark_models(self.settings),
                "/api/benchmark/status": lambda: self.benchmark.status(),
                "/api/benchmark": lambda: data.benchmark_payload(self.settings, (query.get("run") or [None])[0]),
            }
            handler = routes.get(url.path)
            self._api(handler if handler else _not_found)
            return
        self._static(url.path)

    def do_PUT(self) -> None:  # noqa: N802
        url = urlsplit(self.path)
        if not self._authorized():
            self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "Acesso restrito: abra o link com o código de acesso."})
            return
        prefix = "/api/labels/"
        if not url.path.startswith(prefix) or len(url.path) == len(prefix):
            self._api(_not_found)
            return
        job_id = unquote(url.path[len(prefix):])
        self._api(lambda: data.save_label(self.settings, job_id, self._json_body()))

    def do_POST(self) -> None:  # noqa: N802
        url = urlsplit(self.path)
        if not self._authorized():
            self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "Acesso restrito: abra o link com o código de acesso."})
            return
        # CSRF: um <form> de outro site só envia text/plain e similares, e o navegador marca a origem
        media_type = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if media_type != "application/json":
            self._send_json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "Envie JSON (Content-Type: application/json)."})
            return
        if self.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none"):
            self._send_json(HTTPStatus.FORBIDDEN, {"error": "Origem não permitida."})
            return
        if url.path != "/api/benchmark/run":
            self._api(_not_found)
            return
        self._api(self._start_benchmark, status=HTTPStatus.ACCEPTED)

    def _start_benchmark(self) -> dict[str, Any]:
        if self.benchmark.status()["state"] == "running":
            raise DashboardError(409, ALREADY_RUNNING)
        return self.benchmark.start(data.validate_benchmark_models(self.settings, self._json_body()))

    # --- API ---

    def _json_body(self) -> Any:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            raise DashboardError(413, "Corpo grande demais.")
        try:
            return json.loads(self.rfile.read(length) or b"null")
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise DashboardError(400, "JSON inválido.") from exc

    def _api(self, produce: Any, status: int = HTTPStatus.OK) -> None:
        try:
            self._send_json(status, produce())
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


def make_server(
    settings: Settings, dist: Path, host: str = "127.0.0.1", port: int = 8765, token: str | None = None,
    trust_local: bool = True, benchmark: BenchmarkJob | None = None,
) -> ThreadingHTTPServer:
    """token=None: localhost only, no code. With a token (LAN mode), other devices need it."""
    job = benchmark if benchmark is not None else BenchmarkJob(settings)  # um só por servidor: todas as abas veem a mesma rodada
    handler = partial(DashboardHandler, settings=settings, dist=dist, benchmark=job, token=token,
                      trust_local=trust_local)
    return ThreadingHTTPServer((host, port), handler)


def lan_addresses() -> list[str]:
    """Private IPv4 addresses of this PC (to print the phone URL). Sends no packets."""
    found: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))  # endereço de documentação: só escolhe a interface de saída
            found.append(probe.getsockname()[0])
    except OSError:
        pass
    try:
        found += socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        pass
    private = [ip for ip in dict.fromkeys(found) if ip.startswith(("192.168.", "10."))]
    return private or [ip for ip in dict.fromkeys(found) if not ip.startswith("127.")]
