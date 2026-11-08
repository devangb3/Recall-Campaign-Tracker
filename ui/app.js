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
  $("report").hidden = true;
  $("detail").hidden = true;
  showMessage(text, true);
}

function showNoCheckYet() {
  current = null;
  $("report").hidden = true;
  $("detail").hidden = true;
  showMessage("No check has been run yet. Choose “Run check” to load the three CSV files.", false);
}

function render(result) {
  const report = result.report;
  clearMessage();
  current = result;
  $("day-limit").value = report.day_limit;
  $("summary").textContent =
    `Check date ${report.check_date} · run ${result.run_id} · repair limit ${report.day_limit} days`;

  const counts = { notification: 0, repair: 0 };
  report.findings.forEach((f) => { counts[f.kind] = (counts[f.kind] || 0) + 1; });
  const stats = $("stats");
  stats.replaceChildren();
  [["Notification findings", counts.notification, "notification"],
   ["Repair findings", counts.repair, "repair"],
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
        [vehicleLink(f.vin, f.campaign_id), el("span", f.campaign_id, "nowrap"), el("span", f.kind, `kind kind-${f.kind}`), f.reason]));

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
                  d.reason, details];
        }));

  fill("data-quality", report.data_quality.length === 0
    ? empty("No vehicle data-quality flags.")
    : table(["VIN", "Campaign", "Reason"], report.data_quality, (f) =>
        [vehicleLink(f.vin, f.campaign_id), el("span", f.campaign_id, "nowrap"), f.reason]));

  route();
}

// ---- Vehicle detail (REC-27) ------------------------------------------------

function route() {
  if (current === null) return;
  const match = /^#\/vehicle\/([^/]+)\/([^/]+)$/.exec(location.hash);
  let parts = null;
  if (match) {
    try { parts = [decodeURIComponent(match[1]), decodeURIComponent(match[2])]; }
    catch (err) { parts = null; }
  }
  $("report").hidden = parts !== null;
  $("detail").hidden = parts === null;
  if (parts !== null) {
    renderDetail(current.report, parts[0], parts[1]);
    window.scrollTo(0, 0);
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

function repairResult(v) {
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
  facts.appendChild(fact("In notices file", v.in_notices ? "Yes" : "No"));
  facts.appendChild(fact("Notice date used",
    v.notice_date_used === null ? "No usable notice date" : v.notice_date_used,
    v.notice_date_used === null ? "" : "earliest notice on file"));
  facts.appendChild(fact("Repair date used",
    v.repair_date_used === null ? "No usable repair" : v.repair_date_used,
    v.repair_date_used === null ? "" : "earliest repair on or after the notice"));
  facts.appendChild(fact(
    v.repair_date_used === null ? "Days since notice" : "Inclusive days, notice to repair",
    v.inclusive_days === null ? "\u2014" : String(v.inclusive_days),
    v.repair_date_used === null && v.inclusive_days !== null
      ? `counted to the check date ${report.check_date}` : ""));
  facts.appendChild(fact("Day limit", `${v.day_limit} days`));
  facts.appendChild(fact("Repair result", repairResult(v)));
  root.appendChild(facts);

  // Notification and repair findings for this pair. Data problems come later, apart from these.
  const pair = sameVehicle(vin, campaign);
  const found = report.findings.filter(pair);
  root.appendChild(el("h3", "Findings for this vehicle"));
  if (found.length === 0) {
    root.appendChild(empty("No notification or repair finding for this vehicle."));
  } else {
    const list = el("ul", null, "reasons");
    found.forEach((f) => {
      const li = el("li");
      li.appendChild(el("span", f.kind, `kind kind-${f.kind}`));
      li.appendChild(el("span", ` ${f.reason}`));
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
    problems.forEach((text) => list.appendChild(el("li", text)));
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
