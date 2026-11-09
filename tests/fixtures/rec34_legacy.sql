-- Historical database produced by the pre-REC-34 CLI (610747c).
BEGIN TRANSACTION;
CREATE TABLE affected_vehicles (
    ingest_id   INTEGER NOT NULL REFERENCES ingests(ingest_id),
    src_file    TEXT NOT NULL,
    src_row     INTEGER NOT NULL,
    vin         TEXT NOT NULL,
    campaign_id TEXT NOT NULL,
    UNIQUE (ingest_id, vin, campaign_id),
    PRIMARY KEY (ingest_id, src_file, src_row)
);
INSERT INTO "affected_vehicles" VALUES(1,'affected_vehicles.csv',2,'SYNTEST06A0000001','RC-2026-001');
CREATE TABLE check_history (
        history_id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL REFERENCES check_runs(run_id),
        vin TEXT NOT NULL,
        campaign_id TEXT NOT NULL,
        check_date TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (
            kind IN ('notification', 'repair', 'data quality')),
        reason TEXT NOT NULL,
        day_limit INTEGER NOT NULL CHECK (day_limit > 0)
    );
INSERT INTO "check_history" VALUES(1,1,'SYNTEST06A0000001','RC-2026-001','2026-11-01','repair','Repair on 2026-03-02 took 61 inclusive days from notice on 2026-01-01, exceeding the 60-day limit.',60);
INSERT INTO "check_history" VALUES(2,1,'SYNTEST06A0000001','RC-2026-001','2026-11-01','data quality','Repair date 2025-12-31 is before the first notice date 2026-01-01.',60);
INSERT INTO "check_history" VALUES(3,1,'SYNTEST06A0000001','RC-2026-001','2026-11-01','data quality','Repair dates conflict for this vehicle and campaign: 2025-12-31 (row 2) and 2026-03-02 (row 3).',60);
CREATE TABLE check_runs (
        run_id INTEGER PRIMARY KEY AUTOINCREMENT,
        ingest_id INTEGER NOT NULL REFERENCES ingests(ingest_id),
        check_date TEXT NOT NULL,
        day_limit INTEGER NOT NULL CHECK (day_limit > 0),
        saved_at TEXT NOT NULL,
        report_json TEXT NOT NULL
    );
INSERT INTO "check_runs" VALUES(1,1,'2026-11-01',60,'2026-11-09T01:16:40.817374+00:00','{"check_date":"2026-11-01","day_limit":60,"findings":[{"vin":"SYNTEST06A0000001","campaign_id":"RC-2026-001","kind":"repair","reason":"Repair on 2026-03-02 took 61 inclusive days from notice on 2026-01-01, exceeding the 60-day limit.","check_date":"2026-11-01","facts":{"affected":[{"vin":"SYNTEST06A0000001","campaign_id":"RC-2026-001"}],"notices":[{"vin":"SYNTEST06A0000001","campaign_id":"RC-2026-001","notice_date":"2026-01-01"}],"repairs":[{"vin":"SYNTEST06A0000001","campaign_id":"RC-2026-001","repair_date":"2025-12-31"},{"vin":"SYNTEST06A0000001","campaign_id":"RC-2026-001","repair_date":"2026-03-02"}]}}],"data_quality":[{"vin":"SYNTEST06A0000001","campaign_id":"RC-2026-001","kind":"data quality","reason":"Repair date 2025-12-31 is before the first notice date 2026-01-01.","check_date":"2026-11-01","facts":{"affected":[{"vin":"SYNTEST06A0000001","campaign_id":"RC-2026-001"}],"notices":[{"vin":"SYNTEST06A0000001","campaign_id":"RC-2026-001","notice_date":"2026-01-01"}],"repairs":[{"vin":"SYNTEST06A0000001","campaign_id":"RC-2026-001","repair_date":"2025-12-31"},{"vin":"SYNTEST06A0000001","campaign_id":"RC-2026-001","repair_date":"2026-03-02"}]}},{"vin":"SYNTEST06A0000001","campaign_id":"RC-2026-001","kind":"data quality","reason":"Repair dates conflict for this vehicle and campaign: 2025-12-31 (row 2) and 2026-03-02 (row 3).","check_date":"2026-11-01","facts":{"affected":[{"vin":"SYNTEST06A0000001","campaign_id":"RC-2026-001"}],"notices":[{"vin":"SYNTEST06A0000001","campaign_id":"RC-2026-001","notice_date":"2026-01-01"}],"repairs":[{"vin":"SYNTEST06A0000001","campaign_id":"RC-2026-001","repair_date":"2025-12-31"},{"vin":"SYNTEST06A0000001","campaign_id":"RC-2026-001","repair_date":"2026-03-02"}]}}],"data_issues":[{"file":"repairs_done.csv","src_row":2,"issue_code":"REPAIR_BEFORE_NOTICE","action":"kept","reason":"Repair date 2025-12-31 is before the first notice date 2026-01-01.","raw_row":"{\"vin\": \"SYNTEST06A0000001\", \"campaign_id\": \"RC-2026-001\", \"repair_date\": \"2025-12-31\", \"tech_note\": \"Original note.\"}","vin":"SYNTEST06A0000001","campaign_id":"RC-2026-001"},{"file":"repairs_done.csv","src_row":3,"issue_code":"DATE_CONFLICT","action":"kept","reason":"Repair dates conflict for this vehicle and campaign: 2025-12-31 (row 2) and 2026-03-02 (row 3).","raw_row":"{\"vin\": \"SYNTEST06A0000001\", \"campaign_id\": \"RC-2026-001\", \"repair_date\": \"2026-03-02\", \"tech_note\": \"Late repair.\"}","vin":"SYNTEST06A0000001","campaign_id":"RC-2026-001"}],"decisions":[],"history":[{"vin":"SYNTEST06A0000001","campaign_id":"RC-2026-001","check_date":"2026-11-01","kind":"repair","reason":"Repair on 2026-03-02 took 61 inclusive days from notice on 2026-01-01, exceeding the 60-day limit.","day_limit":60},{"vin":"SYNTEST06A0000001","campaign_id":"RC-2026-001","check_date":"2026-11-01","kind":"data quality","reason":"Repair date 2025-12-31 is before the first notice date 2026-01-01.","day_limit":60},{"vin":"SYNTEST06A0000001","campaign_id":"RC-2026-001","check_date":"2026-11-01","kind":"data quality","reason":"Repair dates conflict for this vehicle and campaign: 2025-12-31 (row 2) and 2026-03-02 (row 3).","day_limit":60}],"vehicles":[{"vin":"SYNTEST06A0000001","campaign_id":"RC-2026-001","in_notices":true,"notice_date_used":"2026-01-01","repair_date_used":"2026-03-02","inclusive_days":61,"day_limit":60,"on_time":false,"decision":null,"data_quality_reasons":["Repair date 2025-12-31 is before the first notice date 2026-01-01.","Repair dates conflict for this vehicle and campaign: 2025-12-31 (row 2) and 2026-03-02 (row 3)."],"facts":{"affected":[{"vin":"SYNTEST06A0000001","campaign_id":"RC-2026-001"}],"notices":[{"vin":"SYNTEST06A0000001","campaign_id":"RC-2026-001","notice_date":"2026-01-01"}],"repairs":[{"vin":"SYNTEST06A0000001","campaign_id":"RC-2026-001","repair_date":"2025-12-31"},{"vin":"SYNTEST06A0000001","campaign_id":"RC-2026-001","repair_date":"2026-03-02"}]}}]}');
CREATE TABLE coordinator_decisions (
        decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
        vin TEXT NOT NULL,
        campaign_id TEXT NOT NULL,
        status TEXT NOT NULL CHECK (
            status IN ('reviewed', 'follow up', 'no action')),
        note TEXT,
        decided_on TEXT NOT NULL,
        saved_at TEXT NOT NULL
    );
INSERT INTO "coordinator_decisions" VALUES(1,'SYNTEST06A0000001','RC-2026-001','reviewed','Original decision.','2026-11-01','2026-11-09T01:16:40.865257+00:00');
CREATE TABLE data_issues (
    issue_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    ingest_id   INTEGER NOT NULL REFERENCES ingests(ingest_id),
    file        TEXT NOT NULL,
    src_row     INTEGER NOT NULL,
    "column"    TEXT NOT NULL,
    raw_value   TEXT NOT NULL,
    issue_code  TEXT NOT NULL CHECK (issue_code IN ('MISSING_VALUE', 'BAD_VIN', 'BAD_DATE', 'BAD_CAMPAIGN', 'FUTURE_DATE', 'DUPLICATE_ROW', 'DATE_CONFLICT', 'REPAIR_BEFORE_NOTICE', 'NOT_IN_AFFECTED')),
    action      TEXT NOT NULL CHECK (action IN ('dropped_duplicate', 'kept', 'quarantined')),
    reason      TEXT NOT NULL,
    vin         TEXT,
    campaign_id TEXT,
    raw_row     TEXT NOT NULL
);
INSERT INTO "data_issues" VALUES(1,1,'repairs_done.csv',2,'repair_date','2025-12-31','REPAIR_BEFORE_NOTICE','kept','Repair date 2025-12-31 is before the first notice date 2026-01-01.','SYNTEST06A0000001','RC-2026-001','{"vin": "SYNTEST06A0000001", "campaign_id": "RC-2026-001", "repair_date": "2025-12-31", "tech_note": "Original note."}');
INSERT INTO "data_issues" VALUES(2,1,'repairs_done.csv',3,'repair_date','2026-03-02','DATE_CONFLICT','kept','Repair dates conflict for this vehicle and campaign: 2025-12-31 (row 2) and 2026-03-02 (row 3).','SYNTEST06A0000001','RC-2026-001','{"vin": "SYNTEST06A0000001", "campaign_id": "RC-2026-001", "repair_date": "2026-03-02", "tech_note": "Late repair."}');
CREATE TABLE ingests (
    ingest_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    as_of_date  TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status = 'complete'),
    files       TEXT NOT NULL,   -- JSON: name -> {sha256, rows}
    row_counts  TEXT NOT NULL    -- JSON: name -> raw/clean/quarantined/...
);
INSERT INTO "ingests" VALUES(1,'2026-11-09T01:16:40+00:00','2026-11-09T01:16:40+00:00','2026-11-01','complete','{"affected_vehicles.csv": {"rows": 1, "sha256": "9a4f3f8dd3301159b6897f2cde2c5e7ed9da8de93f5aa7c4d41463863d7cb68e"}, "notices_sent.csv": {"rows": 1, "sha256": "e96f120690f970a873a40bdc2305a9c45c4d68572adf1db48281ce04e1502e71"}, "repairs_done.csv": {"rows": 2, "sha256": "8d312e6c298baf94602f8172588128e115d148a32f23ee89978c49f0ecaece65"}}','{"affected_vehicles.csv": {"clean": 1, "dropped_duplicate": 0, "quarantined": 0, "raw": 1}, "notices_sent.csv": {"clean": 1, "dropped_duplicate": 0, "quarantined": 0, "raw": 1}, "repairs_done.csv": {"clean": 2, "dropped_duplicate": 0, "quarantined": 0, "raw": 2}}');
CREATE TABLE notices_sent (
    ingest_id   INTEGER NOT NULL REFERENCES ingests(ingest_id),
    src_file    TEXT NOT NULL,
    src_row     INTEGER NOT NULL,
    vin         TEXT NOT NULL,
    campaign_id TEXT NOT NULL,
    notice_date TEXT NOT NULL,
    PRIMARY KEY (ingest_id, src_file, src_row)
);
INSERT INTO "notices_sent" VALUES(1,'notices_sent.csv',2,'SYNTEST06A0000001','RC-2026-001','2026-01-01');
CREATE TABLE quarantine (
    ingest_id   INTEGER NOT NULL REFERENCES ingests(ingest_id),
    file        TEXT NOT NULL,
    src_row     INTEGER NOT NULL,
    raw_json    TEXT NOT NULL,
    issue_codes TEXT NOT NULL,
    PRIMARY KEY (ingest_id, file, src_row)
);
CREATE TABLE repairs_done (
    ingest_id   INTEGER NOT NULL REFERENCES ingests(ingest_id),
    src_file    TEXT NOT NULL,
    src_row     INTEGER NOT NULL,
    vin         TEXT NOT NULL,
    campaign_id TEXT NOT NULL,
    repair_date TEXT NOT NULL,
    tech_note   TEXT NOT NULL,
    PRIMARY KEY (ingest_id, src_file, src_row)
);
INSERT INTO "repairs_done" VALUES(1,'repairs_done.csv',2,'SYNTEST06A0000001','RC-2026-001','2025-12-31','Original note.');
INSERT INTO "repairs_done" VALUES(1,'repairs_done.csv',3,'SYNTEST06A0000001','RC-2026-001','2026-03-02','Late repair.');
CREATE TABLE tracker_settings (
        setting_key TEXT PRIMARY KEY CHECK (setting_key = 'day_limit'),
        setting_value INTEGER NOT NULL CHECK (setting_value > 0)
    );
CREATE VIEW cur_affected_vehicles AS SELECT * FROM affected_vehicles WHERE ingest_id = (SELECT MAX(ingest_id) FROM ingests WHERE status = 'complete');
CREATE VIEW cur_notices_sent AS SELECT * FROM notices_sent WHERE ingest_id = (SELECT MAX(ingest_id) FROM ingests WHERE status = 'complete');
CREATE VIEW cur_repairs_done AS SELECT * FROM repairs_done WHERE ingest_id = (SELECT MAX(ingest_id) FROM ingests WHERE status = 'complete');
CREATE VIEW cur_data_issues AS SELECT * FROM data_issues WHERE ingest_id = (SELECT MAX(ingest_id) FROM ingests WHERE status = 'complete');
CREATE VIEW cur_quarantine AS SELECT * FROM quarantine WHERE ingest_id = (SELECT MAX(ingest_id) FROM ingests WHERE status = 'complete');
CREATE INDEX check_history_pair
        ON check_history(vin, campaign_id, history_id);
CREATE INDEX check_runs_ingest
        ON check_runs(ingest_id, run_id);
CREATE INDEX coordinator_decisions_pair
        ON coordinator_decisions(vin, campaign_id, decision_id);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('ingests',1);
INSERT INTO "sqlite_sequence" VALUES('data_issues',2);
INSERT INTO "sqlite_sequence" VALUES('check_runs',1);
INSERT INTO "sqlite_sequence" VALUES('check_history',3);
INSERT INTO "sqlite_sequence" VALUES('coordinator_decisions',1);
COMMIT;
