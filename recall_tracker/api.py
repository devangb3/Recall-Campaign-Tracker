"""Small local JSON API for the existing Recall Coordinator UI.

The API delegates every action to the tool pipeline. It has no owner
outreach, source editing or automatic coordinator-decision operation.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from . import pipeline
from .contract import Decision, DecisionStatus, to_dict
from .contract.validate import require_day_limit
from .ingest import IngestStopError
from .storage import SavedRun


def run_dict(run: SavedRun, loaded_at: str | None = None) -> dict:
    """Run identity around the unchanged, JSON-ready report contract.

    ``loaded_at`` is when the CSV files behind the run were read. It is
    outside the report so the contract payload keeps its shape.
    """
    value = {"run_id": run.run_id, "ingest_id": run.ingest_id,
             "report": to_dict(run.report)}
    if loaded_at is not None:
        value["loaded_at"] = loaded_at
    return value


def _date_field(body: dict, name: str, default: date | None = None
                ) -> date | None:
    if name not in body:
        return default
    value = body[name]
    try:
        if type(value) is not str:
            raise ValueError
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError
        return parsed
    except ValueError as exc:
        raise ValueError(f"{name} must be a date in YYYY-MM-DD format") from exc


def _fields(body: object, allowed: set[str]) -> dict:
    if type(body) is not dict:
        raise ValueError("Request body must be a JSON object")
    unknown = body.keys() - allowed
    if unknown:
        raise ValueError(f"Unknown request field: {sorted(unknown)[0]}")
    return body


def _limit(body: dict) -> int | None:
    return require_day_limit(body["day_limit"]) if "day_limit" in body else None


class Application:
    """Routes usable directly by an app adapter or through the HTTP server."""

    def __init__(self, db_path: Path | str, raw_dir: Path | str):
        self.db_path = Path(db_path)
        self.raw_dir = Path(raw_dir)

    def request(self, method: str, path: str, body: object = None
                ) -> tuple[int, dict]:
        try:
            return self._request(method, urlsplit(path).path, body)
        except IngestStopError as exc:
            # No result accompanies a file error. In particular, never
            # return an empty findings array that could look like success.
            return 422, {"error": str(exc)}
        except LookupError as exc:
            return 404, {"error": str(exc)}
        except (ValueError, TypeError) as exc:
            return 400, {"error": str(exc)}
        except Exception:
            logging.getLogger(__name__).exception("Recall API action failed")
            return 500, {"error": "The action could not be completed; nothing was changed."}

    def _run(self, run: SavedRun) -> dict:
        return run_dict(run, pipeline.ingest_loaded_at(self.db_path, run.ingest_id))

    def _request(self, method: str, path: str, body: object) -> tuple[int, dict]:
        if method == "GET":
            if path == "/healthz":
                return 200, {"status": "ok"}
            if path == "/api/settings":
                return 200, pipeline.settings(self.db_path)
            if path == "/api/report":
                return 200, self._run(pipeline.current_report(self.db_path))
            if path == "/api/runs":
                return 200, {"runs": [{
                    "run_id": run.run_id, "ingest_id": run.ingest_id,
                    "check_date": run.check_date.isoformat(),
                    "day_limit": run.day_limit,
                } for run in pipeline.run_summaries(self.db_path)]}
            if path.startswith("/api/runs/"):
                try:
                    run_id = int(path.removeprefix("/api/runs/"))
                except ValueError as exc:
                    raise ValueError("run_id must be a positive whole number") from exc
                return 200, self._run(pipeline.saved_run(self.db_path, run_id))
            if path == "/api/history":
                report = to_dict(pipeline.current_report(self.db_path).report)
                return 200, {"history": report["history"],
                             "decisions": report["decisions"]}
        elif method == "POST":
            if path in ("/api/checks", "/api/recheck", "/api/day-limit"):
                values = _fields({} if body is None else body,
                                 {"check_date", "day_limit"})
                if path == "/api/day-limit" and "day_limit" not in values:
                    raise ValueError("day_limit is required")
                action = pipeline.run_check if path == "/api/checks" else pipeline.recheck
                arguments = {"check_date": _date_field(values, "check_date"),
                             "day_limit": _limit(values)}
                run = (action(self.raw_dir, self.db_path, **arguments)
                       if path == "/api/checks"
                       else action(self.db_path, **arguments))
                return 201, self._run(run)
            if path == "/api/decisions":
                values = _fields(body, {"vin", "campaign_id", "status", "note",
                                        "decided_on"})
                try:
                    status = DecisionStatus(values.get("status"))
                except ValueError as exc:
                    raise ValueError("status must be reviewed, follow up, or no action") from exc
                note = values.get("note")
                if type(note) is str:
                    note = note.strip() or None
                decision = Decision(
                    values.get("vin"), values.get("campaign_id"), status, note,
                    _date_field(values, "decided_on", date.today()))
                decision_id = pipeline.record_decision(self.db_path, decision)
                return 201, {"decision_id": decision_id}
        return 404, {"error": "API route was not found"}


UI_DIR = Path(__file__).resolve().parent.parent / "ui"
_CONTENT_TYPES = {".html": "text/html; charset=utf-8",
                  ".css": "text/css; charset=utf-8",
                  ".js": "text/javascript; charset=utf-8"}


def static_file(ui_dir: Path | str, url_path: str) -> tuple[bytes, str] | None:
    """Bytes and content type of a UI file, or None when it is not served.

    Only .html, .css and .js files inside ui_dir are served. Anything that
    resolves outside it (for example through ..) is treated as not found.
    """
    root = Path(ui_dir).resolve()
    name = unquote(url_path).lstrip("/") or "index.html"
    try:
        target = (root / name).resolve()
        if (not target.is_relative_to(root) or not target.is_file()
                or target.suffix not in _CONTENT_TYPES):
            return None
        return target.read_bytes(), _CONTENT_TYPES[target.suffix]
    except (OSError, ValueError):
        return None


def make_server(db_path: Path | str, raw_dir: Path | str, *,
                host: str = "127.0.0.1", port: int = 8000,
                ui_dir: Path | str = UI_DIR) -> ThreadingHTTPServer:
    """Create a local server; port=0 is useful for an integration test."""
    app = Application(db_path, raw_dir)

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, value: dict) -> None:
            encoded = (json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

        def _send_static(self, path: str) -> None:
            found = static_file(ui_dir, path)
            if found is None:
                self._send(404, {"error": "File was not found"})
                return
            body, content_type = found
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == "/healthz" or path.startswith("/api/"):
                self._send(*app.request("GET", self.path))
            else:
                self._send_static(path)

        def do_POST(self) -> None:
            try:
                if self.headers.get_content_type() != "application/json":
                    self._send(415, {"error": "Content-Type must be application/json"})
                    return
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0 or length > 1_048_576:
                    self._send(413, {"error": "Request body is too large"})
                    return
                encoded = self.rfile.read(length)
                body = json.loads(encoded) if encoded else None
            except (ValueError, UnicodeError):
                self._send(400, {"error": "Request body must contain valid JSON"})
                return
            self._send(*app.request("POST", self.path, body))

    return ThreadingHTTPServer((host, port), Handler)
