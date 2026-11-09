# SETUP.md

Local setup for the Recall Campaign Tracker (macOS, zsh).

## 1. Prerequisites

- Python 3.12 or newer. CI runs 3.12. Your machine has 3.15, which is fine, but if something fails only locally, try 3.12 first.
- Git.
- No other dependencies. The app uses only the standard library (SQLite, `http.server`). `pytest` is the only package.

## 2. Create a virtual environment and install

```bash
cd ~/Documents/GitHub/Recall-Campaign-Tracker
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

Run `source .venv/bin/activate` in every new terminal. `.venv/`, `data/` and `*.db` are already in `.gitignore`, so generated data and databases never get committed.

## 3. Check the install

```bash
python -m pytest        # whole suite, about 8 seconds (UI browser tests are skipped without Chrome)
```

## 4. Make data and a database

```bash
# 500 synthetic vehicles, three CSVs (seed 42, as-of 2026-11-01)
python -m recall_tracker.generate --out data/raw

# Load them, run both checks, print the report as JSON
python -m recall_tracker check --raw data/raw --db data/recall.db --as-of 2026-11-01
```

`data/raw` and `data/recall.db` may already exist on your machine (the folder is not in git). Re-running adds a new ingest and run; it never deletes earlier ones. To start clean, delete `data/recall.db`.

For a small fixture (about 60 vehicles): `python -m recall_tracker.generate --out data/sample --seed 7 --vehicles 60`.

## 5. Start the local API (what the UI talks to)

```bash
python -m recall_tracker serve --db data/recall.db --raw data/raw --port 8000
```

It listens on `127.0.0.1` only. Try it:

```bash
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/api/report
curl http://127.0.0.1:8000/api/settings
curl -X POST http://127.0.0.1:8000/api/day-limit \
  -H 'Content-Type: application/json' -d '{"day_limit": 61}'
curl -X POST http://127.0.0.1:8000/api/decisions \
  -H 'Content-Type: application/json' \
  -d '{"vin":"VIN_FROM_REPORT","campaign_id":"RC-2026-001","status":"follow up","note":"Check repair"}'
```

Routes: `POST /api/checks`, `/api/recheck`, `/api/day-limit`, `/api/decisions`; `GET /api/report`, `/api/runs`, `/api/runs/<id>`, `/api/history`, `/api/settings`, `/healthz`. A missing or unreadable CSV returns 422 with only `error`.

The same server also serves the coordinator UI from `ui/` at `http://127.0.0.1:8000/` (GET only, .html/.css/.js files under `ui/` only). It is the same origin as the API, so no CORS headers are needed. Open that URL in a browser; on a fresh database choose "Run check".

## 6. Other CLI commands

```bash
python -m recall_tracker recheck --db data/recall.db --day-limit 61
python -m recall_tracker report  --db data/recall.db [--run-id 1]
python -m recall_tracker runs    --db data/recall.db
python -m recall_tracker decide  --db data/recall.db --vin <VIN> --campaign-id <ID> --status 'follow up' --note '...'
```

Exit code 2 means an unusable input file; nothing was changed.

## 7. Look inside the database

```bash
sqlite3 data/recall.db '.tables'
sqlite3 data/recall.db 'select * from cur_data_issues limit 10;'
```

Read the latest ingest through the `cur_<table>` views, not the base tables.

## 8. Working on the UI / PDF tickets (REC-25 to REC-28)

The UI lives in `ui/` (plain HTML, CSS and JS, no build step) and is built ticket by ticket on stacked branches. REC-25 (flags view), REC-27 (vehicle detail and decisions) and REC-26 (check history, `#/history`) are merged; REC-28 (PDF export: the "Export PDF" button, then choose Save as PDF in the print dialog) is built; REC-12 (deck) is next. The header shows when the CSVs were last read (`loaded_at`, in your time zone as ET), because a reload or day-limit Apply reuses that data. Page numbers in the PDF footer need a recent Chrome. To try the UI without touching `data/recall.db`, use a scratch copy: `python -m recall_tracker check --raw data/raw --db data/test.db`, then `serve --db data/test.db`. The client name is the `DEALERSHIP_NAME` constant in `ui/app.js` (also in the page title in `ui/index.html`). Edit the files and reload the browser; no restart is needed because static files are read on every request (restart only for `api.py` changes). Build against the API above and the payload from `recall_tracker.contract.to_dict` (shape in `recall_tracker/contract/serialize.py`). Do not invent new shapes. Render `raw_row` and any `tech_note` as plain text, never HTML. For how the pieces fit together read `docs/architecture/overview.md`; `docs/plan.md` is outdated. See [PLAN.md](PLAN.md) for the work plan and open questions.

## Troubleshooting

- `No module named pytest`: the venv is not active, or you skipped step 2.
- Port 8000 busy: pass a different `--port`.
- Stale or odd data: delete `data/recall.db` and run `check` again.
