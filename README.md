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

## Part 3: the coordinator UI

```bash
python3 -m recall_tracker serve --db data/recall.db --raw data/raw --port 8000
```

Open <http://127.0.0.1:8000/>. The same server serves the UI from `ui/` (plain
HTML, CSS and JavaScript, no build step) and the JSON API below, so there is
one origin and no CORS. On a new database choose **Run check** to load the
three CSVs. The page has three views:

- **Flags:** counts, then notification and repair findings (equal weight, no
  ranking), then "Missing and bad data" with data issues and vehicle
  data-quality flags kept apart, each with a reason. The repair day limit
  control (default 60) recalculates the loaded data and the choice persists.
- **Vehicle detail** (click a VIN): whether the vehicle is on the affected
  list and in the notices file, the notice and repair dates the check used,
  inclusive days, the limit and result, every date on file, data problems, and
  the coordinator decision form (`reviewed`, `follow up`, `no action`, optional
  note) with the decision history. A vehicle outside the affected list gets no
  day count.
- **Check history:** every saved run, every saved check and every decision,
  with filters (VIN, campaign, kind, check date range, current decision, day
  limit).

**Export PDF** asks which parts to include and opens the browser's print
dialog; choose "Save as PDF". If an input file is missing or unreadable the
page shows only the error (HTTP 422), hides the findings and disables the
export. After such an error a reload or a day-limit change reuses the last
good data, so the header always says when the CSVs were read ("Data loaded
from files on ..."; shown in the viewer's time zone). The UI never contacts
owners or edits source records, and shows every value from the API as plain
text.

## API for the recall coordinator UI

The server defaults to `127.0.0.1`. `GET /` and the `.html`, `.css` and `.js`
files under `ui/` are served as static files (GET only); everything under
`/api/` is JSON. A different front end can call the API directly or call
`recall_tracker.api.Application.request` from an existing Python app adapter.
The report contract does not change.

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
`loaded_at` (when the CSV files behind the run were read, UTC) and `report`;
the `report` is the existing `contract.to_dict` payload. A reload or a
`/api/day-limit` change reuses the loaded data, so `loaded_at` stays the
same until the CSVs are read again.
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

`tests/test_ui.py` checks the coordinator UI. Its source checks always run.
Its browser checks open the page in headless Chrome against a real server and
checked data, and are skipped when Chrome is not installed (set `CHROME_BIN`
to use a specific binary).
