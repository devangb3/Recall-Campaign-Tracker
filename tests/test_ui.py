"""Checks on the coordinator UI in ``ui/``.

Two layers:

* Source checks run everywhere. They guard the rules the UI must keep (no
  HTML injection, no inline script, every element the script looks up exists).
* Browser checks open the page in headless Chrome against a real server and
  real checked data, then read the rendered page. They are skipped when Chrome
  is not installed (set ``CHROME_BIN`` to point at one).

The browser checks read the page after it has loaded. Clicks (saving a
decision, the export dialog) are covered by the API tests and by hand.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import urllib.request
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

import pytest

from recall_tracker.api import Application, UI_DIR, make_server, static_file

APP_JS = (UI_DIR / "app.js").read_text(encoding="utf-8")
# Code without // and /* */ comments, so a comment that says "never innerHTML"
# is not mistaken for a use of it.
APP_CODE = re.sub(r"/\*.*?\*/|(?<![:\"'])//[^\n]*", "", APP_JS, flags=re.S)
INDEX = (UI_DIR / "index.html").read_text(encoding="utf-8")
STYLE = (UI_DIR / "style.css").read_text(encoding="utf-8")


# --- Source checks -----------------------------------------------------------

def test_ui_never_builds_html_from_data():
    """API values (raw_row, tech_note) are data; only textContent may show them."""
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write",
                   "eval(", "new Function", "dangerouslySetInnerHTML"):
        assert banned not in APP_CODE, banned


def test_page_is_allowed_by_the_content_security_policy():
    """The server sends default-src 'self': no inline script, style or handler."""
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", INDEX)
    assert not re.search(r"<style\b", INDEX)
    assert not re.search(r"\sstyle\s*=", INDEX)
    assert not re.search(r"\son[a-z]+\s*=", INDEX)
    assert "style.display" not in APP_CODE and ".style." not in APP_CODE


def test_every_element_the_script_looks_up_exists():
    ids_in_html = set(re.findall(r'\bid="([^"]+)"', INDEX))
    looked_up = set(re.findall(r'\$\("([^"]+)"\)', APP_JS))
    looked_up |= set(re.findall(r'getElementById\("([^"]+)"\)', APP_JS))
    assert looked_up, "expected the script to look up elements"
    assert looked_up - ids_in_html == set()


def test_linked_files_are_served():
    for target in re.findall(r'(?:href|src)="(/[^"]+)"', INDEX):
        assert static_file(UI_DIR, target) is not None, target


def test_page_title_and_header_use_the_one_client_name():
    name = re.search(r'const DEALERSHIP_NAME = "([^"]+)"', APP_JS).group(1)
    assert name in re.search(r"<title>(.*?)</title>", INDEX).group(1)


def js_function(name: str) -> str:
    """The source of one top-level function in app.js."""
    start = APP_CODE.index(f"function {name}(")
    end = APP_CODE.find("\nfunction ", start + 1)
    return APP_CODE[start:end if end != -1 else len(APP_CODE)]


@pytest.mark.parametrize("name", ["showError", "showNoCheckYet", "render"])
def test_old_print_copy_is_cleared_whenever_the_screen_changes(name):
    """Ctrl+P must never print an earlier export after an error or new data."""
    assert "clearPrintCopy()" in js_function(name)


def test_clearing_the_print_copy_empties_the_print_only_element():
    body = js_function("clearPrintCopy")
    assert '$("print-report")' in body and "replaceChildren()" in body


def test_pdf_says_when_the_files_changed_and_export_waits_for_readable_files():
    assert "input_check" in js_function("render")
    assert "input_check" in js_function("buildPrintReport")


def test_stylesheet_braces_balance():
    assert STYLE.count("{") == STYLE.count("}")


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_script_has_valid_syntax():
    result = subprocess.run(["node", "--check", str(UI_DIR / "app.js")],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_no_control_can_contact_owners_or_edit_sources():
    """The only requests the UI makes are the documented coordinator actions."""
    sent = set(re.findall(r'api\("(?:POST|PUT|PATCH|DELETE)",\s*"([^"]+)"', APP_JS))
    assert sent <= {"/api/checks", "/api/day-limit", "/api/decisions"}
    # The UI shows each decision's date but never sends one (the server uses today).
    assert not re.search(r"\bdecided_on\s*:", APP_CODE)
    assert "body.decided_on" not in APP_CODE


# --- Browser checks ----------------------------------------------------------

def find_chrome() -> str | None:
    candidates = [os.environ.get("CHROME_BIN"),
                  shutil.which("google-chrome"), shutil.which("google-chrome-stable"),
                  shutil.which("chromium"), shutil.which("chromium-browser"),
                  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    return next((c for c in candidates if c and Path(c).exists()), None)


CHROME = find_chrome()
needs_chrome = pytest.mark.skipif(CHROME is None, reason="Chrome is not installed")


class Dom(HTMLParser):
    """The rendered page: text and table rows by element id."""

    def __init__(self, source: str):
        super().__init__(convert_charrefs=True)
        self.text: dict[str, list[str]] = {}
        self.rows: dict[str, int] = {}
        self.attrs: dict[str, dict] = {}
        self.scripts = 0
        self.images = 0
        self._stack: list[tuple[str, str | None]] = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script":
            self.scripts += 1
        if tag == "img":
            self.images += 1
        if tag in ("br", "img", "input", "meta", "link", "hr"):
            return
        element_id = attrs.get("id")
        if element_id:
            self.attrs[element_id] = attrs
        self._stack.append((tag, element_id))
        if tag == "tr":
            for _, open_id in self._stack:
                if open_id:
                    self.rows[open_id] = self.rows.get(open_id, 0) + 1

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                del self._stack[i:]
                break

    def handle_data(self, data):
        for _, open_id in self._stack:
            if open_id:
                self.text.setdefault(open_id, []).append(data)

    def words(self, element_id: str) -> str:
        return re.sub(r"\s+", " ", " ".join(self.text.get(element_id, []))).strip()

    def body_rows(self, element_id: str) -> int:
        return max(self.rows.get(element_id, 0) - 1, 0)  # minus the header row

    def is_hidden(self, element_id: str) -> bool:
        return "hidden" in self.attrs.get(element_id, {})


def serve(db_path: Path, raw: Path):
    server = make_server(db_path, raw, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


@pytest.fixture(scope="module")
def site(small_dir, tmp_path_factory):
    """A server over a database with one real check of the seed-7 data."""
    root = tmp_path_factory.mktemp("ui_site")
    raw = root / "raw"
    shutil.copytree(small_dir, raw)
    db = root / "recall.db"
    status, _ = Application(db, raw).request(
        "POST", "/api/checks", {"check_date": "2026-11-01"})
    assert status == 201
    server, base = serve(db, raw)
    yield base
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module")
def empty_site(tmp_path_factory):
    """A server that has never run a check."""
    root = tmp_path_factory.mktemp("ui_empty")
    server, base = serve(root / "none.db", root)
    yield base
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module")
def broken_site(small_dir, tmp_path_factory):
    """A checked database whose notices file has since gone missing."""
    root = tmp_path_factory.mktemp("ui_broken")
    raw = root / "raw"
    shutil.copytree(small_dir, raw)
    db = root / "recall.db"
    assert Application(db, raw).request(
        "POST", "/api/checks", {"check_date": "2026-11-01"})[0] == 201
    (raw / "notices_sent.csv").unlink()
    server, base = serve(db, raw)
    yield base
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module")
def changed_site(small_dir, tmp_path_factory):
    """A checked database whose notices file was edited after the check."""
    root = tmp_path_factory.mktemp("ui_changed")
    raw = root / "raw"
    shutil.copytree(small_dir, raw)
    db = root / "recall.db"
    assert Application(db, raw).request(
        "POST", "/api/checks", {"check_date": "2026-11-01"})[0] == 201
    notices = raw / "notices_sent.csv"
    notices.write_text(notices.read_text() + "SYN00000000000000,RC-2026-001,01/01/2026\n")
    server, base = serve(db, raw)
    yield base
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module")
def run(site):
    with urllib.request.urlopen(site + "/api/report") as response:
        return json.load(response)


def render(base: str, route: str = "", tz: str = "America/New_York") -> Dom:
    """Open the page in headless Chrome and return it once it has rendered."""
    profile = Path(os.environ.get("TMPDIR", "/tmp")) / f"recall-ui-chrome-{os.getpid()}"
    result = subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
         f"--user-data-dir={profile}", "--virtual-time-budget=4000", "--dump-dom",
         f"{base}/{route}"],
        capture_output=True, text=True, timeout=60, env={**os.environ, "TZ": tz})
    shutil.rmtree(profile, ignore_errors=True)
    assert result.returncode == 0, result.stderr[-400:]
    return Dom(result.stdout)


def vehicle_route(view: dict) -> str:
    return f"#/vehicle/{view['vin']}/{view['campaign_id']}"


def affected(view: dict) -> bool:
    return len(view["facts"]["affected"]) > 0


@needs_chrome
def test_flags_page_lists_what_the_report_holds(site, run):
    report = run["report"]
    page = render(site)
    header = page.words("summary")
    assert f"check date {report['check_date']}" in header
    assert f"run {run['run_id']}" in header
    assert f"repair limit {report['day_limit']} days" in header
    assert page.body_rows("findings") == len(report["findings"])
    assert page.body_rows("data-issues") == len(report["data_issues"])
    assert page.body_rows("data-quality") == len(report["data_quality"])
    stats = page.words("stats")
    kinds = [f["kind"] for f in report["findings"]]
    assert f"{kinds.count('notification')} Notification findings" in stats
    assert f"{kinds.count('repair')} Repair findings" in stats
    assert not page.is_hidden("report")
    assert "disabled" not in page.attrs["export-pdf"]


@needs_chrome
def test_header_shows_the_load_time_in_the_viewers_zone(site):
    page = render(site, tz="America/New_York")
    assert re.search(r"Data loaded from files on \d{4}-\d{2}-\d{2} \d{2}:\d{2} ET ·",
                     page.words("summary"))


@needs_chrome
def test_a_new_database_says_no_check_has_run(empty_site):
    page = render(empty_site)
    assert "No check has been run yet" in page.words("message")
    assert page.is_hidden("report")
    assert "disabled" in page.attrs["export-pdf"]


@needs_chrome
def test_detail_shows_on_time_and_late_with_the_inclusive_day_count(site, run):
    views = [v for v in run["report"]["vehicles"] if affected(v) and v["repair_date_used"]]
    on_time = next(v for v in views if v["on_time"] is True)
    late = next(v for v in views if v["on_time"] is False)
    for view, label in ((on_time, "On time"), (late, "Late")):
        text = render(site, vehicle_route(view)).words("detail")
        assert view["vin"] in text and view["campaign_id"] in text
        assert f"Repair result {label}" in text
        assert f"Inclusive days, notice to repair {view['inclusive_days']}" in text
        assert f"Day limit {view['day_limit']} days" in text


@needs_chrome
def test_vehicle_outside_the_affected_list_shows_no_day_count(site, run):
    view = next(v for v in run["report"]["vehicles"] if not affected(v) and v["in_notices"])
    text = render(site, vehicle_route(view)).words("detail")
    assert "In affected list No" in text
    assert "Not applicable (not in the affected list)" in text
    assert "Days since notice" not in text and "Inclusive days" not in text
    assert "No notification or repair finding for this vehicle." in text


@needs_chrome
def test_repair_with_no_repair_counts_to_the_check_date(site, run):
    view = next(v for v in run["report"]["vehicles"]
                if affected(v) and v["notice_date_used"] and not v["repair_date_used"])
    text = render(site, vehicle_route(view)).words("detail")
    assert f"Days since notice {view['inclusive_days']}" in text
    assert f"counted to the check date {run['report']['check_date']}" in text
    assert "No repair on or after the notice" in text


@needs_chrome
def test_bad_notice_date_is_a_data_problem_not_a_missing_notice(site, run):
    view = next(v for v in run["report"]["vehicles"]
                if affected(v) and v["in_notices"] and v["notice_date_used"] is None)
    text = render(site, vehicle_route(view)).words("detail")
    assert "In notices file Yes" in text
    assert "No usable notice date" in text
    assert "Data problems (not findings)" in text
    assert "No notice is on file" not in text


@needs_chrome
def test_dates_in_reasons_show_as_iso_and_invalid_ones_stay(site, run):
    report = run["report"]
    us_date = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")

    def real_dates(text):
        found = []
        for month, day, year in us_date.findall(text):
            try:
                date(int(year), int(month), int(day))
                found.append((f"{year}-{month}-{day}", f"{month}/{day}/{year}"))
            except ValueError:
                pass
        return found

    # A real MM/DD/YYYY date in a data-quality reason shows as YYYY-MM-DD.
    flag = next(f for f in report["data_quality"] if real_dates(f["reason"]))
    iso, us = real_dates(flag["reason"])[0]
    text = render(site, f"#/vehicle/{flag['vin']}/{flag['campaign_id']}").words("detail")
    assert iso in text and us not in text
    assert iso in render(site).words("data-quality")

    # A value that is not a real date is the problem, so it stays as written.
    known = {(v["vin"], v["campaign_id"]) for v in report["vehicles"]}
    bad = next(d for d in report["data_issues"]
               if d["issue_code"] == "BAD_DATE" and (d["vin"], d["campaign_id"]) in known)
    written = us_date.search(bad["reason"]).group(0)
    assert written in render(site, f"#/vehicle/{bad['vin']}/{bad['campaign_id']}").words("detail")


@needs_chrome
def test_history_view_lists_runs_checks_decisions_and_filters(site, run):
    page = render(site, "#/history")
    assert not page.is_hidden("history")
    assert page.is_hidden("report")
    text = page.words("history")
    assert "Saved runs" in text and "Coordinator decisions (0)" in text
    assert page.body_rows("history") >= 1
    count = re.search(r"Showing (\d+) of (\d+) matching checks \((\d+) saved in total\)", text)
    assert count and int(count.group(3)) == len(run["report"]["history"])
    for label in ("VIN contains", "Campaign", "Kind", "Check date from",
                  "Current decision", "Day limit used", "Clear filters"):
        assert label in text


@needs_chrome
def test_hostile_text_in_the_data_is_never_turned_into_elements(site):
    """The seed data plants a hostile technician note; it must stay text."""
    page = render(site)
    assert page.scripts == 1  # only the page's own script tag
    assert page.images == 0



@needs_chrome
def test_after_a_file_error_a_reload_cannot_pass_for_a_current_report(broken_site, run):
    page = render(broken_site)
    banner = page.words("input-warning")
    assert not page.is_hidden("input-warning")
    assert "notices_sent.csv" in banner
    assert "last good report" in banner
    assert "Data loaded from files" in page.words("summary")
    assert "disabled" in page.attrs["export-pdf"]
    assert page.body_rows("print-report") == 0


@needs_chrome
def test_changed_files_are_flagged_and_export_stays_available(changed_site):
    page = render(changed_site)
    banner = page.words("input-warning")
    assert "notices_sent.csv" in banner and "Run check" in banner
    assert "disabled" not in page.attrs["export-pdf"]


@needs_chrome
def test_matching_files_show_no_warning(site):
    page = render(site)
    assert page.is_hidden("input-warning")
    assert page.words("input-warning") == ""
