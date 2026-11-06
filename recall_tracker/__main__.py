"""Commands for checking the dealership files and serving the report API."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

from .api import make_server, run_dict
from .contract import Decision, DecisionStatus
from .ingest import IngestStopError
from .pipeline import (
    current_report, recheck, record_decision, run_check, run_summaries, saved_run,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
            ("check", "Load the three CSVs and save their check results"),
            ("recheck", "Recalculate loaded data without reading the CSVs"),
            ("report", "Read the latest report, or an original saved run"),
            ("runs", "List all saved runs"),
            ("decide", "Append the coordinator's decision"),
            ("serve", "Serve the JSON API for the coordinator UI")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--db", type=Path, default=Path("data/recall.db"))
        if name in ("check", "serve"):
            command.add_argument("--raw", type=Path, default=Path("data/raw"))
        if name in ("check", "recheck"):
            command.add_argument("--as-of", type=date.fromisoformat,
                                 help="Check date, YYYY-MM-DD")
            command.add_argument("--day-limit", type=int,
                                 help="Persist a positive inclusive repair-day limit")
        if name == "report":
            command.add_argument("--run-id", type=int,
                                 help="Read an immutable original run instead of current decisions")
        if name == "decide":
            command.add_argument("--vin", required=True)
            command.add_argument("--campaign-id", required=True)
            command.add_argument("--status", required=True,
                                 choices=[s.value for s in DecisionStatus])
            command.add_argument("--note")
            command.add_argument("--on", type=date.fromisoformat, default=date.today())
        if name == "serve":
            command.add_argument("--host", default="127.0.0.1")
            command.add_argument("--port", type=int, default=8000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "check":
            value = run_dict(run_check(args.raw, args.db,
                                      check_date=args.as_of, day_limit=args.day_limit))
        elif args.command == "recheck":
            value = run_dict(recheck(args.db, check_date=args.as_of,
                                    day_limit=args.day_limit))
        elif args.command == "report":
            run = (current_report(args.db) if args.run_id is None
                   else saved_run(args.db, args.run_id))
            value = run_dict(run)
        elif args.command == "runs":
            value = {"runs": [{"run_id": r.run_id, "ingest_id": r.ingest_id,
                               "check_date": r.check_date.isoformat(),
                               "day_limit": r.day_limit} for r in run_summaries(args.db)]}
        elif args.command == "decide":
            note = None if args.note is None else args.note.strip() or None
            decision = Decision(args.vin, args.campaign_id,
                                DecisionStatus(args.status), note, args.on)
            value = {"decision_id": record_decision(args.db, decision)}
        else:
            server = make_server(args.db, args.raw, host=args.host, port=args.port)
            print(f"Recall report API: http://{args.host}:{server.server_port}",
                  file=sys.stderr, flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
            return 0
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0
    except (IngestStopError, ValueError, LookupError, sqlite3.Error, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
