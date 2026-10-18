"""Local dashboard server: JSON API over the RFQ database, plus the built React app.

GET /api/metrics?source=&days=        totals, daily received/replied, data-source mix
GET /api/requests?source=&days=&limit= recent requests, newest first
GET /api/requests/<id>                 one request with its products
GET /api/requests/<id>/rfq.xlsx        the RFQ workbook that was produced
Anything else serves frontend/dist (single-page app).
"""
import json
import logging
import mimetypes
import re
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app import simulate, store
from app.config import ROOT

log = logging.getLogger(__name__)
DIST = ROOT / "frontend" / "dist"
SOURCES = {"gmail", "file", "api"}


def query_options(query):
    source = query.get("source", [""])[0]
    try:
        days = min(max(int(query.get("days", ["30"])[0]), 1), 365)
        limit = min(max(int(query.get("limit", ["100"])[0]), 1), 500)
    except ValueError:
        raise ValueError("days and limit must be whole numbers")
    if source and source not in SOURCES:
        raise ValueError("source must be gmail, file or api")
    return source or None, days, limit


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIST), **kwargs)

    def log_message(self, fmt, *args):
        log.debug(fmt, *args)

    def send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path.startswith("/api/"):
            try:
                self.api(url)
            except ValueError as exc:
                self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except Exception:
                log.exception("Dashboard API error")
                self.send_json({"error": "Internal error; see the dashboard console"},
                               HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        # Single-page app: unknown paths get index.html so client routes survive a refresh.
        if not (DIST / url.path.lstrip("/")).is_file():
            self.path = "/index.html"
        if not (DIST / "index.html").is_file():
            self.send_json({"error": "Frontend not built. Run: cd frontend; npm install; npm run build"},
                           HTTPStatus.NOT_FOUND)
            return
        super().do_GET()

    def same_origin(self):
        """Only the dashboard page itself may trigger a send: blocks other websites (CSRF)."""
        origin = self.headers.get("Origin")
        if origin is None:
            return True  # not a browser cross-site request (e.g. a local script)
        host = urlparse(origin).hostname
        return host in ("127.0.0.1", "localhost")

    def do_POST(self):
        url = urlparse(self.path)
        decision = re.fullmatch(r"/api/requests/(\d+)/findings/(\d+)", url.path)
        if url.path != "/api/simulate" and not decision:
            return self.send_json({"error": "Unknown endpoint"}, HTTPStatus.NOT_FOUND)
        # JSON-only plus an Origin check: a cross-site form post cannot reach these actions.
        if not self.same_origin() or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            return self.send_json({"error": "Forbidden"}, HTTPStatus.FORBIDDEN)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 64 * 1024:
                return self.send_json({"error": "Request too large"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            payload = json.loads(self.rfile.read(length) or b"{}")
            if decision:
                choice = {"approve": "approved", "reject": "rejected"}.get(payload.get("decision"))
                if not choice:
                    raise ValueError("decision must be approve or reject")
                result = store.decide(int(decision.group(1)), int(decision.group(2)), choice)
                log.info("Reviewer %s finding %s of request %s", choice, decision.group(2), decision.group(1))
                return self.send_json(result)
            result = simulate.send(payload.get("subject"), payload.get("body"), bool(payload.get("attach")))
            log.info("Simulation email sent to %s: %s", result["to"], result["subject"])
            self.send_json(result, HTTPStatus.CREATED)
        except (ValueError, json.JSONDecodeError) as exc:  # SimulationError is a ValueError
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            log.exception("Simulation send failed")
            self.send_json({"error": f"Could not send ({type(exc).__name__}). See the dashboard console."},
                           HTTPStatus.BAD_GATEWAY)

    def api(self, url):
        query = parse_qs(url.query)
        if url.path == "/api/metrics":
            source, days, _ = query_options(query)
            return self.send_json(store.metrics(source, days))
        if url.path == "/api/requests":
            source, days, limit = query_options(query)
            message_id = query.get("message_id", [""])[0][:300] or None
            return self.send_json(store.requests(source, days, limit, message_id))
        if url.path == "/api/simulate/config":
            return self.send_json(simulate.config())
        steps = re.fullmatch(r"/api/requests/(\d+)/trace", url.path)
        if steps:
            data = store.trace(int(steps.group(1)))
            return self.send_json(data) if data is not None else self.send_json({"error": "No trace"}, HTTPStatus.NOT_FOUND)
        match = re.fullmatch(r"/api/requests/(\d+)(/rfq\.xlsx)?", url.path)
        if match and not match.group(2):
            detail = store.request_detail(int(match.group(1)))
            return self.send_json(detail) if detail else self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        if match:
            path = store.workbook_for(int(match.group(1)))
            if not path:
                return self.send_json({"error": "Workbook not available"}, HTTPStatus.NOT_FOUND)
            data = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", mimetypes.types_map.get(".xlsx",
                             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
            self.send_header("Content-Disposition", f'attachment; filename="RFQ-{match.group(1)}.xlsx"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_json({"error": "Unknown endpoint"}, HTTPStatus.NOT_FOUND)


def serve(host="127.0.0.1", port=8000):
    store.connect().close()  # create the database file and tables if this is the first run
    server = ThreadingHTTPServer((host, port), Handler)
    log.info("Dashboard on http://%s:%d  (database: %s)", host, port, store.db_path())
    try:
        server.serve_forever()
    finally:
        server.server_close()
