"use strict";

const WAITING_DAYS = 7; // highlight candidates waiting this long
const RATING_POLL_MS = 2000;
const CATEGORY_LABELS = { skills: "Skills", experience: "Experience", relevance: "Role relevance", budget: "Budget fit" };

const $ = (id) => document.getElementById(id);
const state = { stages: [], candidates: [], jobs: [], ai: { search: false, rating: false }, openId: null, searchRun: 0 };

/* ---- helpers ---- */

// Builds a DOM node. Children go in as text, never HTML.
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (value !== false && value != null) node.setAttribute(key, value === true ? "" : value);
  }
  node.append(...children.flat().filter((child) => child != null && child !== false));
  return node;
}

// fetch wrapper. Throws with the API's message. `body` goes as JSON, `form` as multipart.
async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      method: options.method || "GET",
      headers: options.body ? { "Content-Type": "application/json" } : undefined,
      body: options.form || (options.body ? JSON.stringify(options.body) : undefined),
    });
  } catch {
    throw new Error("Can't reach the server. Check that it is running and try again.");
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const error = new Error(body?.message || `Something went wrong (${response.status}).`);
    error.code = body?.error;
    throw error;
  }
  return body;
}

function duration(seconds) {
  if (seconds < 3600) return "less than an hour";
  if (seconds < 86400) {
    const hours = Math.floor(seconds / 3600);
    return hours === 1 ? "1 hour" : `${hours} hours`;
  }
  const days = Math.floor(seconds / 86400);
  return days === 1 ? "1 day" : `${days} days`;
}

function dateTime(iso) {
  return new Date(iso).toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata", day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit",
  }) + " IST";
}

function money(amount, currency) {
  if (currency !== "INR") return `${currency} ${new Intl.NumberFormat().format(amount)}`;
  const lakhs = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 }).format(amount / 100000);
  return `₹${new Intl.NumberFormat("en-IN").format(amount)} (${lakhs} LPA)`;
}

const isFinal = (candidate) => candidate.actions.length === 0;

function timeInStage(candidate) {
  const waiting = !isFinal(candidate) && candidate.days_in_stage >= WAITING_DAYS;
  return el("span", { class: waiting ? "waiting" : "" }, duration(candidate.seconds_in_stage));
}

/* ---- board ---- */

async function loadBoard() {
  const board = await api("/api/candidates");
  state.stages = board.stages;
  state.candidates = board.candidates;
  renderBoard();
  loadAudit();
}

function renderBoard() {
  $("welcome").hidden = state.candidates.length > 0;
  const columns = state.stages.map((stage) => {
    const inStage = state.candidates
      .filter((candidate) => candidate.stage === stage.key)
      .sort((a, b) => b.seconds_in_stage - a.seconds_in_stage);
    return el("div", { class: `column ${stage.key}` },
      el("h2", {}, stage.label, el("span", {}, String(inStage.length))),
      inStage.length ? inStage.map(boardCard) : el("p", { class: "none" }, "No one here"));
  });
  $("board").replaceChildren(...columns);
}

function boardCard(candidate) {
  const where = candidate.rejected_from ? `from ${labelOf(candidate.rejected_from)}, ` : "";
  return el("button", { class: "card", type: "button", onclick: () => openPanel(candidate.id) },
    el("div", { class: "name" }, candidate.name),
    el("div", { class: "meta" }, where, timeInStage(candidate), isFinal(candidate) ? " ago" : " here"));
}

function labelOf(stageKey) {
  return state.stages.find((stage) => stage.key === stageKey)?.label || stageKey;
}

async function loadAudit() {
  try {
    const audit = await api("/api/audit/verify");
    $("audit").textContent = audit.ok ? `History intact: ${audit.events} events verified.` : audit.message;
    $("audit").classList.toggle("broken", !audit.ok);
  } catch {
    $("audit").textContent = "";
  }
}

/* ---- search ---- */

// The search box is a name search. Everything else is a filter from the Filters panel.
// On Enter, with AI on, a question typed in the box is turned into filters.

const NO_FILTERS = {
  stages: [], exclude: [], min_days: null, max_days: null, reached: null, reached_when: "since", reached_date: null,
  not_reached: null, job: null,
  advanced: "", // conditions from a question that no menu can hold; shown as a chip in plain English
};
state.filters = { ...NO_FILTERS };
state.advancedLabel = null;
const WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];

let searchTimer;

function onSearchInput() {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(runSearch, 250);
}

function hasFilters(filters = state.filters) {
  return Object.entries(filters).some(([key, value]) =>
    key !== "reached_when" && (Array.isArray(value) ? value.length : value != null && value !== ""));
}

function searchParams() {
  const params = new URLSearchParams();
  const name = $("search").value.trim();
  if (name) params.append("name", name);
  for (const [key, value] of Object.entries(state.filters)) {
    if (Array.isArray(value)) value.forEach((item) => params.append(key, item));
    else if (value != null && value !== "") params.append(key, value);
  }
  params.append("tz_offset", new Date().getTimezoneOffset());
  return params;
}

// As-you-type search. Never uses AI.
async function runSearch() {
  const run = ++state.searchRun;
  showAssist(null);
  renderChips();
  if (!$("search").value.trim() && !hasFilters()) {
    showSearchError(null);
    $("results").hidden = true;
    $("board").hidden = false;
    return;
  }
  try {
    const found = await api(`/api/search?${searchParams()}`);
    if (run !== state.searchRun) return; // a newer search has started
    showSearchError(null);
    renderResults(found);
  } catch (error) {
    if (run !== state.searchRun) return;
    showSearchError(error);
  }
}

// On Enter. The server only uses AI if the typed words match no candidate's name.
async function runAssist() {
  const text = $("search").value.trim();
  if (!text || !state.ai.search) return runSearch();
  const run = ++state.searchRun;
  showAssist(el("span", { class: "muted" }, "Working out what you meant…"));
  let answer;
  try {
    answer = await api("/api/assist", {
      method: "POST",
      body: { text, filters: state.filters, tz_offset: new Date().getTimezoneOffset() },
    });
  } catch {
    return runSearch(); // fall back to plain search
  }
  if (run !== state.searchRun) return;

  showSearchError(answer.error);
  if (answer.path === "interpreted") {
    useFilters(answer.filters);
    renderResults(answer);
    showAssist(
      el("div", {}, answer.message),
      el("div", { class: "assist-actions" },
        el("button", { class: "link", type: "button", onclick: openFilters }, "Adjust these filters")));
    return;
  }
  if (answer.results) {
    renderResults(answer);
  } else if (!answer.error) {
    // Nothing was run, so don't leave stale results up.
    $("results").hidden = true;
    $("board").hidden = false;
  }
  if (answer.path === "suggestion") {
    showAssist(
      el("div", {}, answer.message),
      el("div", { class: "assist-description" }, answer.description),
      el("div", { class: "assist-actions" },
        el("button", { class: "button primary", type: "button",
          onclick: () => { useFilters(answer.filters); runSearch(); } }, "Apply these filters"),
        el("button", { class: "button", type: "button",
          onclick: () => { setPanel(answer.filters); openFilters(); } }, "Adjust them first")));
  } else {
    showAssist(answer.message ? el("div", {}, answer.message) : null);
  }
}

// Filters from the AI replace the current ones; its name words go in the search box.
function useFilters(filters) {
  const { name, ...rest } = filters;
  $("search").value = name || "";
  state.filters = { ...NO_FILTERS, ...rest };
  setPanel(state.filters);
  renderChips();
}

function showAssist(...children) {
  const parts = children.filter((child) => child != null);
  $("assist").hidden = parts.length === 0;
  $("assist").replaceChildren(...parts);
}

// Why the search can't run. Previous results stay visible.
function showSearchError(error) {
  const box = $("search-error");
  $("search").classList.toggle("invalid", Boolean(error));
  box.hidden = !error;
  if (error) box.replaceChildren(el("div", {}, error.message));
}

function renderResults(found) {
  state.advancedLabel = found.advanced_description ?? state.advancedLabel;
  renderChips();
  const heading = found.count === 1 ? "1 candidate" : `${found.count} candidates`;
  $("results").replaceChildren(...[
    el("h2", {}, found.count ? heading : "No matches"),
    // Exactly what was searched, so she never has to guess.
    found.description ? el("p", { class: "searching" }, found.description.replace(/^Candidates who/, "Showing candidates who"))
      : null,
    found.explanation ? el("p", { class: "explanation" }, found.explanation) : null,
    ...found.results.map((candidate) =>
      el("button", { class: "card", type: "button", onclick: () => openPanel(candidate.id) },
        el("div", {},
          el("div", { class: "name" }, candidate.name),
          el("div", { class: "meta" }, candidate.email, candidate.job_id ? ` · ${candidate.job_id}` : "", " · ",
            timeInStage(candidate), isFinal(candidate) ? " ago" : " in stage")),
        el("span", { class: `stage-tag ${candidate.stage}` }, candidate.stage_label))),
  ].filter(Boolean));
  $("results").hidden = false;
  $("board").hidden = true;
}

/* ---- filters ---- */

function renderFilters() {
  for (const id of ["f-stage", "f-exclude"]) {
    $(id).querySelector(".options").replaceChildren(...state.stages.map((stage) =>
      el("label", {}, el("input", { type: "checkbox", value: stage.key }), stage.label)));
    $(id).addEventListener("change", () => updateMultiLabel(id));
  }
  $("f-reached").append(...state.stages.map((stage) => el("option", { value: stage.key }, stage.label)));
  $("f-never").append(...state.stages.map((stage) => el("option", { value: stage.key }, stage.label)));
  $("f-job").append(...state.jobs.map((job) => el("option", { value: job.id }, `${job.id} · ${job.title}`)));
  $("job-ids").replaceChildren(...state.jobs.map((job) => el("option", { value: job.id }, job.title)));
}

function checked(id) {
  return [...$(id).querySelectorAll("input:checked")].map((box) => box.value);
}

function updateMultiLabel(id) {
  const labels = checked(id).map(labelOf);
  const none = id === "f-stage" ? "Any stage" : "None";
  $(id).querySelector("summary").textContent = labels.length ? labels.join(", ") : none;
}

// The panel's controls as filters.
function readPanel() {
  const time = $("f-for").value ? JSON.parse($("f-for").value) : {};
  return {
    ...NO_FILTERS,
    stages: checked("f-stage"),
    exclude: checked("f-exclude"),
    min_days: time.min_days ?? null,
    max_days: time.max_days ?? null,
    reached: $("f-reached").value || null,
    reached_when: $("f-when").value,
    reached_date: ($("f-reached").value && $("f-date").value) || null,
    not_reached: $("f-never").value || null,
    job: $("f-job").value || null,
    advanced: state.filters.advanced, // not editable in the panel; removed with its chip
  };
}

// Shows `filters` in the panel, adding options the dropdowns don't have (e.g. from the AI).
function setPanel(filters) {
  for (const [id, values] of [["f-stage", filters.stages || []], ["f-exclude", filters.exclude || []]]) {
    $(id).querySelectorAll("input").forEach((box) => { box.checked = values.includes(box.value); });
    updateMultiLabel(id);
  }
  const time = {};
  if (filters.min_days != null) time.min_days = filters.min_days;
  if (filters.max_days != null) time.max_days = filters.max_days;
  selectValue("f-for", Object.keys(time).length ? JSON.stringify(time) : "", timeLabel(time));
  selectValue("f-job", filters.job || "", filters.job);
  $("f-reached").value = filters.reached || "";
  $("f-when").value = filters.reached_when || "since";
  selectValue("f-date", filters.reached_date || "", dayLabel(filters.reached_date));
  $("f-never").value = filters.not_reached || "";
  enableWhen();
}

function selectValue(id, value, label) {
  const select = $(id);
  if (value && ![...select.options].some((option) => option.value === value)) {
    select.append(el("option", { value }, label));
  }
  select.value = value;
}

function days(count) {
  return count === 1 ? "1 day" : `${count} days`;
}

function timeLabel(time) {
  if (time.min_days != null && time.max_days != null) return `${days(time.min_days)} to ${days(time.max_days)}`;
  if (time.min_days != null) return `More than ${days(time.min_days)}`;
  if (time.max_days != null) return `Less than ${days(time.max_days)}`;
  return "Any";
}

function enableWhen() {
  const reached = Boolean($("f-reached").value);
  $("f-when").disabled = !reached;
  $("f-date").disabled = !reached;
}

// "today", "monday", "7d" (ago), "2026-09-01" -> words.
function dayLabel(day) {
  if (!day) return "Any time";
  const option = [...$("f-date").options].find((item) => item.value === day);
  if (option) return option.textContent;
  if (WEEKDAYS.includes(day)) return day[0].toUpperCase() + day.slice(1);
  const ago = day.match(/^(\d+)([dh])$/);
  if (ago) return `${ago[1]} ${ago[2] === "d" ? "days" : "hours"} ago`;
  const date = new Date(`${day}T00:00:00`);
  return Number.isNaN(date.getTime()) ? day
    : date.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

// One removable chip per active filter, so she can see what's applied with the panel closed.
function renderChips() {
  const filters = state.filters;
  const stageList = (keys) => keys.map(labelOf).join(", ");
  const chips = [];
  if (filters.stages.length) chips.push([`Stage: ${stageList(filters.stages)}`, { stages: [] }]);
  if (filters.exclude.length) chips.push([`Excluding: ${stageList(filters.exclude)}`, { exclude: [] }]);
  if (filters.min_days != null || filters.max_days != null) {
    chips.push([`In stage: ${timeLabel(filters).toLowerCase()}`, { min_days: null, max_days: null }]);
  }
  if (filters.reached) {
    const day = dayLabel(filters.reached_date);
    const relative = /^(Today|Yesterday)$/.test(day);
    const words = relative ? day.toLowerCase() : day;
    // "reached Screening yesterday", not "on yesterday".
    const when = !filters.reached_date ? "" : relative && filters.reached_when === "on" ? ` ${words}`
      : ` ${filters.reached_when} ${words}`;
    chips.push([`Reached ${labelOf(filters.reached)}${when}`, { reached: null, reached_when: "since", reached_date: null }]);
  }
  if (filters.not_reached) chips.push([`Never reached ${labelOf(filters.not_reached)}`, { not_reached: null }]);
  if (filters.job) chips.push([`Job: ${filters.job}`, { job: null }]);
  if (filters.advanced) {
    chips.push([`Also: ${state.advancedLabel || "conditions from your question"}`, { advanced: "" }]);
  }

  $("active-filters").hidden = chips.length === 0;
  $("filter-count").hidden = chips.length === 0;
  $("filter-count").textContent = String(chips.length);
  $("active-filters").replaceChildren(
    ...chips.map(([label, cleared]) =>
      el("span", { class: "chip" }, label,
        el("button", {
          type: "button", "aria-label": `Remove filter: ${label}`,
          onclick: () => { state.filters = { ...state.filters, ...cleared }; setPanel(state.filters); runSearch(); },
        }, "×"))),
    chips.length > 1 ? el("button", { class: "link", type: "button", onclick: clearFilters }, "Clear all") : null);
}

function openFilters() {
  $("filters").hidden = false;
  $("filter-toggle").setAttribute("aria-expanded", "true");
}

function applyFilters(event) {
  event.preventDefault();
  closeMultis();
  state.filters = readPanel();
  clearTimeout(searchTimer);
  runSearch();
}

function clearFilters() {
  $("filters").reset();
  state.filters = { ...NO_FILTERS };
  setPanel(state.filters);
  runSearch();
}

function closeMultis(except) {
  document.querySelectorAll(".multi[open]").forEach((multi) => {
    if (multi !== except) multi.open = false;
  });
}

/* ---- candidate panel ---- */

let ratingTimer;

async function openPanel(id, message) {
  state.openId = id;
  clearTimeout(ratingTimer);
  let candidate = null;
  try {
    candidate = await api(`/api/candidates/${id}`);
    renderPanel(candidate, message);
  } catch (error) {
    renderPanel(null, error.message);
  }
  $("backdrop").hidden = false;
  $("panel").hidden = false;
  if (candidate?.rating.status === "pending") ratingTimer = setTimeout(() => pollRating(id), RATING_POLL_MS);
}

// Poll until the rating finishes, then redraw.
async function pollRating(id) {
  if (state.openId !== id) return;
  try {
    const rating = await api(`/api/candidates/${id}/rating`);
    if (state.openId !== id) return;
    if (rating.status !== "pending") return openPanel(id);
  } catch { /* try again on the next tick */ }
  ratingTimer = setTimeout(() => pollRating(id), RATING_POLL_MS);
}

function closePanel() {
  state.openId = null;
  clearTimeout(ratingTimer);
  $("panel").hidden = true;
  $("backdrop").hidden = true;
}

function renderPanel(candidate, message) {
  const close = el("button", { class: "button", type: "button", onclick: closePanel, "aria-label": "Close" }, "Close");
  if (!candidate) {
    $("panel").replaceChildren(el("div", { class: "panel-head" }, el("h2", {}, "Candidate"), close),
      el("p", { class: "form-error" }, message));
    return;
  }

  const since = isFinal(candidate) ? `${duration(candidate.seconds_in_stage)} ago` :
    `for ${duration(candidate.seconds_in_stage)}`;
  const status = el("div", { class: "status" },
    el("strong", {}, candidate.stage_label),
    candidate.rejected_from ? ` (was in ${labelOf(candidate.rejected_from)})` : "",
    el("div", {}, isFinal(candidate) ? `Final outcome, recorded ${since}` : `In this stage ${since}`));

  const next = state.stages[state.stages.findIndex((stage) => stage.key === candidate.stage) + 1];
  const rejectForm = el("form", { class: "reject-form", hidden: true },
    el("input", { name: "reason", maxlength: "500", placeholder: "Reason (optional)", "aria-label": "Reason" }),
    el("div", { class: "actions" },
      el("button", { class: "button danger", type: "submit" }, "Confirm rejection"),
      el("button", { class: "button", type: "button", onclick: () => { rejectForm.hidden = true; } }, "Cancel")));
  rejectForm.addEventListener("submit", (event) => {
    event.preventDefault();
    act(candidate, "reject", { reason: rejectForm.elements.reason.value });
  });

  const actions = isFinal(candidate)
    ? el("p", { class: "final" }, "This is a final outcome and can't be changed.")
    : el("div", { class: "actions" },
        el("button", { class: "button primary", type: "button", onclick: () => act(candidate, "advance") },
          `Move to ${next.label}`),
        el("button", { class: "button danger", type: "button",
          onclick: () => { rejectForm.hidden = false; rejectForm.elements.reason.focus(); } }, "Reject"));

  const timeline = el("ol", { class: "timeline" }, candidate.history.map((event) =>
    el("li", { class: event.type },
      event.summary,
      event.reason ? el("span", { class: "reason" }, `Reason: ${event.reason}`) : null,
      el("time", { datetime: event.at }, dateTime(event.at)))));

  $("panel").replaceChildren(...[
    el("div", { class: "panel-head" },
      el("div", {}, el("h2", {}, candidate.name), el("div", { class: "email" }, candidate.email)),
      close),
    status,
    actions,
    rejectForm,
    message ? el("p", { class: "form-error", role: "alert" }, message) : null,
    ratingCard(candidate),
    jobSection(candidate),
    el("h3", {}, "History"),
    timeline,
    el("p", { class: "audit-note" }, "History is a permanent record. Entries can't be edited or removed."),
    resumeViewer(candidate),
  ].filter(Boolean));
}

/* ---- match rating ---- */

// Hidden when AI isn't configured.
function ratingCard(candidate) {
  const view = candidate.rating;
  if (view.status === "ai_off") return null;
  const pending = view.status === "pending";
  const button = view.can_rerun
    ? el("button", { class: view.rating ? "button" : "button primary", type: "button",
        onclick: (event) => createRating(candidate.id, event.currentTarget) },
        view.rating ? "Re-run rating" : "Create candidate rating")
    : null;
  const progress = pending
    ? el("div", { class: "progress", role: "status" }, el("span", { class: "spinner", "aria-hidden": "true" }),
        "Rating the candidate…")
    : null;

  if (!view.rating) {
    const note = pending || view.status === "not_rated" ? null
      : el("p", { class: view.status === "failed" ? "form-error" : "muted" }, view.message);
    return el("section", { class: "rating" }, el("h3", {}, "Match rating"), note, progress || button);
  }

  const rating = view.rating;
  const rows = Object.keys(CATEGORY_LABELS).map((key) => {
    const category = rating.categories[key];
    const weight = `${Math.round(rating.weights[key] * 100)}%`;
    return el("tr", {},
      el("th", { scope: "row" }, CATEGORY_LABELS[key]),
      el("td", { class: "score" }, category.score == null ? "Not rated" : `${category.score} / 5`,
        category.needs_review ? el("span", { class: "flag" }, "needs review") : null),
      el("td", { class: "muted" }, weight),
      el("td", {}, evidenceFor(key, rating)));
  });

  return el("section", { class: "rating" },
    el("h3", {}, "Match rating"),
    el("div", { class: "overall" },
      el("strong", {}, rating.overall == null ? "Not rated" : `${rating.overall.toFixed(1)} / 10`),
      rating.needs_review ? el("span", { class: "flag" }, "needs review") : null),
    rating.needs_review
      ? el("p", { class: "muted" }, "The scoring model was unsure about at least one category. Check the evidence before relying on the number.")
      : null,
    el("div", { class: "table-scroll" }, el("table", {},
      el("thead", {}, el("tr", {}, ["Category", "Score", "Weight", "Based on"].map((head) => el("th", { scope: "col" }, head)))),
      el("tbody", {}, rows))),
    rating.missing.length
      ? el("p", { class: "muted" }, `Not rated: ${rating.missing.map((key) => CATEGORY_LABELS[key]).join(", ")}. ` +
          "The overall uses the other categories, with their weights rescaled.")
      : null,
    rating.facts.dropped.length
      ? el("p", { class: "muted" }, "Ignored, because the quote given for it was not found in the resume: " +
          `${rating.facts.dropped.map((fact) => fact.label).join(", ")}.`)
      : null,
    el("p", { class: "muted" }, "Overall = 2 × the weighted average of the category scores. ",
      `Rated ${dateTime(view.rated_at)} by ${rating.models.jev} on facts extracted by ${rating.models.deepseek}.`),
    progress || button);
}

function evidenceFor(key, rating) {
  const facts = rating.facts;
  const quotes = (items, label) => items.length
    ? el("details", {}, el("summary", {}, `${items.length} ${label}`),
        el("ul", { class: "evidence" }, items.map((item) => el("li", {}, el("b", {}, item.title || item.name), " ",
          el("q", {}, item.quote)))))
    : el("span", { class: "muted" }, `No ${label} found in the resume`);
  if (key === "skills") return quotes(facts.skills, facts.skills.length === 1 ? "verified skill" : "verified skills");
  if (key === "relevance") return quotes(facts.roles, facts.roles.length === 1 ? "verified role" : "verified roles");
  if (key === "budget") return rating.categories.budget.detail;
  const parts = [];
  if (facts.years_from_role_dates != null) parts.push(`${facts.years_from_role_dates} years from role dates`);
  if (facts.experience) parts.push(`resume states ${facts.experience.years} years`);
  return parts.join("; ") || el("span", { class: "muted" }, "No dated roles or stated years found");
}

// Spinner right away; pollRating redraws when it's done.
async function createRating(id, button) {
  button.replaceWith(el("div", { class: "progress", role: "status" },
    el("span", { class: "spinner", "aria-hidden": "true" }), "Rating the candidate…"));
  try {
    await api(`/api/candidates/${id}/rating`, { method: "POST" });
  } catch { /* the panel reload below shows the current state */ }
  if (state.openId === id) openPanel(id);
}

/* ---- job and resume ---- */

// Job requirements next to the candidate's facts.
function jobSection(candidate) {
  const job = candidate.job;
  if (!job) return null;
  const facts = candidate.rating.rating?.facts;
  const simple = (text) => text.toLowerCase().replace(/[^a-z0-9]/g, "");
  const has = (skill) => facts?.skills.some((found) =>
    simple(found.name) === simple(skill) || simple(found.name).includes(simple(skill)) || simple(skill).includes(simple(found.name)));
  const skills = (names) => el("div", { class: "chips" }, names.map((name) =>
    el("span", { class: has(name) ? "chip found" : "chip" }, has(name) ? `✓ ${name}` : name)));

  const years = [];
  if (facts?.years_from_role_dates != null) years.push(`${facts.years_from_role_dates} years (from role dates)`);
  if (facts?.experience) years.push(`${facts.experience.years} years (stated)`);

  const row = (label, requirement, candidateSide) =>
    el("tr", {}, el("th", { scope: "row" }, label), el("td", {}, requirement), el("td", {}, candidateSide));
  return el("section", {},
    el("h3", {}, `Applied for ${job.id} · ${job.title}`),
    el("div", { class: "table-scroll" }, el("table", {},
      el("thead", {}, el("tr", {}, ["", "Job requires", "Candidate"].map((head) => el("th", { scope: "col" }, head)))),
      el("tbody", {},
        row("Required skills", skills(job.required_skills),
          facts ? `${job.required_skills.filter(has).length} of ${job.required_skills.length} found by name` : "—"),
        row("Nice to have", skills(job.nice_to_have_skills),
          facts ? `${job.nice_to_have_skills.filter(has).length} of ${job.nice_to_have_skills.length} found by name` : "—"),
        row("Experience", `${job.min_experience_years}+ years`, years.join("; ") || "—"),
        row("Budget (CTC p.a.)", `${money(job.budget_min, job.currency)} to ${money(job.budget_max, job.currency)}`,
          candidate.expected_salary ? `Expects ${money(candidate.expected_salary, job.currency)}` : "Not given"),
        row("Location", [job.location, job.work_mode].filter(Boolean).join(" · ") || "—", "—")))));
}

// Page images only; the PDF never reaches the browser.
function resumeViewer(candidate) {
  if (!candidate.resume) return null;
  const pages = Array.from({ length: candidate.resume.pages }, (_, index) =>
    el("img", {
      class: "resume-page", alt: `Resume page ${index + 1}`, draggable: "false", loading: "lazy",
      src: `/api/candidates/${candidate.id}/resume/pages/${index + 1}`,
      oncontextmenu: (event) => event.preventDefault(),
      ondragstart: (event) => event.preventDefault(),
    }));
  return el("section", {},
    el("h3", {}, `Resume (${candidate.resume.pages} ${candidate.resume.pages === 1 ? "page" : "pages"})`),
    candidate.resume.readable ? null : el("p", { class: "muted" }, "No text could be read from this resume, so it can't be rated."),
    el("div", { class: "resume" }, pages));
}

// Sends the stage on screen; the server refuses if it's stale.
async function act(candidate, action, extra = {}) {
  $("panel").querySelectorAll("button").forEach((button) => { button.disabled = true; });
  let message;
  try {
    await api(`/api/candidates/${candidate.id}/${action}`, {
      method: "POST",
      body: { expected_stage: candidate.stage, ...extra },
    });
  } catch (error) {
    message = error.message;
  }
  await refresh();
  if (state.openId === candidate.id) await openPanel(candidate.id, message);
}

async function refresh() {
  await loadBoard().catch(() => {});
  if ($("search").value.trim() || hasFilters()) await runSearch();
}

/* ---- add candidate ---- */

function openAddDialog() {
  $("add-form").reset();
  $("add-error").hidden = true;
  showJobInfo();
  $("add-dialog").showModal();
  $("add-job").focus();
}

// Look up the typed job ID.
async function showJobInfo() {
  const id = $("add-job").value.trim();
  const box = $("add-job-info");
  box.hidden = !id;
  if (!id) return;
  try {
    const job = await api(`/api/jobs/${encodeURIComponent(id)}`);
    if ($("add-job").value.trim() !== id) return;
    box.className = "job-info";
    box.replaceChildren(
      el("strong", {}, `${job.id} · ${job.title}`),
      el("div", {}, `${job.min_experience_years}+ years · ${job.location} · ${job.work_mode}`),
      el("div", {}, `Required: ${job.required_skills.join(", ")}`),
      el("div", {}, `Nice to have: ${job.nice_to_have_skills.join(", ")}`),
      el("div", {}, `Budget: ${money(job.budget_min, job.currency)} to ${money(job.budget_max, job.currency)} per annum`));
  } catch (error) {
    if ($("add-job").value.trim() !== id) return;
    box.className = "job-info form-error";
    box.replaceChildren(error.message);
  }
}

async function submitAdd(event) {
  event.preventDefault();
  $("add-submit").disabled = true;
  try {
    const candidate = await api("/api/candidates", { method: "POST", form: new FormData($("add-form")) });
    $("add-dialog").close();
    await refresh();
    openPanel(candidate.id);
  } catch (error) {
    $("add-error").textContent = error.message;
    $("add-error").hidden = false;
  }
  $("add-submit").disabled = false;
}

async function loadDemo() {
  $("seed-button").disabled = true;
  try {
    await api("/api/demo/seed", { method: "POST" });
  } catch (error) {
    $("audit").textContent = error.message;
  }
  $("seed-button").disabled = false;
  await refresh();
}

/* ---- start ---- */

$("search").addEventListener("input", onSearchInput);
$("search").addEventListener("keydown", (event) => {
  if (event.key === "Enter") { clearTimeout(searchTimer); runAssist(); }
});
$("filter-toggle").addEventListener("click", () => {
  const open = $("filters").hidden;
  if (open) setPanel(state.filters); // drop edits that weren't applied
  $("filters").hidden = !open;
  $("filter-toggle").setAttribute("aria-expanded", String(open));
});
$("filters").addEventListener("submit", applyFilters);
$("f-clear").addEventListener("click", clearFilters);
$("f-reached").addEventListener("change", () => {
  enableWhen();
  if (!$("f-reached").value) $("f-date").value = "";
});
document.addEventListener("click", (event) => closeMultis(event.target.closest?.(".multi")));
$("add-button").addEventListener("click", openAddDialog);
$("add-cancel").addEventListener("click", () => $("add-dialog").close());
$("add-form").addEventListener("submit", submitAdd);
$("add-job").addEventListener("change", showJobInfo);
$("seed-button").addEventListener("click", loadDemo);
$("backdrop").addEventListener("click", closePanel);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !$("panel").hidden) closePanel();
});

async function start() {
  // The board still loads if these fail.
  [state.jobs, state.ai] = await Promise.all([
    api("/api/jobs").catch(() => []),
    api("/api/ai/status").catch(() => state.ai),
  ]);
  if (state.ai.search) {
    $("search").placeholder = "Search by name, or ask a question and press Enter";
  }
  try {
    await loadBoard();
    renderFilters();
  } catch (error) {
    $("board").replaceChildren(el("p", { class: "form-error" }, error.message));
  }
}

start();
