# Recall-Campaign-Tracker

See the [architecture overview](docs/architecture/overview.md) for the data
flow, module responsibilities, checks, storage, and CLI/API behavior.

## Part 1: synthetic data

Generate the three dealership CSVs (seed 42, as-of 2026-11-01, about 500 vehicles):

```bash
python3 -m recall_tracker.generate --out data/raw
```

Options: `--seed`, `--as-of YYYY-MM-DD`, `--vehicles`, `--out`. The folder gets
`affected_vehicles.csv`, `notices_sent.csv`, `repairs_done.csv`, plus
`planted_issues.csv` (every planted bad row, used only by the tests) and
`manifest.json` (seed, as-of date, row counts, SHA-256 of each file).

## Part 1: load the CSVs into recall.db

```bash
python3 -m recall_tracker.ingest --raw data/raw --db data/recall.db --as-of 2026-11-01
```

- If any of the three files is missing, unreadable, empty, or lacks a required
  column, ingest stops with a clear error naming the file and changes nothing
  (exit code 2).
- Safe fixes (VIN case, spaces and hyphens, loose campaign ids, ISO or US
  dates) are silent. Anything else gets an issue code and a plain reason in
  `data_issues`; quarantined rows also go to `quarantine` with the whole raw row.
- Every run is a new ingest. The `cur_<table>` views show the latest one; older
  ingests are kept.
- `--as-of` defaults to today. Dates after it are `FUTURE_DATE`.

## Part 2: run the tracker

Load all three CSVs, run both checks, save the run, and print the report as JSON:

```bash
python3 -m recall_tracker check --raw data/raw --db data/recall.db --as-of 2026-11-01
```

The checks use accepted SQLite rows, not a CSV parser. Both
walk the same affected vehicle-campaign pairs. A notice with a bad date is
reported as a data issue. Conflicting dates and repairs before notice remain separate data-quality flags.

The repair limit defaults to **60 inclusive days**. Notice on January 1,
2026 and repair on March 1 is day 60 (on time); March 2 is day 61 (late).
The earliest notice starts the clock and the earliest repair on or after
it closes the clock. No usable notice date means no repair clock.

Change the limit and recalculate the **already loaded data**, without
needing the CSVs again:

```bash
python3 -m recall_tracker recheck --db data/recall.db --day-limit 61
python3 -m recall_tracker report --db data/recall.db
python3 -m recall_tracker runs --db data/recall.db
python3 -m recall_tracker report --db data/recall.db --run-id 1
```

The chosen limit persists across restarts and subsequent uploads. Recheck
keeps the displayed check date; pass `--as-of YYYY-MM-DD` to check loaded
data at a later date. To check an earlier date, reload the CSVs with that
as-of date so future rows are validated correctly.

Record a coordinator decision using a VIN and campaign from the report:

```bash
python3 -m recall_tracker decide --db data/recall.db \
  --vin 'VIN_FROM_REPORT' --campaign-id RC-2026-001 \
  --status 'follow up' --note 'Review the repair evidence.'
```

Statuses are `reviewed`, `follow up`, and `no action`. Notes are optional.
New decisions keep all earlier decisions, including same-day changes.
`report` shows current decisions and complete check history; `report
--run-id` returns the original saved snapshot. New uploads never erase
earlier runs or decisions. There are no automatic decisions.

A run uses **one SQLite transaction** for the ingest, selected limit,
findings, and report. An unusable file stops before any database write,
with the file and problem on stderr and exit code 2. An unexpected failure
rolls back the whole run. Source CSVs and repair records are never edited.

## API for the recall coordinator UI

```bash
python3 -m recall_tracker serve --db data/recall.db --raw data/raw --port 8000
```

The server defaults to `127.0.0.1`. The UI can proxy `/api/` to this local
server or call `recall_tracker.api.Application.request` from an existing
Python app adapter. The existing UI need not change its report contract.

- `POST /api/checks`: ingest the configured CSV folder and save a run.
- `POST /api/recheck`: check the loaded data again.
- `POST /api/day-limit`: save `{"day_limit": 61}` and return the recalculated report.
- `POST /api/decisions`: append `vin`, `campaign_id`, `status`, and optional
  `note` and `decided_on` (`YYYY-MM-DD`).
- `GET /api/report`: current report with latest decisions and full history.
- `GET /api/runs`: saved-run metadata; `GET /api/runs/1`: original run snapshot.
- `GET /api/history`: all saved check rows and coordinator decisions.
- `GET /api/settings`: the saved repair-day limit (60 before a selection).
- `GET /healthz`: server health.

POST requests use `Content-Type: application/json`. Check/recheck requests
accept optional `check_date` (`YYYY-MM-DD`) and `day_limit` (a positive
integer). Successful checks return status 201 with `run_id`, `ingest_id`,
and `report`; the `report` is the existing `contract.to_dict` payload.
File errors return status 422 with only `error`, so a failed load cannot
look like an empty successful findings list. Invalid choices return 400.


## Running the tests

The application uses Python's standard library, including SQLite and the
HTTP server. `requirements.txt` pins the test runner; `requirements-dev.txt`
reuses that same list for development and CI.

```bash
python3 -m pip install -r requirements.txt
python3 -m pytest            # whole suite, a few seconds
python3 -m pytest -v         # one line per test
python3 -m pytest tests/test_plant.py -k date_conflict   # a subset
```
