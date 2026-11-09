# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
python3 -m pip install -r requirements.txt -r requirements-dev.txt
python3 -m pytest                                          # whole suite (~8s with Chrome, ~2s without); CI runs this on Python 3.12
python3 -m pytest tests/test_plant.py -k date_conflict     # a subset
python3 -m recall_tracker.generate --out data/raw          # options: --seed (42), --as-of YYYY-MM-DD (2026-11-01), --vehicles (500)
python3 -m recall_tracker.ingest --raw data/raw --db data/recall.db --as-of 2026-11-01   # exit code 2 = stopped, nothing changed
```

There is no linter or build step configured, and `pytest` is the only dependency (everything else is stdlib). `pytest.ini` puts the repo root and `tests/` on `pythonpath`. `README.md` documents the CLI and API routes, and `docs/architecture/overview.md` explains the architecture and data flow (current; unlike `docs/plan.md`). `SETUP.md` is the local setup guide and `PLAN.md` holds the UI/PDF work plan and open questions.

## What this project is

A recall-campaign checker for one dealership and one Recall Coordinator. It flags vehicles and reports on them. It must never contact owners or modify source records. Repair `tech_note` text is displayed only and is never treated as instructions (the generator plants a hostile note to test this).

On `main` today: the synthetic-data generator, ingest into SQLite (`recall.db`), the `recall_tracker/contract/` package, and the check engine (`snapshot`, `affected`, `checks`, `pipeline`, `storage`) with a CLI and a local JSON API (`api.py`). There was no UI to preserve: the coordinator UI is built from scratch in `ui/` (plain HTML/CSS/JS, no build step), ticket by ticket on stacked branches. REC-25 (flags view, day-limit control, error state), REC-27 (vehicle detail with decisions) and REC-26 (check history) are merged to `main`. PDF export by browser print (REC-28) is built on `feature/rec-28-export-the-report-to-pdf` with two review fixes (D-21, D-24) and waits for its PR. The stakeholder deck (REC-12) is next. The UI consumes the API and the contract payload.

Work is tracked as Linear tickets (project "Recall Campaign Tracker", keys `REC-n`), not in files in the repo. Decisions are logged in `DECISIONS.md`. The UI/PDF tickets (REC-25 to REC-28) and the stakeholder deck (REC-12) are assigned to Sanket.

## Source of truth: Linear tickets and code over docs/plan.md

`docs/plan.md` is **outdated**. It describes three sources (manufacturer, dealer, central body), a fixed 60-day mailing rule and an unset repair limit X. The client meeting of 4 Nov 2026 replaced that, and the Linear tickets and the code follow the new model:

- Three CSVs: `affected_vehicles` (vin, campaign_id), `notices_sent` (vin, campaign_id, notice_date), `repairs_done` (vin, campaign_id, repair_date, tech_note).
- Two equal findings, `notification` and `repair`, with no ranking between them. Notified means the vin and campaign are in the notices file.
- The repair window is inclusive and defaults to 60 days, and the coordinator can change it on screen. Notice 1 Jan 2026 plus repair 1 Mar 2026 is day 60 (on time); 2 Mar is day 61 (late). A vehicle with no repair row after the limit is a repair finding.
- Bad or conflicting data is a separate flag with a reason. It never turns into a "not notified" finding, and quarantined rows with no usable vin or campaign appear in that same data-issue list.
- A missing or unreadable input file stops the run with a clear error (for example "Cannot run check: notices_sent.csv was not found. Nothing was changed."). It must not produce an empty or partial findings list or flag every vehicle.
- Coordinator decisions are `reviewed`, `follow up` or `no action`, with an optional note. Every run and every decision is kept, and a later upload never removes earlier rows.
- Out of scope: returns, resales, other dealers, current owner, central-body status.

## Generator architecture

`generate.py` builds clean rows and orchestrates output. `plant.py` adds the deliberate cases. They are separate on purpose:

- **Business cases** are clean rows the checks must catch (no notice, day 60 vs day 61). They are not data issues.
- **Data issues** are bad or conflicting rows that ingest must flag with an issue code (`MISSING_VALUE`, `BAD_VIN`, `BAD_CAMPAIGN`, `BAD_DATE`, `FUTURE_DATE`, `DUPLICATE_ROW`, `DATE_CONFLICT`, `NOT_IN_AFFECTED`, `REPAIR_BEFORE_NOTICE`). Each is written to `planted_issues.csv` (the mess log) with file, row_num, column, issue_code, action and reason. Row numbers are spreadsheet rows (header is row 1). Ingest must never read the mess log; only the tests do.
- **Safe mess** (lower-case or spaced/hyphenated VINs, loose campaign ids, ISO dates) is applied to background rows only, and ingest fixes it silently, so it is not in the mess log.
- Each planted case uses its own fresh vehicle, so one planted problem cannot cause a second unplanned issue.
- Output is deterministic: the same seed and as-of date give byte-identical files. `manifest.json` records the seed, as-of date, row counts and SHA-256 of each file. Keep this property when changing the generator.
- VINs start with `SYN` and carry a valid check digit (`vin.py`). Dates in the CSVs are written MM/DD/YYYY.

## Tests

`tests/test_ui.py` checks the UI: source rules (no `innerHTML`, no inline script, every `$("id")` exists in `index.html`, only the documented POSTs, `node --check`) always run; browser checks render the page in headless Chrome (`--dump-dom`) against a real server over the seed-7 data and compare it with `/api/report`. They skip without Chrome (`CHROME_BIN`). They read the loaded page only; clicks (save a decision, export dialog, 422 from a click) are not covered, so check those by hand. Add a test here when a UI rule or rendering bug is fixed (D-25).

`tests/conftest.py` holds an independent reference checker (`find_issues`, `ref_vin`, `ref_campaign`, `ref_date`) written separately from the generator. Tests compare what the generator says it planted against what the reference checker finds in the files. When you change planting rules or issue codes, update both sides. The `small_dir` (seed 7, 60 vehicles) and `full_dir` (seed 42, 500 vehicles) fixtures are session-scoped, and `data_dir` runs a test against both.

## Ingest and recall.db

`ingest.py` runs in three steps: read all files (any missing, unreadable, empty or column-short file raises `IngestStopError` before anything is written), validate rows (`normalize.py` does the safe fixes; bad rows are quarantined with an issue code; duplicates dropped; date conflicts, `REPAIR_BEFORE_NOTICE` and `NOT_IN_AFFECTED` are flagged but kept), then load in one transaction. The load must satisfy raw rows = clean + quarantined + dropped duplicates for every file, or it rolls back (`RowBalanceError`).

- Every run adds a new `ingest_id`; older ingests are never deleted. Read the latest through the `cur_<table>` views.
- `src_row` is the spreadsheet row (header is row 1). `tech_note` is stored verbatim and never parsed.
- `tests/test_db_contract.py` pins the table and column names that later parts read. Renaming a column means updating it deliberately.

## UI (`ui/`)

- `app.js` fetches `/api/report` and renders with the `el()` helper (`textContent` only). `DEALERSHIP_NAME` ("Infinachi Auto Repairs") is the one place the client name is set; the page title in `index.html` repeats it.
- Only HTTP 422 (unusable file) hides the findings and shows the error alone. Other errors show a message and leave the screen as it is. A 400 on first load means no check has run yet.
- Vehicle detail is a hash route `#/vehicle/<vin>/<campaign>` rendered by `renderDetail` from the `vehicles` array. Saving a decision posts to `/api/decisions` (no `decided_on`) and reloads `/api/report`. With no repair on file, `inclusive_days` is counted to the check date and `on_time` is null. A vehicle outside the affected list (`facts.affected` empty) shows "In affected list: No", no day count and a result of "Not applicable" (D-24).
- Check history (REC-26) is the hash route `#/history` (`renderHistory`): saved runs from `/api/runs`, every saved check and every decision from the report, filtered client-side. It is read-only (D-22).
- PDF export (REC-28) is the "Export PDF" button: it opens a dialog to choose the parts (`exportChoice`), then `exportPdf` fills `#print-report` (print-only, hidden on screen) from the loaded report and calls `window.print()`. The `@media print` block in `style.css` hides everything else. Disabled when no report is loaded (D-23).
- Dates on screen are ISO (YYYY-MM-DD). Server reason text uses MM/DD/YYYY, so `isoDates` converts real dates when displaying (invalid ones stay as written); the header time is in the viewer's time zone, with the generic zone name (for example ET, never EST/EDT). Vehicles outside the affected list get an "In affected list: No" fact and no day count (D-24).
- API run payloads carry `input_check` (`ok`/`changed`/`unusable`, from `pipeline.input_check`, read-only). `render` shows `#input-warning` for the last two; `unusable` disables Export PDF; `changed` adds a warning to the PDF cover. `clearPrintCopy()` empties `#print-report` in `render`, `showError` and `showNoCheckYet` (D-26).
- The header reads "Data loaded from files on <time>" from `loaded_at`. Reload and the day-limit Apply reuse loaded data and never re-read the CSVs, so after a file error this is the only sign the report is old (D-21).
- Notification and repair are shown with equal weight (no ranking). Data issues and vehicle data-quality flags sit in their own "Missing and bad data" section.
- Visual check: serve a scratch database and screenshot with headless Chrome (`--headless --screenshot`). Do not point it at the real `data/recall.db` when testing error states.

## Presentation (`presentation/`)

One self-contained HTML deck per client meeting (`1_…` first meeting, `2_…` follow-up). 1280x720 slides, keys for next, back, notes (N), fullscreen (F), print (P). Presenters are set in the `PRESENTERS` object in the script. Figures come from the seed-42 sample checked on 2026-11-01; the demo database must use `--as-of 2026-11-01` (D-27).

## Working rules

- Never run git write operations (add, commit, push, branch, merge). Propose the commands and let Sanket run them. Read-only git is fine.
- One branch and one PR per ticket, stacked: each branch is cut from the previous ticket's branch. Check `git branch --show-current` before editing; stop if it does not match the ticket.
- Decisions are logged in `DECISIONS.md`; add an entry when one is made.

## Check pipeline (part 2)

Data flows one way: ingest -> `snapshot.read_snapshot` -> `checks` -> `pipeline` -> `storage` -> `api`/`__main__`.

- `snapshot.py` reads one complete ingest from SQLite into an immutable `IngestSnapshot`. Checks never parse CSVs; ingest is the only parser.
- `affected.py` builds the `AffectedList` once. `check_notifications` and `check_repairs` both receive that same object and must not build their own list.
- `pipeline.py` runs a whole check in one SQLite transaction (ingest, limit, findings, report). An `IngestStopError` aborts before any write; any other failure rolls everything back.
- `storage.py` is append-only: `check_runs`, decisions and the `tracker_settings` day limit. The caller owns the connection and transaction; storage methods never commit.
- `recheck` recalculates already-loaded data with a new day limit without re-reading CSVs. The chosen limit persists.
- CLI: `python3 -m recall_tracker {check,recheck,report,runs,decide,serve}`. Exit 2 means an unusable input file (stderr names the file and problem). The API returns 422 with only `error` for that case so a failed load never looks like an empty findings list.
- `api.py` is stdlib `http.server`, local only (127.0.0.1). It has no owner-contact, source-edit or automatic-decision operation, and should not gain one. The API routes are JSON; the only non-JSON route is GET for the coordinator UI in `ui/` (plain HTML/CSS/JS, no build step; `api.static_file` serves only .html/.css/.js under `ui/`). The UI writes API values with `textContent` only, because `raw_row` can hold a hostile `tech_note`. No CORS headers (same origin). Every `recheck` or day-limit change saves a new run, so history grows. Run payloads add `loaded_at` (the ingest's `finished_at`) next to `report`; the UI header shows it so a reload or day-limit Apply on old data is visible after a file error (D-21).

## Contract package

`recall_tracker/contract/` defines the report payload that the UI and PDF stories consume. It is merged. Build against it rather than inventing new shapes. `serialize.to_dict` is the JSON shape (TypedDicts in `serialize.py`); the report holds `findings` (notification/repair), `data_quality` (per-vehicle findings of kind "data quality"), `data_issues` (quarantined/flagged rows, `vin`/`campaign_id` null when unreadable), `decisions`, `history` and `vehicles` (per-pair detail). `data_quality` and `data_issues` are different lists. Its day count is `(repair_date - notice_date).days + 1`. A repair before the notice does not close the clock, and the clock starts at the earliest notice.
