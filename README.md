# Recall-Campaign-Tracker

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

## Running the tests

```bash
python3 -m pip install -r requirements.txt
python3 -m pytest            # whole suite, about 1 second
python3 -m pytest -v         # one line per test
python3 -m pytest tests/test_plant.py -k date_conflict   # a subset
```
