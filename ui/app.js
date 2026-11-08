"use strict";

// Every value from the API is written with textContent, never innerHTML.
// raw_row can hold a repair tech_note, which is data and not markup.

// The one dealership this tracker is for. Change the name here only.
const DEALERSHIP_NAME = "Infinachi Auto Repairs";

const $ = (id) => document.getElementById(id);

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
  $("report").hidden = true;
  showMessage(text, true);
}

function showNoCheckYet() {
  $("report").hidden = true;
  showMessage("No check has been run yet. Choose “Run check” to load the three CSV files.", false);
}

function render(result) {
  const report = result.report;
  clearMessage();
  $("report").hidden = false;
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
        [el("span", f.vin, "mono"), el("span", f.campaign_id, "nowrap"), el("span", f.kind, `kind kind-${f.kind}`), f.reason]));

  fill("data-issues", report.data_issues.length === 0
    ? empty("No data issues.")
    : table(["File and row", "Code and action", "VIN", "Campaign", "Reason", "Raw row"],
        report.data_issues, (d) => {
          const details = el("details");
          details.appendChild(el("summary", "Show"));
          details.appendChild(el("pre", d.raw_row, "mono"));
          return [el("span", `${d.file} \u00b7 row ${d.src_row}`, "nowrap"), codeCell(d),
                  d.vin === null ? "not readable" : el("span", d.vin, "mono"),
                  d.campaign_id === null ? "not readable" : el("span", d.campaign_id, "nowrap"),
                  d.reason, details];
        }));

  fill("data-quality", report.data_quality.length === 0
    ? empty("No vehicle data-quality flags.")
    : table(["VIN", "Campaign", "Reason"], report.data_quality, (f) =>
        [el("span", f.vin, "mono"), el("span", f.campaign_id, "nowrap"), f.reason]));
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

$("dealer").textContent = DEALERSHIP_NAME;
load();
