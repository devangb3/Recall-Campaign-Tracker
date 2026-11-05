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

## Running the tests

```bash
python3 -m pip install -r requirements.txt
python3 -m pytest            # whole suite, about 1 second
python3 -m pytest -v         # one line per test
python3 -m pytest tests/test_plant.py -k date_conflict   # a subset
```
