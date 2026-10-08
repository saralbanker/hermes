"""Read-only Hermes dashboard (FastAPI). Run with `uvicorn dashboard.app:create_app --factory`.

No login: the service binds 127.0.0.1 and is reached from the phone only through
`tailscale serve` (tailnet-only). Two guards stay in place instead of a token:
  * a Host-header allowlist (localhost, 127.0.0.1, *.ts.net) against DNS-rebinding from a
    malicious website open in the owner's browser;
  * an X-Requested-With header on the timer POSTs, which a cross-site request cannot set
    without a CORS preflight (and no CORS is offered).

Environment:
    HERMES_DASH_ALLOWED_HOSTS  optional extra comma-separated Host names to accept
    HERMES_DB_PATH             optional override of db/applications.db (used by tests)
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from dashboard import controls
from dashboard.queries import build_overview, open_readonly

logger = logging.getLogger(__name__)

CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "hermes-dashboard"
DEFAULT_ALLOWED_HOSTS = ("localhost", "127.0.0.1", "*.ts.net")
STATIC_INDEX = Path(__file__).resolve().parent / "static" / "index.html"
STATIC_CHART_JS = Path(__file__).resolve().parent / "static" / "chart.umd.min.js"
# The page uses small inline <script>/<style> blocks (API strings are only ever set via
# textContent), so 'unsafe-inline' is needed; everything else is locked to this origin.
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'unsafe-inline'; "
    "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'none'"
)


def require_csrf_header(request: Request) -> None:
    """Dependency for POSTs: require the X-Requested-With guard header."""
    if request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise HTTPException(status_code=403, detail="Missing X-Requested-With header")


def _allowed_hosts() -> list[str]:
    extra = [h.strip() for h in os.environ.get("HERMES_DASH_ALLOWED_HOSTS", "").split(",") if h.strip()]
    return [*DEFAULT_ALLOWED_HOSTS, *extra]


def _safe_timer_status() -> dict[str, object]:
    """timer_status that degrades to an error entry instead of failing the page."""
    try:
        return controls.timer_status()
    except controls.TimerControlError as exc:
        logger.error("timer_status failed: %s", exc)
        return {"error": str(exc)}


def _overview_payload(app: FastAPI) -> dict:  # type: ignore[type-arg]
    conn = open_readonly(app.state.db_path)
    try:
        data = build_overview(conn, date.today().isoformat(), app.state.repo_root)
    finally:
        conn.close()
    return {
        **data,
        "generated_at": datetime.now().astimezone().isoformat(),
        "timer": _safe_timer_status(),
    }


def _run_timer_action(action: str) -> dict[str, object]:
    """Pause or resume the timer, returning fresh status; errors become HTTP 500."""
    try:
        (controls.pause_timer if action == "pause" else controls.resume_timer)()
        return controls.timer_status()
    except controls.TimerControlError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _run_timer_status() -> dict[str, object]:
    try:
        return controls.timer_status()
    except controls.TimerControlError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _register_routes(app: FastAPI) -> None:
    @app.get("/")
    def index() -> Response:
        if not STATIC_INDEX.is_file():
            return PlainTextResponse("Not found", status_code=404)
        return FileResponse(STATIC_INDEX, media_type="text/html")

    @app.get("/chart.js")
    def chart_js() -> Response:
        return FileResponse(STATIC_CHART_JS, media_type="text/javascript")

    @app.get("/api/overview")
    def overview() -> dict:  # type: ignore[type-arg]
        return _overview_payload(app)

    @app.get("/api/timer")
    def get_timer() -> dict[str, object]:
        return _run_timer_status()

    @app.post("/api/timer/pause", dependencies=[Depends(require_csrf_header)])
    def pause() -> dict[str, object]:
        return _run_timer_action("pause")

    @app.post("/api/timer/resume", dependencies=[Depends(require_csrf_header)])
    def resume() -> dict[str, object]:
        return _run_timer_action("resume")


def create_app() -> FastAPI:
    """App factory."""
    repo_root = Path(__file__).resolve().parents[2]
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.repo_root = repo_root
    app.state.db_path = Path(os.environ.get("HERMES_DB_PATH") or repo_root / "db" / "applications.db")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_allowed_hosts())
    _register_routes(app)
    return app
