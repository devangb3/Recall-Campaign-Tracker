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
from urllib.parse import urlsplit

from . import pipeline
from .contract import Decision, DecisionStatus, to_dict
from .contract.validate import require_day_limit
from .ingest import IngestStopError
from .storage import SavedRun


def run_dict(run: SavedRun) -> dict:
    """Run identity around the unchanged, JSON-ready report contract."""
    return {"run_id": run.run_id, "ingest_id": run.ingest_id,
            "report": to_dict(run.report)}


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

    def _request(self, method: str, path: str, body: object) -> tuple[int, dict]:
        if method == "GET":
            if path == "/healthz":
                return 200, {"status": "ok"}
            if path == "/api/settings":
                return 200, pipeline.settings(self.db_path)
            if path == "/api/report":
                return 200, run_dict(pipeline.current_report(self.db_path))
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
                return 200, run_dict(pipeline.saved_run(self.db_path, run_id))
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
                return 201, run_dict(run)
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


def make_server(db_path: Path | str, raw_dir: Path | str, *,
                host: str = "127.0.0.1", port: int = 8000
                ) -> ThreadingHTTPServer:
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

        def do_GET(self) -> None:
            self._send(*app.request("GET", self.path))

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
