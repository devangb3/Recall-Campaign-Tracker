"use strict";

// The one dealership this tracker is for. Change the name here only.
const DEALERSHIP_NAME = "Infinachi Auto Repairs";

const STATUSES = ["reviewed", "follow up", "no action"];
const EXPORT_KEYS = ["findings", "flaggedRepairs", "data", "vehicles", "runs", "checks", "decisions"];
const CHECK_ROW_CAP = 500;
const NO_CHECK = "No check has been run yet. Choose \u201cRun check\u201d to load the five CSV files.";

class ParseError extends Error {
  constructor(message) {
    super(message);
    this.name = "ParseError";
  }
}

function $(id) {
  const node = document.getElementById(id);
  if (node === null) throw new Error("missing #" + id);
  return node;
}

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function table(columns, rows, cell) {
  const wrap = el("div", null, "table-wrap");
  const grid = el("table");
  const head = el("tr");
  columns.forEach((name) => head.appendChild(el("th", name)));
  grid.appendChild(el("thead")).appendChild(head);
  const body = el("tbody");
  rows.forEach((row) => {
    const tr = el("tr");
    cell(row).forEach((value) => {
      const td = el("td");
      if (value instanceof Node) td.appendChild(value);
      else td.textContent = value === null || value === undefined ? "\u2014" : value;
      tr.appendChild(td);
    });
    body.appendChild(tr);
  });
  grid.appendChild(body);
  wrap.appendChild(grid);
  return wrap;
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
  const box = $("message");
  box.hidden = true;
  box.textContent = "";
  box.className = "";
}

function kindBadge(kind) {
  const tone = kind === "data quality" ? "data" : kind.replaceAll(" ", "-");
  return el("span", kind, "kind kind-" + tone);
}

function statusBadge(status) {
  return el("span", status, "status status-" + status.replaceAll(" ", "-"));
}

function codeCell(row) {
  const box = el("div");
  box.appendChild(el("div", row.issue_code, "nowrap"));
  box.appendChild(el("div", row.action, "hint"));
  return box;
}

// A date that is not a real calendar day stays as written. It is the problem.
function isoDates(text) {
  return text.replace(/\b(\d{2})\/(\d{2})\/(\d{4})\b/g, (found, mm, dd, yyyy) => {
    const d = new Date(Date.UTC(+yyyy, +mm - 1, +dd));
    const real = d.getUTCFullYear() === +yyyy && d.getUTCMonth() === +mm - 1 && d.getUTCDate() === +dd;
    return real ? yyyy + "-" + mm + "-" + dd : found;
  });
}

// shortGeneric stays ET all year. EST and EDT would each be wrong for half of it.
function loadedText(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "at an unknown time";
  const pad = (n) => String(n).padStart(2, "0");
  const zone = new Intl.DateTimeFormat("en-US", { timeZoneName: "shortGeneric" })
    .formatToParts(d).find((part) => part.type === "timeZoneName");
  return "on " + d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) + " " +
    pad(d.getHours()) + ":" + pad(d.getMinutes()) + (zone ? " " + zone.value : "");
}

function filesNote(inputCheck) {
  if (!inputCheck || inputCheck.state === "ok") return null;
  if (inputCheck.state === "unusable") {
    return inputCheck.message + " This is the last good report; nothing has been checked again. " +
      "Fix the files, then choose \u201cRun check\u201d.";
  }
  return inputCheck.message + " This report is from the earlier data. Choose \u201cRun check\u201d to load the new files.";
}

function textHit(needle, parts) {
  const wanted = needle.trim().toLowerCase();
  if (wanted === "") return true;
  for (let i = 0; i < parts.length; i++) {
    const part = parts[i];
    if (part === null || part === undefined) continue;
    if (String(part).toLowerCase().includes(wanted)) return true;
  }
  return false;
}

function vinHit(needle, vin) {
  const wanted = needle.trim().toLowerCase();
  if (wanted === "") return true;
  if (vin === null || vin === undefined) return false;
  return String(vin).toLowerCase().includes(wanted);
}

function vehicleKey(vin, campaignId) {
  return vin + "\u0000" + campaignId;
}

function linkOrText(vin, campaignId, index, lensId) {
  if (vin === null || vin === undefined) return "not readable";
  if (campaignId === null || campaignId === undefined) return el("span", vin, "mono");
  if (!index.vehiclesByKey.has(vehicleKey(vin, campaignId))) return el("span", vin, "mono");
  return vehicleLink(vin, campaignId, lensId);
}

function vehicleLink(vin, campaignId, lensId) {
  const link = el("a", vin, "mono vin-link");
  link.href = hashFor(lensId, { vin: vin, campaignId: campaignId });
  return link;
}

const FLAGGED_COLUMNS = ["VIN", "Campaign", "Vehicle model", "Build date",
  "Campaign model", "Build date range (inclusive)", "Flag", "Repair dates", "Reason"];

function flaggedRepairCells(row, link, index, lensId) {
  const vehicle = row.facts.vehicle;
  const campaign = row.facts.campaign;
  return [
    link ? linkOrText(row.vin, row.campaign_id, index, lensId) : el("span", row.vin, "mono"),
    row.campaign_id,
    vehicle.model,
    vehicle.build_date,
    campaign.model,
    campaign.start_date + " to " + campaign.end_date,
    "Repair on an unaffected vehicle",
    row.facts.repairs.map((item) => item.repair_date).join(", "),
    row.reason,
  ];
}

// The band hides one data-problems pane. It is not a row predicate.
const LENS_CATALOG = Object.freeze([
  Object.freeze({
    id: "findings",
    hash: "#",
    aliases: Object.freeze(["", "#/", "#/findings"]),
    navId: "nav-flags",
    regionId: "report",
    filtersId: "findings-filters",
    fields: Object.freeze([
      Object.freeze({ key: "text", label: "Search", control: "search" }),
      Object.freeze({
        key: "kind", label: "Kind", control: "enum",
        labels: Object.freeze({ "": "Any", notification: "notification", repair: "repair" }),
      }),
      Object.freeze({ key: "campaign", label: "Campaign", control: "distinct", prop: "campaign_id" }),
    ]),
    panes: Object.freeze([
      Object.freeze({
        id: "findings",
        mountId: "findings",
        columns: Object.freeze(["VIN", "Campaign", "Kind", "Reason"]),
        ordered: (index) => index.findings,
        emptySource: "No findings in this check.",
        emptyMatch: "No findings match these filters.",
        match(row, query) {
          if (query.kind !== "" && row.kind !== query.kind) return false;
          if (query.campaign !== "" && row.campaign_id !== query.campaign) return false;
          return textHit(query.text, [row.vin, row.campaign_id, row.reason]);
        },
        cells(row, index, lensId) {
          return [
            linkOrText(row.vin, row.campaign_id, index, lensId),
            el("span", row.campaign_id, "nowrap"),
            kindBadge(row.kind),
            isoDates(row.reason),
          ];
        },
      }),
    ]),
  }),
  Object.freeze({
    id: "flaggedRepairs",
    hash: "#/flagged-repairs",
    aliases: Object.freeze([]),
    navId: "nav-flagged-repairs",
    regionId: "flagged-repairs",
    filtersId: "flagged-filters",
    fields: Object.freeze([
      Object.freeze({ key: "text", label: "Search", control: "search" }),
      Object.freeze({ key: "campaign", label: "Campaign", control: "distinct", prop: "campaign_id" }),
    ]),
    panes: Object.freeze([
      Object.freeze({
        id: "flagged",
        mountId: "flagged-repairs-list",
        columns: FLAGGED_COLUMNS,
        ordered: (index) => index.flaggedRepairs,
        emptySource: "No repairs on unaffected vehicles in this check.",
        emptyMatch: "No flagged repairs match these filters.",
        match(row, query) {
          if (query.campaign !== "" && row.campaign_id !== query.campaign) return false;
          return textHit(query.text, [
            row.vin, row.campaign_id, row.reason,
            row.facts.vehicle.model, row.facts.campaign.model,
          ]);
        },
        cells(row, index, lensId) {
          return flaggedRepairCells(row, true, index, lensId);
        },
      }),
    ]),
  }),
  Object.freeze({
    id: "dataProblems",
    hash: "#/data-problems",
    aliases: Object.freeze([]),
    navId: "nav-data-problems",
    regionId: "data-problems",
    filtersId: "data-filters",
    fields: Object.freeze([
      Object.freeze({ key: "text", label: "Search", control: "search" }),
      Object.freeze({
        key: "band", label: "Show", control: "enum",
        labels: Object.freeze({
          "": "Any",
          issues: "Data issues",
          quality: "Vehicle data-quality flags",
        }),
      }),
      Object.freeze({ key: "campaign", label: "Campaign", control: "distinct", prop: "campaign_id" }),
    ]),
    panes: Object.freeze([
      Object.freeze({
        id: "issues",
        mountId: "data-issues",
        bandId: "issues-band",
        columns: Object.freeze(["File and row", "Code and action", "VIN", "Campaign", "Reason", "Raw row"]),
        ordered: (index) => index.dataIssues,
        emptySource: "No data issues.",
        emptyMatch: "No data issues match these filters.",
        match(row, query) {
          if (query.campaign !== "" && row.campaign_id !== query.campaign) return false;
          return textHit(query.text, [row.vin, row.campaign_id, row.reason, row.file, row.issue_code]);
        },
        cells(row, index, lensId) {
          const details = el("details");
          details.appendChild(el("summary", "Show"));
          details.appendChild(el("pre", row.raw_row, "mono"));
          return [
            el("span", row.file + " \u00b7 row " + row.src_row, "nowrap"),
            codeCell(row),
            linkOrText(row.vin, row.campaign_id, index, lensId),
            row.campaign_id === null ? "not readable" : el("span", row.campaign_id, "nowrap"),
            isoDates(row.reason),
            details,
          ];
        },
      }),
      Object.freeze({
        id: "quality",
        mountId: "data-quality",
        bandId: "quality-band",
        columns: Object.freeze(["VIN", "Campaign", "Reason"]),
        ordered: (index) => index.dataQuality,
        emptySource: "No vehicle data-quality flags.",
        emptyMatch: "No data-quality flags match these filters.",
        match(row, query) {
          if (query.campaign !== "" && row.campaign_id !== query.campaign) return false;
          return textHit(query.text, [row.vin, row.campaign_id, row.reason]);
        },
        cells(row, index, lensId) {
          return [
            linkOrText(row.vin, row.campaign_id, index, lensId),
            el("span", row.campaign_id, "nowrap"),
            isoDates(row.reason),
          ];
        },
      }),
    ]),
  }),
  Object.freeze({
    id: "history",
    hash: "#/history",
    aliases: Object.freeze([]),
    navId: "nav-history",
    regionId: "history",
    filtersId: "history-filters",
    runsMountId: "history-runs",
    fields: Object.freeze([
      Object.freeze({ key: "vin", label: "VIN contains", control: "search", placeholder: "e.g. SYN4P" }),
      Object.freeze({ key: "campaign", label: "Campaign", control: "distinct", prop: "campaign_id" }),
      Object.freeze({
        key: "kind", label: "Kind", control: "enum",
        labels: Object.freeze({
          "": "Any",
          notification: "notification",
          repair: "repair",
          "data quality": "data quality",
          "unaffected repair": "Repair on an unaffected vehicle",
        }),
      }),
      Object.freeze({ key: "from", label: "Check date from", control: "date" }),
      Object.freeze({ key: "to", label: "to", control: "date" }),
      Object.freeze({
        key: "decision", label: "Current decision", control: "enum",
        labels: Object.freeze({
          "": "Any",
          none: "No decision yet",
          reviewed: "reviewed",
          "follow up": "follow up",
          "no action": "no action",
        }),
      }),
      Object.freeze({ key: "limit", label: "Day limit used", control: "distinct", prop: "day_limit" }),
    ]),
    panes: Object.freeze([
      Object.freeze({
        id: "checks",
        mountId: "history-checks",
        columns: Object.freeze(["Check date", "VIN", "Campaign", "Kind", "Reason", "Day limit", "Current decision"]),
        ordered: (index) => index.historyNewest,
        emptySource: "No checks have been saved yet.",
        emptyMatch: "No checks match these filters.",
        count(shown, matching, total) {
          const base = "Showing " + shown + " of " + matching + " matching checks (" + total + " saved in total)";
          if (matching > shown) return base + ". Narrow the filters to see the rest.";
          return base + ".";
        },
        match(row, query, index) {
          if (!vinHit(query.vin, row.vin)) return false;
          if (query.campaign !== "" && row.campaign_id !== query.campaign) return false;
          if (query.kind !== "" && row.kind !== query.kind) return false;
          if (query.from !== "" && row.check_date < query.from) return false;
          if (query.to !== "" && row.check_date > query.to) return false;
          if (query.limit !== "" && String(row.day_limit) !== query.limit) return false;
          if (query.decision !== "") {
            const decision = index.decisionByKey.get(vehicleKey(row.vin, row.campaign_id));
            if (query.decision === "none") return decision === undefined;
            return decision !== undefined && decision.status === query.decision;
          }
          return true;
        },
        cells(row, index, lensId) {
          const decision = index.decisionByKey.get(vehicleKey(row.vin, row.campaign_id));
          return [
            el("span", row.check_date, "nowrap"),
            linkOrText(row.vin, row.campaign_id, index, lensId),
            el("span", row.campaign_id, "nowrap"),
            kindBadge(row.kind),
            isoDates(row.reason),
            row.day_limit,
            decision === undefined ? "\u2014" : statusBadge(decision.status),
          ];
        },
      }),
      Object.freeze({
        id: "decisions",
        mountId: "history-decisions",
        columns: Object.freeze(["Decided on", "VIN", "Campaign", "Status", "Note"]),
        ordered: (index) => index.decisionsNewest,
        emptySource: "No decisions have been recorded yet.",
        emptyMatch: "No decisions match the VIN and campaign filters.",
        match(row, query) {
          if (!vinHit(query.vin, row.vin)) return false;
          if (query.campaign !== "" && row.campaign_id !== query.campaign) return false;
          return true;
        },
        cells(row, index, lensId) {
          return [
            el("span", row.decided_on, "nowrap"),
            linkOrText(row.vin, row.campaign_id, index, lensId),
            el("span", row.campaign_id, "nowrap"),
            statusBadge(row.status),
            row.note,
          ];
        },
      }),
    ]),
  }),
]);

function lensById(lensId) {
  const lens = LENS_CATALOG.find((entry) => entry.id === lensId);
  if (lens === undefined) throw new Error("unknown lens " + lensId);
  return lens;
}

function emptyQuery(lens) {
  const query = {};
  for (const field of lens.fields) query[field.key] = "";
  return query;
}

function samePin(left, right) {
  if (left === null || right === null) return left === right;
  return left.vin === right.vin && left.campaignId === right.campaignId;
}

function parseHash(hash) {
  let text = hash || "";
  if (text.length > 1 && text.endsWith("/")) text = text.slice(0, -1);
  const vehicle = /\/vehicle\/([^/]+)\/([^/]*)$/.exec(text);
  let pin = null;
  let rest = text;
  if (vehicle) {
    rest = text.slice(0, vehicle.index);
    try {
      pin = {
        vin: decodeURIComponent(vehicle[1]),
        campaignId: decodeURIComponent(vehicle[2]),
      };
    } catch (err) {
      pin = null;
    }
    if (pin !== null && (pin.vin === "" || pin.campaignId === "")) pin = null;
  }
  const lens = LENS_CATALOG.find((entry) => entry.hash === rest || entry.aliases.includes(rest));
  if (lens === undefined) return { lensId: "findings", pin: pin };
  return { lensId: lens.id, pin: pin };
}

function hashFor(lensId, pin) {
  const lens = lensById(lensId);
  if (pin === null) return lens.hash;
  return lens.hash + "/vehicle/" + encodeURIComponent(pin.vin) + "/" + encodeURIComponent(pin.campaignId);
}

function reflectHash(cursor) {
  const current = parseHash(location.hash);
  if (current.lensId === cursor.lensId && samePin(current.pin, cursor.pin)) return;
  location.hash = hashFor(cursor.lensId, cursor.pin);
}

function matchesFor(lens, query, index) {
  const matches = {};
  for (const pane of lens.panes) {
    const rows = pane.ordered(index);
    const indexes = [];
    for (let i = 0; i < rows.length; i++) {
      if (pane.match(rows[i], query, index)) indexes.push(i);
    }
    matches[pane.id] = indexes;
  }
  return matches;
}

function cursorFrom(nav, index) {
  const queries = {};
  for (const lens of LENS_CATALOG) queries[lens.id] = emptyQuery(lens);
  const lens = lensById(nav.lensId);
  return {
    lensId: nav.lensId,
    pin: nav.pin,
    queries: queries,
    matches: matchesFor(lens, queries[lens.id], index),
  };
}

function retarget(cursor, index) {
  const lens = lensById(cursor.lensId);
  return {
    lensId: cursor.lensId,
    pin: cursor.pin,
    queries: cursor.queries,
    matches: matchesFor(lens, cursor.queries[lens.id], index),
  };
}

function withRuns(index, runs) {
  return Object.assign({}, index, { runs: runs });
}

function byNewest(rows, field) {
  return Object.freeze(rows.slice().reverse().sort((left, right) => {
    if (left[field] < right[field]) return 1;
    if (left[field] > right[field]) return -1;
    return 0;
  }));
}

function sameDecision(left, right) {
  const vehicleDecision = left === undefined ? null : left;
  const winner = right === undefined ? null : right;
  if (vehicleDecision === null || winner === null) return vehicleDecision === winner;
  return vehicleDecision.vin === winner.vin
    && vehicleDecision.campaign_id === winner.campaign_id
    && vehicleDecision.status === winner.status
    && vehicleDecision.decided_on === winner.decided_on
    && vehicleDecision.note === winner.note;
}

function requireArray(report, key) {
  const value = report[key];
  if (!Array.isArray(value)) throw new ParseError("report." + key + " is missing");
  return value;
}

function parseReport(data) {
  if (data === null || typeof data !== "object") throw new ParseError("report envelope is missing");
  if (data.run_id === undefined || data.run_id === null || data.run_id === "") {
    throw new ParseError("run_id is missing");
  }
  if (data.ingest_id === undefined || data.ingest_id === null || data.ingest_id === "") {
    throw new ParseError("ingest_id is missing");
  }
  if (typeof data.loaded_at !== "string" || data.loaded_at === "") throw new ParseError("loaded_at is missing");
  const report = data.report;
  if (report === null || typeof report !== "object") throw new ParseError("report is missing");
  if (typeof report.check_date !== "string" || report.check_date === "") {
    throw new ParseError("report.check_date is missing");
  }
  if (typeof report.day_limit !== "number" || !Number.isInteger(report.day_limit)) {
    throw new ParseError("report.day_limit is missing");
  }
  let inputCheck = null;
  if (data.input_check !== undefined && data.input_check !== null) {
    if (typeof data.input_check !== "object") throw new ParseError("input_check is missing");
    inputCheck = data.input_check;
  }
  const findings = Object.freeze(requireArray(report, "findings"));
  const flaggedRepairs = Object.freeze(requireArray(report, "flagged_repairs"));
  const dataQuality = Object.freeze(requireArray(report, "data_quality"));
  const dataIssues = Object.freeze(requireArray(report, "data_issues"));
  const decisions = Object.freeze(requireArray(report, "decisions"));
  const history = Object.freeze(requireArray(report, "history"));
  const vehicles = Object.freeze(requireArray(report, "vehicles"));
  const vehiclesByKey = new Map();
  for (const vehicle of vehicles) {
    if (vehicle === null || typeof vehicle !== "object"
        || typeof vehicle.vin !== "string" || typeof vehicle.campaign_id !== "string") {
      throw new ParseError("vehicle is missing vin or campaign_id");
    }
    const key = vehicleKey(vehicle.vin, vehicle.campaign_id);
    if (vehiclesByKey.has(key)) {
      throw new ParseError("duplicate vehicle " + vehicle.vin + " " + vehicle.campaign_id);
    }
    vehiclesByKey.set(key, vehicle);
  }
  const decisionByKey = new Map();
  for (const decision of decisions) {
    if (decision === null || typeof decision !== "object"
        || typeof decision.vin !== "string" || typeof decision.campaign_id !== "string") {
      throw new ParseError("decision is missing vin or campaign_id");
    }
    const key = vehicleKey(decision.vin, decision.campaign_id);
    const best = decisionByKey.get(key);
    if (best === undefined || decision.decided_on >= best.decided_on) decisionByKey.set(key, decision);
  }
  for (const vehicle of vehicles) {
    const key = vehicleKey(vehicle.vin, vehicle.campaign_id);
    const winner = decisionByKey.has(key) ? decisionByKey.get(key) : null;
    if (!sameDecision(vehicle.decision, winner)) {
      throw new ParseError("vehicle.decision disagrees with decisions for " + vehicle.vin + " " + vehicle.campaign_id);
    }
  }
  return {
    runId: data.run_id,
    ingestId: data.ingest_id,
    loadedAt: data.loaded_at,
    inputCheck: inputCheck,
    checkDate: report.check_date,
    dayLimit: report.day_limit,
    findings: findings,
    flaggedRepairs: flaggedRepairs,
    dataQuality: dataQuality,
    dataIssues: dataIssues,
    decisions: decisions,
    history: history,
    vehicles: vehicles,
    vehiclesByKey: vehiclesByKey,
    decisionByKey: decisionByKey,
    historyNewest: byNewest(history, "check_date"),
    decisionsNewest: byNewest(decisions, "decided_on"),
    runs: { phase: "idle" },
  };
}

function initialState(hash) {
  return {
    phase: "loading",
    message: null,
    messageIsError: false,
    desiredNav: parseHash(hash),
    index: null,
    cursor: null,
    exportChoice: {
      findings: true,
      flaggedRepairs: true,
      data: true,
      vehicles: true,
      runs: true,
      checks: false,
      decisions: true,
    },
    busy: false,
    epoch: 0,
  };
}

function dropReport(state, phase, message, isError) {
  return {
    phase: phase,
    message: message,
    messageIsError: isError,
    desiredNav: state.desiredNav,
    index: null,
    cursor: null,
    exportChoice: state.exportChoice,
    busy: false,
    epoch: state.epoch,
  };
}

function messageState(state, text, isError) {
  return Object.assign({}, state, { message: text, messageIsError: isError, busy: false });
}

function errorText(data, fallback) {
  if (data && typeof data.error === "string" && data.error !== "") return data.error;
  return fallback;
}

function reduce(state, command) {
  if (command === null || typeof command !== "object" || typeof command.type !== "string") {
    throw new Error("illegal command");
  }
  switch (command.type) {
  case "boot": {
    const epoch = state.epoch + 1;
    return { state: Object.assign({}, state, { epoch: epoch, busy: true }), effect: { type: "fetchReport", epoch: epoch } };
  }
  case "navigate": {
    const nav = parseHash(command.hash);
    if (state.phase === "ready" && state.cursor !== null && state.index !== null) {
      if (state.cursor.lensId === nav.lensId && samePin(state.cursor.pin, nav.pin)) {
        return { state: state, effect: null };
      }
      let index = state.index;
      let effect = null;
      if (nav.lensId === "history" && index.runs.phase === "idle") {
        index = withRuns(index, { phase: "loading" });
        effect = { type: "fetchRuns", epoch: state.epoch };
      }
      const cursor = {
        lensId: nav.lensId,
        pin: nav.pin,
        queries: state.cursor.queries,
        matches: matchesFor(lensById(nav.lensId), state.cursor.queries[nav.lensId], index),
      };
      return {
        state: Object.assign({}, state, { desiredNav: nav, index: index, cursor: cursor }),
        effect: effect,
      };
    }
    if (state.desiredNav.lensId === nav.lensId && samePin(state.desiredNav.pin, nav.pin)) {
      return { state: state, effect: null };
    }
    return { state: Object.assign({}, state, { desiredNav: nav }), effect: null };
  }
  case "query": {
    if (state.phase !== "ready" || state.cursor === null || state.index === null) {
      throw new Error("query requires a ready workspace");
    }
    if (command.lensId !== state.cursor.lensId) throw new Error("query lens " + command.lensId + " is not active");
    if (command.patch === null || typeof command.patch !== "object") throw new Error("query patch is missing");
    const lens = lensById(command.lensId);
    const nextQuery = Object.assign({}, state.cursor.queries[lens.id]);
    let changed = false;
    for (const key of Object.keys(command.patch)) {
      const field = lens.fields.find((item) => item.key === key);
      if (field === undefined) throw new Error("illegal query field " + key);
      const value = command.patch[key];
      if (typeof value !== "string") throw new Error("illegal value for " + key);
      if (field.control === "enum" && !Object.prototype.hasOwnProperty.call(field.labels, value)) {
        throw new Error("illegal value " + value + " for " + key);
      }
      if (nextQuery[key] !== value) {
        nextQuery[key] = value;
        changed = true;
      }
    }
    if (!changed) return { state: state, effect: null };
    const queries = Object.assign({}, state.cursor.queries);
    queries[lens.id] = nextQuery;
    return {
      state: Object.assign({}, state, {
        cursor: {
          lensId: state.cursor.lensId,
          pin: state.cursor.pin,
          queries: queries,
          matches: matchesFor(lens, nextQuery, state.index),
        },
      }),
      effect: null,
    };
  }
  case "report": {
    if (command.epoch !== state.epoch) return { state: state, effect: null };
    if (command.status === 200 || command.status === 201) {
      let index;
      try {
        index = parseReport(command.data);
      } catch (err) {
        if (err instanceof ParseError) return { state: dropReport(state, "fault", err.message, true), effect: null };
        throw err;
      }
      const cursor = state.cursor === null ? cursorFrom(state.desiredNav, index) : retarget(state.cursor, index);
      let effect = null;
      if (cursor.lensId === "history" && index.runs.phase === "idle") {
        index = withRuns(index, { phase: "loading" });
        effect = { type: "fetchRuns", epoch: state.epoch };
      }
      return {
        state: Object.assign({}, state, {
          phase: "ready",
          message: command.notice || null,
          messageIsError: false,
          index: index,
          cursor: cursor,
          busy: false,
        }),
        effect: effect,
      };
    }
    if (command.status === 400) return { state: dropReport(state, "empty", NO_CHECK, false), effect: null };
    if (command.status === 422) {
      return { state: dropReport(state, "fault", errorText(command.data, "The files could not be read."), true), effect: null };
    }
    const text = errorText(command.data, state.index === null
      ? "The report could not be loaded."
      : "The action could not be completed.");
    if (state.index === null) return { state: dropReport(state, "fault", text, true), effect: null };
    return { state: messageState(state, text, true), effect: null };
  }
  case "runs": {
    if (command.epoch !== state.epoch) return { state: state, effect: null };
    if (state.phase !== "ready" || state.index === null || state.index.runs.phase !== "loading") {
      return { state: state, effect: null };
    }
    const runs = command.status === 200 && Array.isArray(command.data.runs)
      ? { phase: "ready", rows: command.data.runs }
      : { phase: "failed", message: errorText(command.data, "The saved runs could not be loaded.") };
    return { state: Object.assign({}, state, { index: withRuns(state.index, runs) }), effect: null };
  }
  case "reload": {
    const epoch = state.epoch + 1;
    return {
      state: Object.assign({}, state, { epoch: epoch, busy: true }),
      effect: { type: "fetchReport", epoch: epoch, notice: command.notice || null },
    };
  }
  case "runCheck": {
    const epoch = state.epoch + 1;
    return {
      state: Object.assign({}, state, { epoch: epoch, busy: true }),
      effect: { type: "postJson", path: "/api/checks", body: {}, accept: "report", epoch: epoch },
    };
  }
  case "dayLimit": {
    if (!Number.isInteger(command.dayLimit) || command.dayLimit < 1) {
      throw new Error("day limit must be a whole number of 1 or more");
    }
    const epoch = state.epoch + 1;
    return {
      state: Object.assign({}, state, { epoch: epoch, busy: true }),
      effect: {
        type: "postJson",
        path: "/api/day-limit",
        body: { day_limit: command.dayLimit },
        accept: "report",
        epoch: epoch,
      },
    };
  }
  case "saveDecision": {
    if (typeof command.vin !== "string" || command.vin === "") throw new Error("decision vin is missing");
    if (typeof command.campaignId !== "string" || command.campaignId === "") {
      throw new Error("decision campaign is missing");
    }
    if (!STATUSES.includes(command.status)) throw new Error("illegal status " + command.status);
    if (typeof command.note !== "string") throw new Error("decision note is missing");
    const body = { vin: command.vin, campaign_id: command.campaignId, status: command.status };
    if (command.note !== "") body.note = command.note;
    const epoch = state.epoch + 1;
    return {
      state: Object.assign({}, state, { epoch: epoch, busy: true }),
      effect: { type: "postJson", path: "/api/decisions", body: body, accept: "thenReload", epoch: epoch },
    };
  }
  case "exportChoice": {
    if (!EXPORT_KEYS.includes(command.key)) throw new Error("illegal export choice " + command.key);
    if (typeof command.checked !== "boolean") throw new Error("export choice is missing");
    if (state.exportChoice[command.key] === command.checked) return { state: state, effect: null };
    const exportChoice = Object.assign({}, state.exportChoice);
    exportChoice[command.key] = command.checked;
    return { state: Object.assign({}, state, { exportChoice: exportChoice }), effect: null };
  }
  case "export": {
    if (state.phase !== "ready" || state.index === null) {
      return { state: messageState(state, "There is no report to export. Run a check first.", true), effect: null };
    }
    if (state.index.inputCheck && state.index.inputCheck.state === "unusable") {
      return {
        state: messageState(state, "The input files cannot be read, so this report is not exported. Fix the files and run a check.", true),
        effect: null,
      };
    }
    return { state: state, effect: { type: "print" } };
  }
  case "message":
    return { state: messageState(state, command.text, command.isError), effect: null };
  default:
    throw new Error("illegal command " + command.type);
  }
}

// Ctrl+P must not reprint an export from before this screen.
function clearPrintCopy() {
  $("print-report").replaceChildren();
}

function hideWork() {
  $("app").classList.remove("is-split");
  $("detail").hidden = true;
  $("detail").replaceChildren();
  $("stats").hidden = true;
  for (const lens of LENS_CATALOG) {
    $(lens.regionId).hidden = true;
    for (const pane of lens.panes) $(pane.mountId).replaceChildren();
    if (lens.runsMountId) $(lens.runsMountId).replaceChildren();
  }
  $("issues-band").hidden = false;
  $("quality-band").hidden = false;
}

function showError(text) {
  clearPrintCopy();
  $("input-warning").hidden = true;
  $("export-pdf").disabled = true;
  hideWork();
  showMessage(text, true);
}

function showNoCheckYet() {
  clearPrintCopy();
  $("input-warning").hidden = true;
  $("export-pdf").disabled = true;
  hideWork();
  showMessage(NO_CHECK, false);
}

function paintStats(index) {
  const counts = { notification: 0, repair: 0 };
  index.findings.forEach((finding) => {
    counts[finding.kind] = (counts[finding.kind] || 0) + 1;
  });
  const stats = $("stats");
  stats.replaceChildren();
  [
    ["Notification findings", counts.notification, "notification"],
    ["Repair findings", counts.repair, "repair"],
    ["Flagged repairs", index.flaggedRepairs.length, "repair"],
    ["Data issues", index.dataIssues.length, "data"],
    ["Data-quality flags", index.dataQuality.length, "data"],
  ].forEach(([label, n, tone]) => {
    const card = el("div", null, "stat " + tone);
    card.appendChild(el("span", String(n), "stat-n"));
    card.appendChild(el("span", label, "stat-l"));
    stats.appendChild(card);
  });
}

function render(index) {
  clearPrintCopy();
  const input_check = index.inputCheck;
  const note = filesNote(input_check);
  $("input-warning").textContent = note === null ? "" : note;
  $("input-warning").hidden = note === null;
  $("export-pdf").disabled = input_check !== undefined && input_check !== null && input_check.state === "unusable";
  $("day-limit").value = index.dayLimit;
  $("summary").textContent = "Data loaded from files " + loadedText(index.loadedAt) +
    " \u00b7 check date " + index.checkDate + " \u00b7 run " + index.runId +
    " \u00b7 repair limit " + index.dayLimit + " days";
  paintStats(index);
  $("stats").hidden = false;
}

function buildPrintReport(index, runs, choice) {
  const input_check = index.inputCheck;
  fillPrint(index, runs, choice, input_check);
}

function reportOf(index) {
  return {
    check_date: index.checkDate,
    day_limit: index.dayLimit,
    findings: index.findings,
    flagged_repairs: index.flaggedRepairs,
    data_quality: index.dataQuality,
    data_issues: index.dataIssues,
    decisions: index.decisions,
    history: index.history,
    vehicles: index.vehicles,
  };
}

function detailVehicles(report) {
  const flagged = new Set();
  report.findings.concat(report.data_quality, report.flagged_repairs).forEach((row) => {
    flagged.add(vehicleKey(row.vin, row.campaign_id));
  });
  return report.vehicles.filter((vehicle) => flagged.has(vehicleKey(vehicle.vin, vehicle.campaign_id)) ||
    vehicle.decision !== null || vehicle.data_quality_reasons.length > 0);
}

function exportParts(index) {
  const report = reportOf(index);
  return [
    ["findings", "Findings", report.findings.length + " notification and repair findings"],
    ["flaggedRepairs", "Flagged repairs", report.flagged_repairs.length + " repairs on unaffected vehicles"],
    ["data", "Missing and bad data",
      report.data_issues.length + " data issues and " + report.data_quality.length + " vehicle data-quality flags, kept apart"],
    ["vehicles", "Vehicle detail", detailVehicles(report).length + " vehicles with a finding, a flag or a decision"],
    ["runs", "Saved runs", "each check run with its date and day limit"],
    ["checks", "Every saved check", report.history.length + " rows from all saved runs. This can run to many pages"],
    ["decisions", "Coordinator decisions", report.decisions.length + " decisions, newest first"],
  ];
}

function printSection(root, title, tone, note) {
  const section = el("section", null, "print-section " + (tone || ""));
  section.appendChild(el("h2", title));
  if (note) section.appendChild(el("p", note, "print-note"));
  root.appendChild(section);
  return section;
}

function printTable(section, columns, rows, cell, emptyText) {
  section.appendChild(rows.length === 0 ? empty(emptyText) : table(columns, rows, cell));
}

function kpi(value, label, tone) {
  const card = el("div", null, "print-kpi " + tone);
  card.appendChild(el("span", String(value), "print-kpi-n"));
  card.appendChild(el("span", label, "print-kpi-l"));
  return card;
}

// A day count here would look overdue. The check does not score this vehicle.
function inAffectedList(vehicle) {
  return vehicle.facts.affected.length > 0;
}

function repairResult(vehicle) {
  if (!inAffectedList(vehicle)) return "Not applicable (not in the affected list)";
  if (vehicle.on_time === true) return el("span", "On time", "kind kind-ok");
  if (vehicle.on_time === false) return el("span", "Late", "kind kind-repair");
  return vehicle.notice_date_used === null
    ? "Not applicable (no notice date)" : "No repair on or after the notice";
}

function fillPrint(index, runs, choice, input_check) {
  const report = reportOf(index);
  const root = $("print-report");
  root.replaceChildren();
  const cover = el("div", null, "print-cover");
  const title = el("div");
  title.appendChild(el("p", DEALERSHIP_NAME, "print-dealer"));
  title.appendChild(el("h1", "Recall campaign report"));
  cover.appendChild(title);
  const meta = el("dl", null, "print-meta");
  [
    ["Check date", report.check_date],
    ["Run", "#" + index.runId],
    ["Repair day limit", report.day_limit + " days"],
    ["Data loaded", loadedText(index.loadedAt).replace(/^on /, "")],
  ].forEach(([key, value]) => {
    const item = el("div");
    item.appendChild(el("dt", key));
    item.appendChild(el("dd", value));
    meta.appendChild(item);
  });
  cover.appendChild(meta);
  root.appendChild(cover);
  const note = filesNote(input_check);
  if (note !== null) root.appendChild(el("p", note, "print-warning"));

  const counts = { notification: 0, repair: 0 };
  report.findings.forEach((finding) => { counts[finding.kind] = (counts[finding.kind] || 0) + 1; });
  const checked = report.vehicles.filter((vehicle) => vehicle.facts.affected.length > 0).length;
  const kpis = el("div", null, "print-kpis");
  kpis.appendChild(kpi(checked, "Vehicles checked (per campaign)", "total"));
  kpis.appendChild(kpi(counts.notification, "Notification findings", "notification"));
  kpis.appendChild(kpi(counts.repair, "Repair findings", "repair"));
  kpis.appendChild(kpi(report.flagged_repairs.length, "Flagged repairs", "repair"));
  kpis.appendChild(kpi(report.data_issues.length, "Data issues", "data"));
  kpis.appendChild(kpi(report.data_quality.length, "Data-quality flags", "data"));
  root.appendChild(kpis);
  root.appendChild(el("p",
    "Repair window: " + report.day_limit + " days, counting both the notice day and the repair day. " +
    "Data issues and flags are data problems, never findings.", "print-rule"));

  if (choice.findings) {
    const section = printSection(root, "Findings (" + report.findings.length + ")", "tone-findings");
    printTable(section, ["VIN", "Campaign", "Kind", "Reason"], report.findings,
      (finding) => [el("span", finding.vin, "mono"), el("span", finding.campaign_id, "nowrap"),
        kindBadge(finding.kind), isoDates(finding.reason)], "No findings in this check.");
  }
  if (choice.flaggedRepairs) {
    const section = printSection(root, "Flagged repairs (" + report.flagged_repairs.length + ")", "tone-findings",
      "Campaign eligibility requires a matching model and a build date within the inclusive campaign range.");
    printTable(section, FLAGGED_COLUMNS, report.flagged_repairs,
      (finding) => flaggedRepairCells(finding, false), "No repairs on unaffected vehicles in this check.");
  }
  if (choice.data) {
    const section = printSection(root, "Missing and bad data", "tone-data",
      "These are data problems, not findings. A row listed here is never treated as \"not notified\".");
    section.appendChild(el("h3", "Data issues (" + report.data_issues.length + ")"));
    printTable(section, ["File and row", "Code and action", "VIN", "Campaign", "Reason"], report.data_issues,
      (row) => [el("span", row.file + " \u00b7 row " + row.src_row, "nowrap"), codeCell(row),
        row.vin === null ? "not readable" : el("span", row.vin, "mono"),
        row.campaign_id === null ? "not readable" : el("span", row.campaign_id, "nowrap"), isoDates(row.reason)],
      "No data issues.");
    section.appendChild(el("h3", "Vehicle data-quality flags (" + report.data_quality.length + ")"));
    printTable(section, ["VIN", "Campaign", "Reason"], report.data_quality,
      (finding) => [el("span", finding.vin, "mono"), el("span", finding.campaign_id, "nowrap"), isoDates(finding.reason)],
      "No vehicle data-quality flags.");
  }
  if (choice.vehicles) {
    const detail = detailVehicles(report);
    const section = printSection(root, "Vehicle detail (" + detail.length + ")", "tone-vehicles",
      "Every vehicle with a finding, a data-quality flag or a coordinator decision. " +
      "With no repair on file, days are counted from the notice to the check date.");
    printTable(section, ["VIN", "Campaign", "In affected list", "In notices", "Notice used", "Repair used", "Days", "Limit",
      "Result", "Current decision", "Data problems"], detail,
      (vehicle) => [el("span", vehicle.vin, "mono"), el("span", vehicle.campaign_id, "nowrap"),
        inAffectedList(vehicle) ? "Yes" : "No", vehicle.in_notices ? "Yes" : "No",
        vehicle.notice_date_used, vehicle.repair_date_used,
        inAffectedList(vehicle) && vehicle.inclusive_days !== null ? String(vehicle.inclusive_days) : null,
        vehicle.day_limit, repairResult(vehicle),
        vehicle.decision === null ? "\u2014" : statusBadge(vehicle.decision.status),
        vehicle.data_quality_reasons.length === 0 ? "\u2014" : isoDates(vehicle.data_quality_reasons.join(" "))],
      "No vehicles have findings, flags or decisions.");
  }
  if (choice.runs) {
    const section = printSection(root, "Saved runs", "tone-history",
      "Every check that was run. A later upload never removes earlier rows.");
    if (runs === null) section.appendChild(empty("The saved runs could not be loaded."));
    else printTable(section, ["Run", "Check date", "Repair day limit", "Data load (ingest)"], runs.slice().reverse(),
      (row) => [row.run_id, row.check_date, row.day_limit, row.ingest_id], "No saved runs.");
  }
  if (choice.checks) {
    const section = printSection(root, "Every saved check (" + report.history.length + ")", "tone-history",
      "Newest first. Notification and repair entries are not ranked.");
    printTable(section, ["Check date", "VIN", "Campaign", "Kind", "Reason", "Day limit", "Current decision"],
      index.historyNewest,
      (row) => {
        const decision = index.decisionByKey.get(vehicleKey(row.vin, row.campaign_id));
        return [el("span", row.check_date, "nowrap"), el("span", row.vin, "mono"), el("span", row.campaign_id, "nowrap"),
          kindBadge(row.kind), isoDates(row.reason), row.day_limit,
          decision === undefined ? "\u2014" : statusBadge(decision.status)];
      }, "No checks have been saved yet.");
  }
  if (choice.decisions) {
    const section = printSection(root, "Coordinator decisions (" + report.decisions.length + ")", "tone-history",
      "Newest first. The latest decision for a vehicle is its current decision; earlier ones stay listed.");
    printTable(section, ["Decided on", "VIN", "Campaign", "Status", "Note"], index.decisionsNewest,
      (row) => [el("span", row.decided_on, "nowrap"), el("span", row.vin, "mono"),
        el("span", row.campaign_id, "nowrap"), statusBadge(row.status), row.note],
      "No decisions have been recorded yet.");
  }
  const left = exportParts(index).filter(([key]) => !choice[key]).map((part) => part[1]);
  if (left.length > 0) root.appendChild(el("p", "Not included in this PDF: " + left.join(", ") + ".", "print-omitted"));
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

function sameVehicle(vin, campaignId) {
  return (row) => row.vin === vin && row.campaign_id === campaignId;
}

function fillDetail(index, pin, lensId, dispatch) {
  const root = $("detail");
  root.replaceChildren();
  const close = el("a", "Close vehicle", "back");
  close.href = hashFor(lensId, null);
  root.appendChild(close);
  const vehicle = index.vehiclesByKey.get(vehicleKey(pin.vin, pin.campaignId));
  if (vehicle === undefined) {
    root.appendChild(empty("This vehicle and campaign are not in the current report."));
    return;
  }
  const title = el("h2", null, "detail-title");
  title.appendChild(el("span", vehicle.vin, "mono"));
  title.appendChild(el("span", "  " + vehicle.campaign_id, "detail-campaign"));
  root.appendChild(title);

  const facts = el("dl", null, "facts");
  const affected = inAffectedList(vehicle);
  facts.appendChild(fact("In affected list", affected ? "Yes" : "No",
    affected ? "" : "not checked for notice or repair days"));
  facts.appendChild(fact("In notices file", vehicle.in_notices ? "Yes" : "No"));
  facts.appendChild(fact("Notice date used",
    vehicle.notice_date_used === null ? "No usable notice date" : vehicle.notice_date_used,
    vehicle.notice_date_used === null ? "" : "earliest notice on file"));
  facts.appendChild(fact("Repair date used",
    vehicle.repair_date_used === null ? "No usable repair" : vehicle.repair_date_used,
    vehicle.repair_date_used === null ? "" : "earliest repair on or after the notice"));
  if (affected) {
    facts.appendChild(fact(
      vehicle.repair_date_used === null ? "Days since notice" : "Inclusive days, notice to repair",
      vehicle.inclusive_days === null ? "\u2014" : String(vehicle.inclusive_days),
      vehicle.repair_date_used === null && vehicle.inclusive_days !== null
        ? "counted to the check date " + index.checkDate : ""));
  }
  facts.appendChild(fact("Day limit", vehicle.day_limit + " days"));
  facts.appendChild(fact("Repair result", repairResult(vehicle)));
  if (vehicle.facts.vehicle) {
    facts.appendChild(fact("Vehicle model", vehicle.facts.vehicle.model));
    facts.appendChild(fact("Build date", vehicle.facts.vehicle.build_date));
  }
  if (vehicle.facts.campaign) {
    facts.appendChild(fact("Campaign model", vehicle.facts.campaign.model));
    facts.appendChild(fact("Campaign build date range",
      vehicle.facts.campaign.start_date + " to " + vehicle.facts.campaign.end_date, "both dates included"));
  }
  root.appendChild(facts);

  const pair = sameVehicle(vehicle.vin, vehicle.campaign_id);
  const found = index.findings.concat(index.flaggedRepairs).filter(pair);
  root.appendChild(el("h3", "Findings for this vehicle"));
  if (found.length === 0) root.appendChild(empty("No notification or repair finding for this vehicle."));
  else {
    const list = el("ul", null, "reasons");
    found.forEach((finding) => {
      const item = el("li");
      item.appendChild(kindBadge(finding.kind));
      item.appendChild(el("span", " " + isoDates(finding.reason)));
      list.appendChild(item);
    });
    root.appendChild(list);
  }

  root.appendChild(el("h3", "Dates on file"));
  const rows = [];
  vehicle.facts.notices.forEach((notice) => rows.push(["Notice", notice.notice_date, notice.notice_date === vehicle.notice_date_used]));
  vehicle.facts.repairs.forEach((repair) => rows.push(["Repair", repair.repair_date, repair.repair_date === vehicle.repair_date_used]));
  root.appendChild(rows.length === 0
    ? empty("No notice or repair dates on file for this vehicle.")
    : table(["Record", "Date", "Used by the check"], rows,
      (row) => [row[0], el("span", row[1], "nowrap"), row[2] ? "Yes" : "No"]));

  const problems = new Set(vehicle.data_quality_reasons);
  index.dataIssues.filter(pair).forEach((row) => problems.add(row.reason));
  if (problems.size > 0) {
    root.appendChild(el("h3", "Data problems (not findings)"));
    const list = el("ul", null, "reasons");
    problems.forEach((text) => list.appendChild(el("li", isoDates(text))));
    root.appendChild(list);
  }
  root.appendChild(decisionSection(index, vehicle, dispatch));
}

function decisionSection(index, vehicle, dispatch) {
  const section = el("section", null, "decision");
  section.appendChild(el("h3", "Coordinator decision"));
  const mine = index.decisions.filter(sameVehicle(vehicle.vin, vehicle.campaign_id));
  if (vehicle.decision === null) section.appendChild(el("p", "No decision recorded yet.", "muted"));
  else {
    const box = el("div", null, "current-decision");
    box.appendChild(statusBadge(vehicle.decision.status));
    box.appendChild(el("span", " on " + vehicle.decision.decided_on, "hint"));
    if (vehicle.decision.note) box.appendChild(el("p", vehicle.decision.note, "note"));
    section.appendChild(box);
  }
  const form = el("form", null, "decision-form");
  const fieldset = el("fieldset");
  fieldset.appendChild(el("legend", "Record a decision"));
  STATUSES.forEach((status) => {
    const label = el("label", null, "choice");
    const input = el("input");
    input.type = "radio";
    input.name = "status";
    input.value = status;
    input.required = true;
    label.appendChild(input);
    label.appendChild(el("span", " " + status));
    fieldset.appendChild(label);
  });
  form.appendChild(fieldset);
  const noteLabel = el("label", "Note (optional)", "note-label");
  noteLabel.htmlFor = "decision-note";
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
    const chosen = form.querySelector("input[name=status]:checked");
    if (chosen === null) {
      dispatch({ type: "message", text: "Choose reviewed, follow up or no action.", isError: true });
      return;
    }
    dispatch({
      type: "saveDecision",
      vin: vehicle.vin,
      campaignId: vehicle.campaign_id,
      status: chosen.value,
      note: note.value.trim(),
    });
  });
  section.appendChild(form);
  if (mine.length > 0) {
    section.appendChild(el("h3", "Decision history"));
    section.appendChild(table(["Date", "Status", "Note"], mine.slice().reverse(),
      (row) => [el("span", row.decided_on, "nowrap"), statusBadge(row.status), row.note]));
  }
  return section;
}

function api(method, path, body) {
  const options = { method: method, headers: {} };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  return fetch(path, options).then((response) => response.json().then(
    (data) => ({ status: response.status, data: data }),
    () => ({ status: response.status, data: { error: "The server sent an unreadable response." } })
  ), () => ({ status: 0, data: { error: "Cannot reach the tracker server." } }));
}

function mountWorkspace(doc, ports) {
  if (doc === null || typeof doc.getElementById !== "function") {
    throw new Error("mountWorkspace requires the page document");
  }
  if (typeof ports.request !== "function") throw new Error("mountWorkspace requires ports.request");
  const api = ports.request;
  requireMounts();

  let state = initialState(location.hash);
  let paintedFindings = null;
  let paintedRuns = null;
  let paintedLens = null;
  let paintedMatches = null;
  let detailPin = "";
  let detailFindings = null;
  const bars = new Map();
  const filterControls = new Map();

  function requireMounts() {
    $("dealer");
    $("summary");
    $("stats");
    $("message");
    $("input-warning");
    $("detail");
    $("export-pdf");
    $("export-dialog");
    $("export-form");
    $("export-cancel");
    $("export-options");
    $("print-report");
    $("day-limit");
    $("limit-form");
    $("run-check");
    $("app");
    $("nav-flags");
    $("nav-flagged-repairs");
    $("nav-data-problems");
    $("nav-history");
    $("report");
    $("findings");
    $("findings-filters");
    $("flagged-repairs");
    $("flagged-filters");
    $("flagged-repairs-list");
    $("data-problems");
    $("data-filters");
    $("data-issues");
    $("data-quality");
    $("issues-band");
    $("quality-band");
    $("history");
    $("history-runs");
    $("history-filters");
    $("history-count");
    $("history-checks");
    $("history-decisions");
    $("history-decisions-title");
  }

  function forgetPaint() {
    paintedFindings = null;
    paintedRuns = null;
    paintedLens = null;
    paintedMatches = null;
    detailPin = "";
    detailFindings = null;
    bars.clear();
    filterControls.clear();
  }

  function dispatch(command) {
    const outcome = reduce(state, command);
    if (outcome.state === state && outcome.effect === null) return;
    state = outcome.state;
    paint(state, outcome.effect);
    if (state.phase === "ready" && state.cursor !== null) reflectHash(state.cursor);
    const effect = outcome.effect;
    if (effect !== null && (effect.type === "fetchReport" || effect.type === "fetchRuns" || effect.type === "postJson")) {
      runEffect(effect);
    }
  }

  function paintBusy(next) {
    $("run-check").disabled = next.busy;
    $("limit-form").querySelector("button").disabled = next.busy;
    const buttons = $("detail").querySelectorAll("button");
    for (let i = 0; i < buttons.length; i++) buttons[i].disabled = next.busy;
  }

  function paintNav(cursor) {
    for (const lens of LENS_CATALOG) {
      const link = $(lens.navId);
      link.href = hashFor(lens.id, cursor.pin);
      link.classList.toggle("active", lens.id === cursor.lensId);
    }
  }

  function bandAllows(lens, pane, query) {
    if (lens.id !== "dataProblems" || query.band === "") return true;
    return pane.id === query.band;
  }

  function paintPane(lens, pane, index, query, indexes) {
    const mount = $(pane.mountId);
    if (!bandAllows(lens, pane, query)) {
      if (pane.bandId) $(pane.bandId).hidden = true;
      mount.replaceChildren();
      return;
    }
    if (pane.bandId) $(pane.bandId).hidden = false;
    const rows = pane.ordered(index);
    let shownIndexes = indexes;
    let shown = indexes.length;
    // The sentence still names every match. The cap is only how many rows are built.
    if (pane.id === "checks") {
      shown = Math.min(indexes.length, CHECK_ROW_CAP);
      shownIndexes = indexes.slice(0, shown);
    }
    if (typeof pane.count === "function") {
      $("history-count").textContent = pane.count(shown, indexes.length, index.historyNewest.length);
    }
    if (pane.id === "decisions") {
      $("history-decisions-title").textContent = "Coordinator decisions (" + indexes.length + ")";
    }
    if (shownIndexes.length === 0) {
      mount.replaceChildren(empty(rows.length === 0 ? pane.emptySource : pane.emptyMatch));
      return;
    }
    const picked = shownIndexes.map((i) => rows[i]);
    mount.replaceChildren(table(pane.columns, picked, (row) => pane.cells(row, index, lens.id)));
  }

  function paintRuns(index) {
    const box = $("history-runs");
    const runs = index.runs;
    if (runs.phase === "loading") {
      box.replaceChildren(empty("Loading saved runs\u2026"));
      return;
    }
    if (runs.phase === "failed") {
      box.replaceChildren(empty(runs.message));
      return;
    }
    if (runs.phase !== "ready") throw new Error("unknown runs phase " + runs.phase);
    const rows = runs.rows.slice().reverse();
    box.replaceChildren(rows.length === 0
      ? empty("No saved runs.")
      : table(["Run", "Check date", "Repair day limit", "Data load (ingest)"], rows,
        (row) => [row.run_id, row.check_date, row.day_limit, row.ingest_id]));
  }

  function distinctValues(lens, prop, index) {
    const seen = new Set();
    const values = [];
    for (const pane of lens.panes) {
      for (const row of pane.ordered(index)) {
        const value = row[prop];
        if (value === null || value === undefined || value === "") continue;
        const token = String(value);
        if (seen.has(token)) continue;
        seen.add(token);
        values.push(value);
      }
    }
    values.sort((left, right) => {
      if (typeof left === "number" && typeof right === "number") return left - right;
      const a = String(left);
      const b = String(right);
      if (a < b) return -1;
      if (a > b) return 1;
      return 0;
    });
    return values;
  }

  function optionPairs(field, lens, index, selected) {
    if (field.control === "enum") {
      return Object.keys(field.labels).map((value) => [value, field.labels[value]]);
    }
    const options = [["", "Any"]];
    const seen = new Set();
    distinctValues(lens, field.prop, index).forEach((value) => {
      const token = String(value);
      seen.add(token);
      options.push([token, token]);
    });
    if (selected !== "" && !seen.has(selected)) options.push([selected, selected]);
    return options;
  }

  function buildFilters(lens, query, index) {
    const bar = el("div", null, "filters");
    const controls = {};
    for (const field of lens.fields) {
      let control;
      if (field.control === "search" || field.control === "date") {
        control = el("input");
        control.type = field.control === "date" ? "date" : "search";
        if (field.placeholder) control.placeholder = field.placeholder;
      } else {
        control = el("select");
        optionPairs(field, lens, index, query[field.key]).forEach(([value, text]) => {
          const option = el("option", text);
          option.value = value;
          control.appendChild(option);
        });
      }
      control.value = query[field.key];
      const listen = field.control === "search" || field.control === "date" ? "input" : "change";
      control.addEventListener(listen, () => {
        dispatch({ type: "query", lensId: lens.id, patch: { [field.key]: control.value } });
      });
      controls[field.key] = control;
      const wrap = el("label", null, "filter");
      wrap.appendChild(el("span", field.label));
      wrap.appendChild(control);
      bar.appendChild(wrap);
    }
    const clear = el("button", "Clear filters", "secondary");
    clear.type = "button";
    clear.addEventListener("click", () => {
      dispatch({ type: "query", lensId: lens.id, patch: emptyQuery(lens) });
    });
    bar.appendChild(clear);
    $(lens.filtersId).replaceChildren(bar);
    filterControls.set(lens.id, controls);
    bars.set(lens.id, index.findings);
  }

  function syncFilters(lens, query) {
    const controls = filterControls.get(lens.id);
    if (controls === undefined) throw new Error("missing filters for " + lens.id);
    for (const field of lens.fields) {
      const control = controls[field.key];
      if (document.activeElement !== control && control.value !== query[field.key]) {
        control.value = query[field.key];
      }
    }
  }

  function paintDetail(index, cursor) {
    const root = $("detail");
    if (cursor.pin === null) {
      root.hidden = true;
      root.replaceChildren();
      detailPin = "";
      detailFindings = null;
      return;
    }
    const pinKey = vehicleKey(cursor.pin.vin, cursor.pin.campaignId);
    root.hidden = false;
    if (detailPin === pinKey && detailFindings === index.findings) return;
    detailPin = pinKey;
    detailFindings = index.findings;
    fillDetail(index, cursor.pin, cursor.lensId, dispatch);
  }

  function paint(next, effect) {
    if (next.phase !== "ready" || next.index === null || next.cursor === null) {
      forgetPaint();
      if (next.phase === "empty") showNoCheckYet();
      else if (next.phase === "fault") showError(next.message || "The report could not be loaded.");
      else {
        hideWork();
        $("export-pdf").disabled = true;
        $("input-warning").hidden = true;
        if (next.message === null) clearMessage();
        else showMessage(next.message, next.messageIsError);
      }
      paintBusy(next);
      return;
    }
    const index = next.index;
    const cursor = next.cursor;
    const lens = lensById(cursor.lensId);
    const reportChanged = paintedFindings !== index.findings;
    if (reportChanged) {
      paintedFindings = index.findings;
      render(index);
    }
    $("app").classList.toggle("is-split", cursor.pin !== null);
    paintNav(cursor);
    if (reportChanged || paintedLens !== lens.id) {
      for (const entry of LENS_CATALOG) {
        if (entry.id === lens.id) continue;
        for (const pane of entry.panes) $(pane.mountId).replaceChildren();
        if (entry.runsMountId) $(entry.runsMountId).replaceChildren();
      }
      if (lens.id !== "history") paintedRuns = null;
    }
    for (const entry of LENS_CATALOG) $(entry.regionId).hidden = entry.id !== lens.id;
    const query = cursor.queries[lens.id];
    if (bars.get(lens.id) !== index.findings) buildFilters(lens, query, index);
    else syncFilters(lens, query);
    const tablesChanged = reportChanged || paintedLens !== lens.id || paintedMatches !== cursor.matches;
    if (tablesChanged) {
      for (const pane of lens.panes) {
        const indexes = cursor.matches[pane.id];
        if (indexes === undefined) throw new Error("missing matches for " + pane.id);
        paintPane(lens, pane, index, query, indexes);
      }
      paintedLens = lens.id;
      paintedMatches = cursor.matches;
    }
    if (lens.runsMountId) {
      if (paintedRuns !== index.runs) {
        paintRuns(index);
        paintedRuns = index.runs;
      }
    }
    paintDetail(index, cursor);
    if (next.message === null) clearMessage();
    else showMessage(next.message, next.messageIsError);
    paintBusy(next);
    if (effect !== null && effect.type === "print") startPrint(index, Object.assign({}, next.exportChoice));
  }

  function fillExportOptions() {
    if (state.index === null) throw new Error("export requires a report");
    const box = $("export-options");
    box.replaceChildren();
    exportParts(state.index).forEach(([key, label, hint]) => {
      const row = el("label", null, "export-option");
      const input = el("input");
      input.type = "checkbox";
      input.checked = state.exportChoice[key];
      input.addEventListener("change", () => {
        dispatch({ type: "exportChoice", key: key, checked: input.checked });
      });
      const text = el("span");
      text.appendChild(el("strong", label));
      text.appendChild(el("span", hint, "hint"));
      row.appendChild(input);
      row.appendChild(text);
      box.appendChild(row);
    });
  }

  async function startPrint(index, choice) {
    const button = $("export-pdf");
    button.disabled = true;
    try {
      let runs = null;
      if (choice.runs) {
        const saved = await api("GET", "/api/runs");
        runs = saved.status === 200 && Array.isArray(saved.data.runs) ? saved.data.runs : null;
      }
      buildPrintReport(index, runs, choice);
      const title = document.title;
      document.title = "Recall report " + index.checkDate + " run " + index.runId;
      window.addEventListener("afterprint", () => { document.title = title; }, { once: true });
      window.print();
    } finally {
      const current = state.index;
      button.disabled = state.phase !== "ready" || current === null ||
        (current.inputCheck !== undefined && current.inputCheck !== null && current.inputCheck.state === "unusable");
    }
  }

  async function runEffect(effect) {
    if (effect.type === "fetchReport") {
      const fresh = await api("GET", "/api/report");
      if (effect.notice && fresh.status !== 200) {
        dispatch({ type: "report", epoch: effect.epoch, status: fresh.status, data: fresh.data });
        dispatch({
          type: "message",
          text: "The decision was saved, but the report could not be reloaded.",
          isError: true,
        });
        return;
      }
      dispatch({
        type: "report",
        epoch: effect.epoch,
        status: fresh.status,
        data: fresh.data,
        notice: effect.notice || null,
      });
      return;
    }
    if (effect.type === "fetchRuns") {
      const saved = await api("GET", "/api/runs");
      dispatch({ type: "runs", epoch: effect.epoch, status: saved.status, data: saved.data });
      return;
    }
    if (effect.type === "postJson") {
      let saved;
      if (effect.path === "/api/checks") saved = await api("POST", "/api/checks", effect.body);
      else if (effect.path === "/api/day-limit") saved = await api("POST", "/api/day-limit", effect.body);
      else if (effect.path === "/api/decisions") saved = await api("POST", "/api/decisions", effect.body);
      else throw new Error("illegal post " + effect.path);
      if (effect.accept === "report") {
        dispatch({ type: "report", epoch: effect.epoch, status: saved.status, data: saved.data });
        return;
      }
      if (effect.accept === "thenReload") {
        if (saved.status !== 201) {
          dispatch({
            type: "message",
            text: errorText(saved.data, "The decision could not be saved."),
            isError: true,
          });
          return;
        }
        dispatch({ type: "reload", notice: "Decision saved." });
        return;
      }
      throw new Error("illegal post result " + effect.accept);
    }
    throw new Error("paint owns effect " + effect.type);
  }

  function wire() {
    $("dealer").textContent = DEALERSHIP_NAME;
    window.addEventListener("hashchange", () => dispatch({ type: "navigate", hash: location.hash }));
    $("run-check").addEventListener("click", () => dispatch({ type: "runCheck" }));
    $("limit-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const value = Number($("day-limit").value);
      if (!Number.isInteger(value) || value < 1) {
        dispatch({
          type: "message",
          text: "The repair day limit must be a whole number of 1 or more.",
          isError: true,
        });
        return;
      }
      dispatch({ type: "dayLimit", dayLimit: value });
    });
    $("export-pdf").addEventListener("click", () => {
      if (state.phase !== "ready" || state.index === null) {
        dispatch({ type: "message", text: "There is no report to export. Run a check first.", isError: true });
        return;
      }
      fillExportOptions();
      $("export-dialog").showModal();
    });
    $("export-form").addEventListener("submit", (event) => {
      event.preventDefault();
      $("export-dialog").close();
      dispatch({ type: "export" });
    });
    $("export-cancel").addEventListener("click", () => $("export-dialog").close());
  }

  wire();
  dispatch({ type: "boot" });
}

mountWorkspace(document, { request: api });
