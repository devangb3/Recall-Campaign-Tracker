# PLAN.md: Sanket's work

Source: Linear project "Recall Campaign Tracker" and the code on `main`, last updated 8 Nov 2026. All tickets below are assigned to Sanket. REC-25, REC-27 and REC-26 are merged to `main`. The REC-28 branch has `main` merged in and also carries two review fixes: the "data loaded" header (D-21, from the REC-25 review) and the affected-list and date-format fixes (D-24, from the REC-27 review).

## Where the project stands

- Done and merged: generator, ingest into `recall.db`, contract package, check engine, pipeline, storage, CLI and the local JSON API (REC-7, 9, 10, 13, 16 to 23, 29, 30, 33). Architecture notes are in `docs/architecture/overview.md`.
- The UI is built from scratch in `ui/` (plain HTML/CSS/JS). REC-25 (flags view, with the static route in `api.py`) is merged to `main`. REC-27 and REC-26 were stacked and are merged too; REC-28 is the last UI branch.
- REC-32 (tiny sample `recall.db`, Julian) is still Todo. Not needed: generate your own (see SETUP.md).
- Withdrawn after the 4 Nov meeting: REC-5, 6, 8, 11, 14, 15, 24. `docs/plan.md` still describes that old model, so ignore it.

## Sanket's tickets

| Ticket | Title | Due | Status |
|---|---|---|---|
| REC-25 | Show notification, repair and data-quality flags | 6 Nov (ignored, D-2) | Done, merged |
| REC-26 | Show check history | 6 Nov (ignored, D-2) | Done, merged |
| REC-27 | Show vehicle detail and the coordinator's decision | 6 Nov (ignored, D-2) | Done, merged |
| REC-28 | Export the report to PDF | 9 Nov (ignored, D-2) | Built and committed on `feature/rec-28-export-the-report-to-pdf` (3 commits ahead of `main`), PR next |
| REC-12 | Write the stakeholder business deck | 5 Nov (ignored, D-2) | First draft built: `presentation/2_recall_tracker_followup_deck.html` (D-27), for review |

The "keep the current UI, do not redesign" wording in the tickets is leftover: no UI existed, so there was nothing to preserve.

## Rules that apply to every ticket

- Notification and repair findings are equal. No ranking, no priority order.
- Bad or missing data goes in a separate list with a reason. A bad notice date is a data issue, never "not notified".
- A failed load (HTTP 422) shows the error plainly. Never show an empty or partial findings list.
- Nothing on screen contacts an owner or edits a source record.
- Render `raw_row` and `tech_note` as plain text only. A hostile note is planted in the test data.
- Out of scope: current owner, central-body status, resale, returns, other dealers.

## What the API already gives you

`GET /api/report` returns `{run_id, ingest_id, loaded_at, report}` (`loaded_at` is when the CSVs were read, shown in the header, D-21). `report` has:

- `findings`: notification and repair findings (vin, campaign_id, kind, reason, check_date, facts), in check order.
- `data_quality`: per-vehicle findings of kind "data quality" (for example a notice for a vehicle not in the affected file).
- `data_issues`: quarantined or flagged rows (file, src_row, issue_code, action, reason, raw_row; vin and campaign_id null when unreadable). This feeds REC-25's separate list.
- `history`, `decisions`: for REC-26.
- `vehicles`: per pair detail (in_notices, notice_date_used, repair_date_used, inclusive_days, day_limit, on_time, decision, data_quality_reasons, facts). `facts.affected` is empty for a vehicle outside the affected list. This is REC-27.

Writes: `POST /api/day-limit`, `/api/decisions`, `/api/checks`, `/api/recheck`. Also `GET /api/runs`, `/api/runs/<id>`, `/api/history`, `/api/settings`.

Gaps: no pagination or filtering in the API (filters are client-side), no PDF endpoint (print-to-PDF instead), and each day-limit change saves a new run. The server serves `ui/` and needs no CORS (same origin).

## Decisions

Logged in [DECISIONS.md](DECISIONS.md) (D-1 to D-24): serve the UI from the backend, history filters, decision date handling, two-notice-date display, `raw_row` handling, error display, print-to-PDF and its contents, the load-time header, date formats, deck format.

## Plan (prerequisite order, due dates ignored)

### Step 1: scaffold (done, merged with REC-25)
Static route in `api.py` (`static_file`), `ui/` folder, tests in `tests/test_api.py`.

### Step 2: REC-25 flags view (done, merged)
Also added: summary cards by count, a "Run check" button, the dealership name in the header (D-17), sticky-header tables that scroll.
- Findings list: vin, campaign_id, kind, reason, in payload order.
- Separate data-issue panel from `data_issues` (and `data_quality` shown clearly as its own group).
- Day-limit control posting to `POST /api/day-limit`, re-render from the returned report, value persists.
- 422 state with the exact message, for example "Cannot run check: notices_sent.csv was not found. Nothing was changed."

### Step 3: REC-27 vehicle detail (done, merged, see D-20)
Open from a finding or data-quality row. From `vehicles`: in notices file, notice date used, repair date used, inclusive days, day limit, current decision, `data_quality_reasons`. Decision form (reviewed, follow up, no action, optional note) posting to `/api/decisions`, then refresh.

### Step 4: REC-26 history view (done, merged, see D-22)
Read-only table from `history` and `decisions`: check date, kind, reason, day limit, decision status and note. Filters (D-5): VIN search, campaign, kind, check date range, current decision (including none), day limit. Done after REC-27 so decisions exist to show. Latest decision is current, earlier ones stay visible. Optional drill-in to a saved run via `/api/runs/<id>`.

### Step 5: REC-28 PDF export (built, see D-23)
"Export PDF" opens a dialog to choose the parts (findings, missing and bad data, vehicle detail, saved runs, every saved check, decisions). A print-only copy is built from the loaded report with a cover band, five large number cards, page numbers and the data problems kept apart; the person chooses Save as PDF in the print dialog. Disabled when no report is loaded. Review fixes on this branch: the "data loaded" header in the viewer's time zone as ET (D-21, D-24), an "In affected list" fact with no day count for unaffected vehicles, and ISO dates everywhere (D-24).

### Step 6: REC-12 stakeholder deck (first draft built, D-27)
Content is fully specified in the ticket (one coordinator, one dealership, three CSVs, two equal findings, 60-day inclusive rule with the 1 Jan / 1 Mar / 2 Mar example, adjustable limit, data-issue flag, stop-on-bad-file, decisions and history kept, out-of-scope list, no contact and no source edits). 15 minutes, three presenters, no branding, figures from the seed-42 run (D-11). Done last so it can use the finished app.

## Open questions

Everything from the first round is answered (see DECISIONS.md). Still open:

1. Who presents which part of the deck?
2. REC-34 (Improvement, Backlog): client asked for a "Repair on an unaffected vehicle" flag, defined by model and build-date eligibility. That conflicts with REC-21 (affected list only) and the data has no model or build date. Needs answers from the client before any work (see the ticket). Today's `NOT_IN_AFFECTED` data issue already covers a repair for a pair not in the affected list.
3. Data-issue list filters by file and issue code (D-8) were not built. Add them only if the coordinator needs them.
