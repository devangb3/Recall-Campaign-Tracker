"use strict";

// Every value from the API is written with textContent, never innerHTML.
// raw_row can hold a repair tech_note, which is data and not markup.

// The one dealership this tracker is for. Change the name here only.
const DEALERSHIP_NAME = "Infinachi Auto Repairs";

const $ = (id) => document.getElementById(id);

// The report currently on screen (as returned by the API).
let current = null;

const STATUSES = ["reviewed", "follow up", "no action"];

function vehicleLink(vin, campaign) {
  const link = el("a", vin, "mono vin-link");
  link.href = `#/vehicle/${encodeURIComponent(vin)}/${encodeURIComponent(campaign)}`;
  return link;
}

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = text;
  if (className) node.className = className;
  return node;
}

async function api(method, path, body) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path, options);
  } catch (err) {
    return { status: 0, data: { error: "Cannot reach the tracker server." } };
  }
  let data;
  try {
    data = await response.json();
  } catch (err) {
    data = { error: "The server sent an unreadable response." };
  }
  return { status: response.status, data };
}

function table(columns, rows, cell) {
  const wrap = el("div", null, "table-wrap");
  const t = el("table");
  const head = el("tr");
  columns.forEach((name) => head.appendChild(el("th", name)));
  t.appendChild(el("thead")).appendChild(head);
  const body = el("tbody");
  rows.forEach((row) => {
    const tr = el("tr");
    cell(row).forEach((value) => {
      const td = el("td");
      if (value instanceof Node) td.appendChild(value);
      else td.textContent = value === null || value === undefined ? "—" : value;
      tr.appendChild(td);
    });
    body.appendChild(tr);
  });
  t.appendChild(body);
  wrap.appendChild(t);
  return wrap;
}

// A data-issue VIN links to the vehicle only when that pair is in the report.
function issueVin(report, d) {
  if (d.vin === null) return "not readable";
  const known = d.campaign_id !== null && report.vehicles.some(
    (v) => v.vin === d.vin && v.campaign_id === d.campaign_id);
  return known ? vehicleLink(d.vin, d.campaign_id) : el("span", d.vin, "mono");
}

function codeCell(d) {
  const box = el("div");
  box.appendChild(el("div", d.issue_code, "nowrap"));
  box.appendChild(el("div", d.action, "hint"));
  return box;
}

function fill(id, node) {
  const target = $(id);
  target.replaceChildren(node);
}

function empty(text) {
  return el("p", text, "empty");
}

function showMessage(text, isError) {
  const box = $("message");
  box.textContent = text;
  box.className = isError ? "error" : "";
  box.hidden = false;
}

function clearMessage() {
  $("message").hidden = true;
  $("message").textContent = "";
}

// A failed load shows only the error. No findings, empty or old, stay on screen.
function showError(text) {
  current = null;
  clearPrintCopy();
  $("input-warning").hidden = true;
  $("export-pdf").disabled = true;
  $("report").hidden = true;
  $("detail").hidden = true;
  $("history").hidden = true;
  $("flagged-repairs").hidden = true;
  showMessage(text, true);
}

function showNoCheckYet() {
  current = null;
  clearPrintCopy();
  $("input-warning").hidden = true;
  $("export-pdf").disabled = true;
  $("report").hidden = true;
  $("detail").hidden = true;
  $("history").hidden = true;
  $("flagged-repairs").hidden = true;
  showMessage("No check has been run yet. Choose “Run check” to load the five CSV files.", false);
}

// When the CSV files were last read. Reload and Apply reuse that data, so
// the header must say how old it is (the files are not re-read on those).
function loadedText(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "at an unknown time";
  // Same year-month-day style as every other date on screen, in the
  // viewer's own time zone. The generic name (ET, not EST or EDT) stays right
  // in both summer and winter time.
  const pad = (n) => String(n).padStart(2, "0");
  const zone = new Intl.DateTimeFormat("en-US", { timeZoneName: "shortGeneric" })
    .formatToParts(d).find((part) => part.type === "timeZoneName");
  return `on ${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}${zone ? ` ${zone.value}` : ""}`;
}

// The server words data problems with the CSV style MM/DD/YYYY. Show real
// dates the way the rest of the screen does (YYYY-MM-DD). A value that is not
// a real date (13/01/2026, 02/30/2026) stays as written: it is the problem.
function isoDates(text) {
  return text.replace(/\b(\d{2})\/(\d{2})\/(\d{4})\b/g, (found, mm, dd, yyyy) => {
    const d = new Date(Date.UTC(+yyyy, +mm - 1, +dd));
    const real = d.getUTCFullYear() === +yyyy && d.getUTCMonth() === +mm - 1 && d.getUTCDate() === +dd;
    return real ? `${yyyy}-${mm}-${dd}` : found;
  });
}

// The print-only copy is built when "Export PDF" is chosen. Throw it away
// whenever the screen changes, so Ctrl+P can never print an earlier export
// after an error or on newer data.
function clearPrintCopy() {
  $("print-report").replaceChildren();
}

// Whether the CSV files still match the loaded data (from the API). Reload
// and the day-limit Apply reuse loaded data and never read the files, so
// after a file error the last good report comes back. Say so, and do not let
// it be exported as if it were current.
function filesNote(inputCheck) {
  if (!inputCheck || inputCheck.state === "ok") return null;
  if (inputCheck.state === "unusable") {
    return `${inputCheck.message} This is the last good report; nothing has been checked again. ` +
      "Fix the files, then choose \u201cRun check\u201d.";
  }
  return `${inputCheck.message} This report is from the earlier data. Choose \u201cRun check\u201d to load the new files.`;
}

function render(result) {
  const report = result.report;
  clearMessage();
  current = result;
  clearPrintCopy();
  const note = filesNote(result.input_check);
  $("input-warning").textContent = note === null ? "" : note;
  $("input-warning").hidden = note === null;
  // An unreadable file means a new check would stop; no PDF of old data then.
  $("export-pdf").disabled = result.input_check !== undefined && result.input_check.state === "unusable";
  $("day-limit").value = report.day_limit;
  $("summary").textContent =
    `Data loaded from files ${loadedText(result.loaded_at)} · check date ${report.check_date} · ` +
    `run ${result.run_id} · repair limit ${report.day_limit} days`;

  const counts = { notification: 0, repair: 0 };
  report.findings.forEach((f) => { counts[f.kind] = (counts[f.kind] || 0) + 1; });
  const stats = $("stats");
  stats.replaceChildren();
  [["Notification findings", counts.notification, "notification"],
   ["Repair findings", counts.repair, "repair"],
   ["Flagged repairs", report.flagged_repairs.length, "repair"],
   ["Data issues", report.data_issues.length, "data"],
   ["Data-quality flags", report.data_quality.length, "data"]].forEach(([label, n, tone]) => {
    const card = el("div", null, `stat ${tone}`);
    card.appendChild(el("span", String(n), "stat-n"));
    card.appendChild(el("span", label, "stat-l"));
    stats.appendChild(card);
  });

  fill("findings", report.findings.length === 0
    ? empty("No findings in this check.")
    : table(["VIN", "Campaign", "Kind", "Reason"], report.findings, (f) =>
        [vehicleLink(f.vin, f.campaign_id), el("span", f.campaign_id, "nowrap"), kindBadge(f.kind), isoDates(f.reason)]));

  fill("data-issues", report.data_issues.length === 0
    ? empty("No data issues.")
    : table(["File and row", "Code and action", "VIN", "Campaign", "Reason", "Raw row"],
        report.data_issues, (d) => {
          const details = el("details");
          details.appendChild(el("summary", "Show"));
          details.appendChild(el("pre", d.raw_row, "mono"));
          return [el("span", `${d.file} \u00b7 row ${d.src_row}`, "nowrap"), codeCell(d),
                  issueVin(report, d),
                  d.campaign_id === null ? "not readable" : el("span", d.campaign_id, "nowrap"),
                  isoDates(d.reason), details];
        }));

  fill("data-quality", report.data_quality.length === 0
    ? empty("No vehicle data-quality flags.")
    : table(["VIN", "Campaign", "Reason"], report.data_quality, (f) =>
        [vehicleLink(f.vin, f.campaign_id), el("span", f.campaign_id, "nowrap"), isoDates(f.reason)]));

  renderFlaggedRepairs(report);
  route();
}

function flaggedRepairCells(f, link) {
  const vehicle = f.facts.vehicle;
  const campaign = f.facts.campaign;
  return [link ? vehicleLink(f.vin, f.campaign_id) : el("span", f.vin, "mono"),
    f.campaign_id, vehicle.model, vehicle.build_date, campaign.model,
    `${campaign.start_date} to ${campaign.end_date}`, "Repair on an unaffected vehicle",
    f.facts.repairs.map((r) => r.repair_date).join(", "), f.reason];
}

const FLAGGED_REPAIR_COLUMNS = ["VIN", "Campaign", "Vehicle model", "Build date",
  "Campaign model", "Build date range (inclusive)", "Flag", "Repair dates", "Reason"];

function renderFlaggedRepairs(report) {
  fill("flagged-repairs-list", report.flagged_repairs.length === 0
    ? empty("No repairs on unaffected vehicles in this check.")
    : table(FLAGGED_REPAIR_COLUMNS, report.flagged_repairs, (f) => flaggedRepairCells(f, true)));
}

// ---- Vehicle detail (REC-27) ------------------------------------------------

// ---- Check history (REC-26) ----------------------------------------------
// Read-only. Shows every saved check result and every decision; it never
// reruns a check or edits anything. Filters work on the report already loaded.

const HISTORY_ROW_LIMIT = 500;
const historyFilters = { vin: "", campaign: "", kind: "", from: "", to: "", decision: "", limit: "" };

function kindBadge(kind) {
  return el("span", kind, `kind kind-${kind === "data quality" ? "data" : kind.replaceAll(" ", "-")}`);
}

// Current decision per vehicle and campaign: latest decided_on, then the
// later record wins. Same rule as the server (contract/decision.py).
function currentDecisions(decisions) {
  const byPair = new Map();
  decisions.forEach((d) => {
    const key = `${d.vin}\u0000${d.campaign_id}`;
    const best = byPair.get(key);
    if (best === undefined || d.decided_on >= best.decided_on) byPair.set(key, d);
  });
  return byPair;
}

function distinct(values) {
  return Array.from(new Set(values)).sort();
}

function filterField(labelText, control) {
  const wrap = el("label", null, "filter");
  wrap.appendChild(el("span", labelText));
  wrap.appendChild(control);
  return wrap;
}

function selectOf(options, value, onChange) {
  const select = el("select");
  options.forEach(([val, text]) => {
    const option = el("option", text);
    option.value = val;
    select.appendChild(option);
  });
  select.value = value;
  select.addEventListener("change", () => onChange(select.value));
  return select;
}

function inputOf(type, value, onChange, placeholder) {
  const input = el("input");
  input.type = type;
  input.value = value;
  if (placeholder) input.placeholder = placeholder;
  input.addEventListener("input", () => onChange(input.value));
  return input;
}

function renderHistory(report) {
  const root = $("history");
  root.replaceChildren();
  const known = new Set(report.vehicles.map((v) => `${v.vin}\u0000${v.campaign_id}`));
  const currentBy = currentDecisions(report.decisions);
  const decisionOf = (row) => currentBy.get(`${row.vin}\u0000${row.campaign_id}`);
  const vehicleCell = (row) => known.has(`${row.vin}\u0000${row.campaign_id}`)
    ? vehicleLink(row.vin, row.campaign_id) : el("span", row.vin, "mono");

  root.appendChild(el("h2", "Check history"));
  root.appendChild(el("p",
    "Every saved check and every coordinator decision. Nothing here reruns a check or changes a record.",
    "section-note"));

  // Saved runs (filled in when /api/runs answers).
  root.appendChild(el("h3", "Saved runs"));
  const runsBox = el("div");
  runsBox.appendChild(empty("Loading saved runs…"));
  root.appendChild(runsBox);
  api("GET", "/api/runs").then(({ status, data }) => {
    if (status !== 200) {
      runsBox.replaceChildren(empty(data.error || "The saved runs could not be loaded."));
      return;
    }
    const runs = data.runs.slice().reverse();
    runsBox.replaceChildren(runs.length === 0 ? empty("No saved runs.") : table(
      ["Run", "Check date", "Repair day limit", "Data load (ingest)"], runs,
      (r) => [r.run_id, r.check_date, r.day_limit, r.ingest_id]));
  });

  // Filters.
  root.appendChild(el("h3", "Findings checked over time"));
  const bar = el("div", null, "filters");
  const results = el("div");
  const count = el("p", null, "hint filter-count");
  const rerun = () => showResults();
  const set = (key) => (value) => { historyFilters[key] = value; rerun(); };
  const all = (text) => ["", text];
  bar.appendChild(filterField("VIN contains", inputOf("search", historyFilters.vin, set("vin"), "e.g. SYN4P")));
  bar.appendChild(filterField("Campaign", selectOf(
    [all("Any")].concat(distinct(report.history.map((h) => h.campaign_id)).map((c) => [c, c])),
    historyFilters.campaign, set("campaign"))));
  bar.appendChild(filterField("Kind", selectOf(
    [all("Any"), ["notification", "notification"], ["repair", "repair"], ["data quality", "data quality"], ["unaffected repair", "Repair on an unaffected vehicle"]],
    historyFilters.kind, set("kind"))));
  bar.appendChild(filterField("Check date from", inputOf("date", historyFilters.from, set("from"))));
  bar.appendChild(filterField("to", inputOf("date", historyFilters.to, set("to"))));
  bar.appendChild(filterField("Current decision", selectOf(
    [all("Any"), ["none", "No decision yet"], ["reviewed", "reviewed"], ["follow up", "follow up"], ["no action", "no action"]],
    historyFilters.decision, set("decision"))));
  bar.appendChild(filterField("Day limit used", selectOf(
    [all("Any")].concat(distinct(report.history.map((h) => h.day_limit)).sort((a, b) => a - b)
      .map((n) => [String(n), String(n)])),
    historyFilters.limit, set("limit"))));
  const clear = el("button", "Clear filters", "secondary");
  clear.type = "button";
  clear.addEventListener("click", () => {
    Object.keys(historyFilters).forEach((k) => { historyFilters[k] = ""; });
    renderHistory(report);
  });
  bar.appendChild(clear);
  root.appendChild(bar);
  root.appendChild(count);
  root.appendChild(results);

  // Newest first; among the same check date the later record comes first.
  const ordered = report.history.slice().reverse()
    .sort((a, b) => (a.check_date < b.check_date ? 1 : a.check_date > b.check_date ? -1 : 0));

  function matches(row) {
    const f = historyFilters;
    if (f.vin.trim() !== "" && !row.vin.toLowerCase().includes(f.vin.trim().toLowerCase())) return false;
    if (f.campaign !== "" && row.campaign_id !== f.campaign) return false;
    if (f.kind !== "" && row.kind !== f.kind) return false;
    if (f.from !== "" && row.check_date < f.from) return false;
    if (f.to !== "" && row.check_date > f.to) return false;
    if (f.limit !== "" && String(row.day_limit) !== f.limit) return false;
    if (f.decision !== "") {
      const d = decisionOf(row);
      if (f.decision === "none" ? d !== undefined : d === undefined || d.status !== f.decision) return false;
    }
    return true;
  }

  function showResults() {
    const rows = ordered.filter(matches);
    const shown = rows.slice(0, HISTORY_ROW_LIMIT);
    count.textContent = `Showing ${shown.length} of ${rows.length} matching checks (${ordered.length} saved in total)` +
      (rows.length > shown.length ? `. Narrow the filters to see the rest.` : ".");
    results.replaceChildren();
    results.appendChild(rows.length === 0
      ? empty(ordered.length === 0 ? "No checks have been saved yet." : "No checks match these filters.")
      : table(["Check date", "VIN", "Campaign", "Kind", "Reason", "Day limit", "Current decision"], shown,
        (h) => {
          const d = decisionOf(h);
          return [el("span", h.check_date, "nowrap"), vehicleCell(h), el("span", h.campaign_id, "nowrap"),
            kindBadge(h.kind), isoDates(h.reason), h.day_limit, d === undefined ? "—" : statusBadge(d.status)];
        }));

    // Decisions follow the VIN and campaign filters. The other filters are about checks.
    const f = historyFilters;
    const decisions = report.decisions.slice().reverse()
      .sort((a, b) => (a.decided_on < b.decided_on ? 1 : a.decided_on > b.decided_on ? -1 : 0))
      .filter((d) => (f.vin.trim() === "" || d.vin.toLowerCase().includes(f.vin.trim().toLowerCase())) &&
        (f.campaign === "" || d.campaign_id === f.campaign));
    results.appendChild(el("h3", `Coordinator decisions (${decisions.length})`));
    results.appendChild(decisions.length === 0
      ? empty(report.decisions.length === 0 ? "No decisions have been recorded yet." : "No decisions match the VIN and campaign filters.")
      : table(["Decided on", "VIN", "Campaign", "Status", "Note"], decisions,
        (d) => [el("span", d.decided_on, "nowrap"), vehicleCell(d), el("span", d.campaign_id, "nowrap"),
          statusBadge(d.status), d.note]));
  }
  showResults();
}

// ---- PDF export (REC-28) --------------------------------------------------
// "Export PDF" asks what to include, fills a print-only copy of the loaded
// report and opens the browser's print dialog; choose "Save as PDF" there.
// Every part uses the same data as the screen, with data problems kept apart.
// It reads only what is already loaded (plus the saved-runs list) and
// contacts no one.

function newestFirst(rows, field) {
  return rows.slice().reverse()
    .sort((a, b) => (a[field] < b[field] ? 1 : a[field] > b[field] ? -1 : 0));
}

// Every vehicle with a finding, a data-quality flag or a decision.
function detailVehicles(report) {
  const flagged = new Set();
  report.findings.concat(report.data_quality, report.flagged_repairs)
    .forEach((f) => flagged.add(`${f.vin}\u0000${f.campaign_id}`));
  return report.vehicles.filter((v) => flagged.has(`${v.vin}\u0000${v.campaign_id}`) ||
    v.decision !== null || v.data_quality_reasons.length > 0);
}

// What the person can switch on or off. "checks" is the long one, so it
// starts off. The summary at the top is always included.
const exportChoice = { findings: true, flaggedRepairs: true, data: true, vehicles: true, runs: true, checks: false, decisions: true };

function exportParts(report) {
  return [
    ["findings", "Findings", `${report.findings.length} notification and repair findings`],
    ["flaggedRepairs", "Flagged repairs", `${report.flagged_repairs.length} repairs on unaffected vehicles`],
    ["data", "Missing and bad data",
      `${report.data_issues.length} data issues and ${report.data_quality.length} vehicle data-quality flags, kept apart`],
    ["vehicles", "Vehicle detail", `${detailVehicles(report).length} vehicles with a finding, a flag or a decision`],
    ["runs", "Saved runs", "each check run with its date and day limit"],
    ["checks", "Every saved check", `${report.history.length} rows from all saved runs. This can run to many pages`],
    ["decisions", "Coordinator decisions", `${report.decisions.length} decisions, newest first`],
  ];
}

function openExportDialog() {
  if (current === null) {
    showMessage("There is no report to export. Run a check first.", true);
    return;
  }
  const box = $("export-options");
  box.replaceChildren();
  exportParts(current.report).forEach(([key, label, note]) => {
    const row = el("label", null, "export-option");
    const input = el("input");
    input.type = "checkbox";
    input.name = key;
    input.checked = exportChoice[key];
    input.addEventListener("change", () => { exportChoice[key] = input.checked; });
    const text = el("span");
    text.appendChild(el("strong", label));
    text.appendChild(el("span", note, "hint"));
    row.appendChild(input);
    row.appendChild(text);
    box.appendChild(row);
  });
  $("export-dialog").showModal();
}

function printSection(root, title, tone, note) {
  const section = el("section", null, `print-section ${tone || ""}`);
  section.appendChild(el("h2", title));
  if (note) section.appendChild(el("p", note, "print-note"));
  root.appendChild(section);
  return section;
}

function printTable(section, columns, rows, cell, emptyText) {
  section.appendChild(rows.length === 0 ? empty(emptyText) : table(columns, rows, cell));
}

function kpi(value, label, tone) {
  const card = el("div", null, `print-kpi ${tone}`);
  card.appendChild(el("span", String(value), "print-kpi-n"));
  card.appendChild(el("span", label, "print-kpi-l"));
  return card;
}

function buildPrintReport(result, runs, choice) {
  const report = result.report;
  const root = $("print-report");
  root.replaceChildren();

  // Cover band: who, what, which check.
  const cover = el("div", null, "print-cover");
  const title = el("div");
  title.appendChild(el("p", DEALERSHIP_NAME, "print-dealer"));
  title.appendChild(el("h1", "Recall campaign report"));
  cover.appendChild(title);
  const meta = el("dl", null, "print-meta");
  [["Check date", report.check_date], ["Run", `#${result.run_id}`],
   ["Repair day limit", `${report.day_limit} days`],
   ["Data loaded", loadedText(result.loaded_at).replace(/^on /, "")]].forEach(([k, v]) => {
    const item = el("div");
    item.appendChild(el("dt", k));
    item.appendChild(el("dd", v));
    meta.appendChild(item);
  });
  cover.appendChild(meta);
  root.appendChild(cover);
  const note = filesNote(result.input_check);
  if (note !== null) root.appendChild(el("p", note, "print-warning"));

  // The numbers that matter, big. Notification and repair carry equal weight.
  const counts = { notification: 0, repair: 0 };
  report.findings.forEach((f) => { counts[f.kind] = (counts[f.kind] || 0) + 1; });
  const checked = report.vehicles.filter((v) => v.facts.affected.length > 0).length;
  const kpis = el("div", null, "print-kpis");
  kpis.appendChild(kpi(checked, "Vehicles checked (per campaign)", "total"));
  kpis.appendChild(kpi(counts.notification, "Notification findings", "notification"));
  kpis.appendChild(kpi(counts.repair, "Repair findings", "repair"));
  kpis.appendChild(kpi(report.flagged_repairs.length, "Flagged repairs", "repair"));
  kpis.appendChild(kpi(report.data_issues.length, "Data issues", "data"));
  kpis.appendChild(kpi(report.data_quality.length, "Data-quality flags", "data"));
  root.appendChild(kpis);
  root.appendChild(el("p",
    `Repair window: ${report.day_limit} days, counting both the notice day and the repair day. ` +
    "Data issues and flags are data problems, never findings.", "print-rule"));

  if (choice.findings) {
    const sec = printSection(root, `Findings (${report.findings.length})`, "tone-findings");
    printTable(sec, ["VIN", "Campaign", "Kind", "Reason"], report.findings,
      (f) => [el("span", f.vin, "mono"), el("span", f.campaign_id, "nowrap"),
        kindBadge(f.kind), isoDates(f.reason)], "No findings in this check.");
  }

  if (choice.flaggedRepairs) {
    const sec = printSection(root, `Flagged repairs (${report.flagged_repairs.length})`, "tone-findings",
      "Campaign eligibility requires a matching model and a build date within the inclusive campaign range.");
    printTable(sec, FLAGGED_REPAIR_COLUMNS, report.flagged_repairs,
      (f) => flaggedRepairCells(f, false), "No repairs on unaffected vehicles in this check.");
  }

  if (choice.data) {
    const sec = printSection(root, "Missing and bad data", "tone-data",
      "These are data problems, not findings. A row listed here is never treated as \"not notified\".");
    sec.appendChild(el("h3", `Data issues (${report.data_issues.length})`));
    printTable(sec, ["File and row", "Code and action", "VIN", "Campaign", "Reason"], report.data_issues,
      (d) => [el("span", `${d.file} · row ${d.src_row}`, "nowrap"), codeCell(d),
        d.vin === null ? "not readable" : el("span", d.vin, "mono"),
        d.campaign_id === null ? "not readable" : el("span", d.campaign_id, "nowrap"), isoDates(d.reason)],
      "No data issues.");
    sec.appendChild(el("h3", `Vehicle data-quality flags (${report.data_quality.length})`));
    printTable(sec, ["VIN", "Campaign", "Reason"], report.data_quality,
      (f) => [el("span", f.vin, "mono"), el("span", f.campaign_id, "nowrap"), isoDates(f.reason)],
      "No vehicle data-quality flags.");
  }

  if (choice.vehicles) {
    const detail = detailVehicles(report);
    const sec = printSection(root, `Vehicle detail (${detail.length})`, "tone-vehicles",
      "Every vehicle with a finding, a data-quality flag or a coordinator decision. " +
      "With no repair on file, days are counted from the notice to the check date.");
    printTable(sec, ["VIN", "Campaign", "In affected list", "In notices", "Notice used", "Repair used", "Days", "Limit",
      "Result", "Current decision", "Data problems"], detail,
      (v) => [el("span", v.vin, "mono"), el("span", v.campaign_id, "nowrap"),
        inAffectedList(v) ? "Yes" : "No", v.in_notices ? "Yes" : "No",
        v.notice_date_used, v.repair_date_used,
        inAffectedList(v) && v.inclusive_days !== null ? String(v.inclusive_days) : null, v.day_limit, repairResult(v),
        v.decision === null ? "—" : statusBadge(v.decision.status),
        v.data_quality_reasons.length === 0 ? "—" : isoDates(v.data_quality_reasons.join(" "))],
      "No vehicles have findings, flags or decisions.");
  }

  if (choice.runs) {
    const sec = printSection(root, "Saved runs", "tone-history",
      "Every check that was run. A later upload never removes earlier rows.");
    if (runs === null) sec.appendChild(empty("The saved runs could not be loaded."));
    else printTable(sec, ["Run", "Check date", "Repair day limit", "Data load (ingest)"], runs.slice().reverse(),
      (r) => [r.run_id, r.check_date, r.day_limit, r.ingest_id], "No saved runs.");
  }

  const currentBy = currentDecisions(report.decisions);
  if (choice.checks) {
    const sec = printSection(root, `Every saved check (${report.history.length})`, "tone-history",
      "Newest first. Notification and repair entries are not ranked.");
    printTable(sec, ["Check date", "VIN", "Campaign", "Kind", "Reason", "Day limit", "Current decision"],
      newestFirst(report.history, "check_date"),
      (h) => {
        const d = currentBy.get(`${h.vin}\u0000${h.campaign_id}`);
        return [el("span", h.check_date, "nowrap"), el("span", h.vin, "mono"), el("span", h.campaign_id, "nowrap"),
          kindBadge(h.kind), isoDates(h.reason), h.day_limit, d === undefined ? "—" : statusBadge(d.status)];
      }, "No checks have been saved yet.");
  }

  if (choice.decisions) {
    const sec = printSection(root, `Coordinator decisions (${report.decisions.length})`, "tone-history",
      "Newest first. The latest decision for a vehicle is its current decision; earlier ones stay listed.");
    printTable(sec, ["Decided on", "VIN", "Campaign", "Status", "Note"],
      newestFirst(report.decisions, "decided_on"),
      (d) => [el("span", d.decided_on, "nowrap"), el("span", d.vin, "mono"),
        el("span", d.campaign_id, "nowrap"), statusBadge(d.status), d.note],
      "No decisions have been recorded yet.");
  }

  // Say what this PDF leaves out, so a partial export is not mistaken for the whole report.
  const left = exportParts(report).filter(([key]) => !choice[key]).map(([, label]) => label);
  if (left.length > 0) {
    root.appendChild(el("p", `Not included in this PDF: ${left.join(", ")}.`, "print-omitted"));
  }
}

async function exportPdf() {
  if (current === null) {
    showMessage("There is no report to export. Run a check first.", true);
    return;
  }
  $("export-dialog").close();
  if (current.input_check && current.input_check.state === "unusable") {
    showMessage("The input files cannot be read, so this report is not exported. Fix the files and run a check.", true);
    return;
  }
  const button = $("export-pdf");
  button.disabled = true;
  try {
    let runs = null;
    if (exportChoice.runs) {
      const saved = await api("GET", "/api/runs");
      runs = saved.status === 200 ? saved.data.runs : null;
    }
    buildPrintReport(current, runs, Object.assign({}, exportChoice));
    // The browser uses the page title as the suggested file name.
    const title = document.title;
    document.title = `Recall report ${current.report.check_date} run ${current.run_id}`;
    window.addEventListener("afterprint", () => { document.title = title; }, { once: true });
    window.print();
  } finally {
    button.disabled = current === null || (current.input_check && current.input_check.state === "unusable");
  }
}

function route() {
  if (current === null) return;
  const match = /^#\/vehicle\/([^/]+)\/([^/]+)$/.exec(location.hash);
  let parts = null;
  if (match) {
    try { parts = [decodeURIComponent(match[1]), decodeURIComponent(match[2])]; }
    catch (err) { parts = null; }
  }
  const onHistory = location.hash === "#/history";
  const onFlaggedRepairs = location.hash === "#/flagged-repairs";
  $("report").hidden = parts !== null || onHistory || onFlaggedRepairs;
  $("detail").hidden = parts === null;
  $("history").hidden = !onHistory;
  $("flagged-repairs").hidden = !onFlaggedRepairs;
  $("nav-flagged-repairs").classList.toggle("active", onFlaggedRepairs);
  $("nav-flags").classList.toggle("active", !onHistory && !onFlaggedRepairs && parts === null);
  $("nav-history").classList.toggle("active", onHistory);
  if (parts !== null) {
    renderDetail(current.report, parts[0], parts[1]);
    window.scrollTo(0, 0);
  } else if (onHistory) {
    renderHistory(current.report);
  }
}

function fact(label, value, note) {
  const box = el("div", null, "fact");
  box.appendChild(el("dt", label));
  const dd = el("dd");
  if (value instanceof Node) dd.appendChild(value);
  else dd.textContent = value;
  if (note) dd.appendChild(el("span", note, "hint fact-note"));
  box.appendChild(dd);
  return box;
}

function statusBadge(status) {
  return el("span", status, `status status-${status.replace(" ", "-")}`);
}

function sameVehicle(vin, campaign) {
  return (row) => row.vin === vin && row.campaign_id === campaign;
}

// The check only runs for vehicles on the affected list. A notice or repair
// row for any other vehicle is a data-quality flag, so no day count applies.
function inAffectedList(v) {
  return v.facts.affected.length > 0;
}

function repairResult(v) {
  if (!inAffectedList(v)) return "Not applicable (not in the affected list)";
  if (v.on_time === true) return el("span", "On time", "kind kind-ok");
  if (v.on_time === false) return el("span", "Late", "kind kind-repair");
  return v.notice_date_used === null
    ? "Not applicable (no notice date)" : "No repair on or after the notice";
}

function renderDetail(report, vin, campaign) {
  const root = $("detail");
  root.replaceChildren();
  const back = el("a", "\u2190 Back to flags");
  back.href = "#";
  back.className = "back";
  root.appendChild(back);

  const v = report.vehicles.find(sameVehicle(vin, campaign));
  if (v === undefined) {
    root.appendChild(empty("This vehicle and campaign are not in the current report."));
    return;
  }

  const title = el("h2", null, "detail-title");
  title.appendChild(el("span", v.vin, "mono"));
  title.appendChild(el("span", `  ${v.campaign_id}`, "detail-campaign"));
  root.appendChild(title);

  // What the check used.
  const facts = el("dl", null, "facts");
  const affected = inAffectedList(v);
  facts.appendChild(fact("In affected list", affected ? "Yes" : "No",
    affected ? "" : "not checked for notice or repair days"));
  facts.appendChild(fact("In notices file", v.in_notices ? "Yes" : "No"));
  facts.appendChild(fact("Notice date used",
    v.notice_date_used === null ? "No usable notice date" : v.notice_date_used,
    v.notice_date_used === null ? "" : "earliest notice on file"));
  facts.appendChild(fact("Repair date used",
    v.repair_date_used === null ? "No usable repair" : v.repair_date_used,
    v.repair_date_used === null ? "" : "earliest repair on or after the notice"));
  // No day count for a vehicle outside the affected list: it would look overdue.
  if (affected) {
    facts.appendChild(fact(
      v.repair_date_used === null ? "Days since notice" : "Inclusive days, notice to repair",
      v.inclusive_days === null ? "\u2014" : String(v.inclusive_days),
      v.repair_date_used === null && v.inclusive_days !== null
        ? `counted to the check date ${report.check_date}` : ""));
  }
  facts.appendChild(fact("Day limit", `${v.day_limit} days`));
  facts.appendChild(fact("Repair result", repairResult(v)));
  if (v.facts.vehicle) {
    facts.appendChild(fact("Vehicle model", v.facts.vehicle.model));
    facts.appendChild(fact("Build date", v.facts.vehicle.build_date));
  }
  if (v.facts.campaign) {
    facts.appendChild(fact("Campaign model", v.facts.campaign.model));
    facts.appendChild(fact("Campaign build date range",
      `${v.facts.campaign.start_date} to ${v.facts.campaign.end_date}`, "both dates included"));
  }
  root.appendChild(facts);

  // Notification and repair findings for this pair. Data problems come later, apart from these.
  const pair = sameVehicle(vin, campaign);
  const found = report.findings.concat(report.flagged_repairs).filter(pair);
  root.appendChild(el("h3", "Findings for this vehicle"));
  if (found.length === 0) {
    root.appendChild(empty("No notification or repair finding for this vehicle."));
  } else {
    const list = el("ul", null, "reasons");
    found.forEach((f) => {
      const li = el("li");
      li.appendChild(kindBadge(f.kind));
      li.appendChild(el("span", ` ${isoDates(f.reason)}`));
      list.appendChild(li);
    });
    root.appendChild(list);
  }

  // Every date on file, and which one the check used.
  root.appendChild(el("h3", "Dates on file"));
  const rows = [];
  v.facts.notices.forEach((n) => rows.push(["Notice", n.notice_date, n.notice_date === v.notice_date_used]));
  v.facts.repairs.forEach((r) => rows.push(["Repair", r.repair_date, r.repair_date === v.repair_date_used]));
  root.appendChild(rows.length === 0
    ? empty("No notice or repair dates on file for this vehicle.")
    : table(["Record", "Date", "Used by the check"], rows,
        (r) => [r[0], el("span", r[1], "nowrap"), r[2] ? "Yes" : "No"]));

  // Data problems for this pair, kept apart from the findings. Same wording is listed once.
  const problems = new Set(v.data_quality_reasons);
  report.data_issues.filter(pair).forEach((d) => problems.add(d.reason));
  if (problems.size > 0) {
    root.appendChild(el("h3", "Data problems (not findings)"));
    const list = el("ul", null, "reasons");
    problems.forEach((text) => list.appendChild(el("li", isoDates(text))));
    root.appendChild(list);
  }

  root.appendChild(decisionSection(report, v));
}

function decisionSection(report, v) {
  const section = el("section", null, "decision");
  section.appendChild(el("h3", "Coordinator decision"));

  const mine = report.decisions.filter(sameVehicle(v.vin, v.campaign_id));
  if (v.decision === null) {
    section.appendChild(el("p", "No decision recorded yet.", "muted"));
  } else {
    const box = el("div", null, "current-decision");
    box.appendChild(statusBadge(v.decision.status));
    box.appendChild(el("span", ` on ${v.decision.decided_on}`, "hint"));
    if (v.decision.note) box.appendChild(el("p", v.decision.note, "note"));
    section.appendChild(box);
  }

  const form = el("form", null, "decision-form");
  const fieldset = el("fieldset");
  fieldset.appendChild(el("legend", "Record a decision"));
  STATUSES.forEach((status, i) => {
    const label = el("label", null, "choice");
    const input = el("input");
    input.type = "radio";
    input.name = "status";
    input.value = status;
    input.required = true;
    if (i === 0) input.checked = false;
    label.appendChild(input);
    label.appendChild(el("span", ` ${status}`));
    fieldset.appendChild(label);
  });
  form.appendChild(fieldset);
  const noteLabel = el("label", "Note (optional)", "note-label");
  noteLabel.setAttribute("for", "decision-note");
  const note = el("textarea");
  note.id = "decision-note";
  note.rows = 3;
  form.appendChild(noteLabel);
  form.appendChild(note);
  const submit = el("button", "Save decision");
  submit.type = "submit";
  form.appendChild(submit);
  form.appendChild(el("span", "Saving adds to the history. Earlier decisions are kept.", "hint"));
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    saveDecision(v, form, submit);
  });
  section.appendChild(form);

  if (mine.length > 0) {
    section.appendChild(el("h3", "Decision history"));
    section.appendChild(table(["Date", "Status", "Note"], mine.slice().reverse(),
      (d) => [el("span", d.decided_on, "nowrap"), statusBadge(d.status), d.note]));
  }
  return section;
}

async function saveDecision(v, form, submit) {
  const chosen = form.querySelector("input[name=status]:checked");
  if (chosen === null) {
    showMessage("Choose reviewed, follow up or no action.", true);
    return;
  }
  const body = { vin: v.vin, campaign_id: v.campaign_id, status: chosen.value };
  const noteText = form.querySelector("textarea").value.trim();
  if (noteText !== "") body.note = noteText;
  submit.disabled = true;
  try {
    const saved = await api("POST", "/api/decisions", body);
    if (saved.status !== 201) {
      showMessage(saved.data.error || "The decision could not be saved.", true);
      return;
    }
    // Reload the saved report so the new decision shows with the old ones.
    const fresh = await api("GET", "/api/report");
    if (fresh.status === 200) {
      render(fresh.data);
      showMessage("Decision saved.", false);
    } else {
      showMessage("The decision was saved, but the report could not be reloaded.", true);
    }
  } finally {
    submit.disabled = false;
  }
}

function busy(isBusy) {
  $("run-check").disabled = isBusy;
  $("limit-form").querySelector("button").disabled = isBusy;
}

async function handle(promise) {
  busy(true);
  try {
    const { status, data } = await promise;
    if (status === 200 || status === 201) render(data);
    // A file problem (422) hides every finding. Other errors leave the screen as it is.
    else if (status === 422) showError(data.error);
    else showMessage(data.error || "The action could not be completed.", true);
  } finally {
    busy(false);
  }
}

async function load() {
  const { status, data } = await api("GET", "/api/report");
  if (status === 200) render(data);
  else if (status === 400) showNoCheckYet();
  else showError(data.error || "The report could not be loaded.");
}

$("export-pdf").addEventListener("click", openExportDialog);
$("export-form").addEventListener("submit", (event) => { event.preventDefault(); exportPdf(); });
$("export-cancel").addEventListener("click", () => $("export-dialog").close());
$("run-check").addEventListener("click", () => handle(api("POST", "/api/checks", {})));

$("limit-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const value = Number($("day-limit").value);
  if (!Number.isInteger(value) || value < 1) {
    showMessage("The repair day limit must be a whole number of 1 or more.", true);
    return;
  }
  handle(api("POST", "/api/day-limit", { day_limit: value }));
});

window.addEventListener("hashchange", route);
$("dealer").textContent = DEALERSHIP_NAME;
load();
