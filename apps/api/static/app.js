"use strict";

const RANKING_LIMIT = 20;
const SVG_NAMESPACE = "http://www.w3.org/2000/svg";
const RANKING_MODES = Object.freeze({
  largest: {
    label: "Largest",
    metricHeading: "Total posts",
    contextHeading: "Measured",
    description: "Newest valid total posts",
  },
  fastest_growth: {
    label: "Fastest Growth",
    metricHeading: "Growth",
    contextHeading: "Measurement window",
    description: "Posts per day from the newest compatible pair",
  },
  relative_growth: {
    label: "Relative Growth",
    metricHeading: "Relative growth",
    contextHeading: "Measurement window",
    description: "24-hour rate relative to the previous total",
  },
});

const INELIGIBILITY_PRESENTATION = Object.freeze({
  missing_total_posts: {
    title: "Metric unavailable",
    detail: "The latest accepted observation does not include a valid total-post count.",
  },
  invalid_total_posts: {
    title: "Metric unavailable",
    detail: "The latest total-post measurement cannot be ranked safely.",
  },
  insufficient_history: {
    title: "Building history",
    detail: "More accepted observations are required for this ranking.",
  },
  incompatible_provenance: {
    title: "History not comparable",
    detail: "The newest observations use different evidence classes.",
  },
  incompatible_unit: {
    title: "History not comparable",
    detail: "The newest observations do not share the required posts unit.",
  },
  invalid_time_interval: {
    title: "Measurement window unavailable",
    detail: "The newest observations do not form a positive time interval.",
  },
  zero_baseline: {
    title: "Relative growth unavailable",
    detail: "A zero previous total cannot provide a relative-growth baseline.",
  },
});

const GROWTH_UNAVAILABLE_LABELS = Object.freeze({
  insufficient_history: "Building history",
  incompatible_snapshots: "History not comparable",
  invalid_interval: "Measurement window unavailable",
});

const PROVENANCE_HELP = Object.freeze({
  observed: "Observed: reported directly by a supported public source.",
  estimated: "Estimated: derived transparently from available public evidence.",
  owner_verified: "Owner verified: verified by the source owner.",
});

const integerFormatter = new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 });
const compactFormatter = new Intl.NumberFormat(undefined, {
  notation: "compact",
  maximumSignificantDigits: 3,
});
const rateFormatter = new Intl.NumberFormat(undefined, {
  notation: "compact",
  maximumSignificantDigits: 3,
});
const percentFormatter = new Intl.NumberFormat(undefined, { maximumSignificantDigits: 3 });
const dateFormatter = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });
const dateOnlyFormatter = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });
const relativeFormatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

const elements = {
  navToggle: document.querySelector("#nav-toggle"),
  primaryNav: document.querySelector("#primary-nav"),
  heroStatus: document.querySelector(".hero-status"),
  heroSourceCount: document.querySelector("#hero-source-count"),
  heroLatestState: document.querySelector("#hero-latest-state"),
  rankingConnectionLabel: document.querySelector("#ranking-connection-label"),
  ecosystemMetrics: document.querySelector("#ecosystem-metrics"),
  snapshotLargestName: document.querySelector("#snapshot-largest-name"),
  snapshotLargestValue: document.querySelector("#snapshot-largest-value"),
  snapshotGrowthValue: document.querySelector("#snapshot-growth-value"),
  snapshotGrowthNote: document.querySelector("#snapshot-growth-note"),
  snapshotTracked: document.querySelector("#snapshot-tracked"),
  snapshotEligible: document.querySelector("#snapshot-eligible"),
  snapshotEligibleNote: document.querySelector("#snapshot-eligible-note"),
  rankingTabs: Array.from(document.querySelectorAll("[data-ranking-mode]")),
  rankingPanel: document.querySelector("#ranking-panel"),
  rankingSummary: document.querySelector("#ranking-summary"),
  rankingModeDescription: document.querySelector("#ranking-mode-description"),
  rankingMetricHeading: document.querySelector("#ranking-metric-heading"),
  rankingContextHeading: document.querySelector("#ranking-context-heading"),
  rankingFreshness: document.querySelector("#ranking-freshness"),
  rankingLoading: document.querySelector("#ranking-loading"),
  rankingError: document.querySelector("#ranking-error"),
  rankingErrorMessage: document.querySelector("#ranking-error-message"),
  rankingRetry: document.querySelector("#ranking-retry"),
  rankingEmpty: document.querySelector("#ranking-empty"),
  rankingResults: document.querySelector("#ranking-results"),
  rankingCaption: document.querySelector("#ranking-caption"),
  rankingBody: document.querySelector("#ranking-body"),
  rankingPagination: document.querySelector("#ranking-pagination"),
  rankingPageStatus: document.querySelector("#ranking-page-status"),
  rankingPrevious: document.querySelector("#ranking-previous"),
  rankingNext: document.querySelector("#ranking-next"),
  compareSelection: document.querySelector("#compare-selection"),
  compareButton: document.querySelector("#compare-button"),
  comparePanel: document.querySelector("#compare-panel"),
  compareClose: document.querySelector("#compare-close"),
  compareLoading: document.querySelector("#compare-loading"),
  compareError: document.querySelector("#compare-error"),
  compareErrorMessage: document.querySelector("#compare-error-message"),
  compareResults: document.querySelector("#compare-results"),
  compareBody: document.querySelector("#compare-body"),
  detailPanel: document.querySelector("#detail-panel"),
  detailClose: document.querySelector("#detail-close"),
  detailTitle: document.querySelector("#detail-title"),
  detailFamily: document.querySelector("#detail-family"),
  detailLink: document.querySelector("#detail-link"),
  detailLoading: document.querySelector("#detail-loading"),
  detailError: document.querySelector("#detail-error"),
  detailErrorMessage: document.querySelector("#detail-error-message"),
  detailContent: document.querySelector("#detail-content"),
  detailTotal: document.querySelector("#detail-total"),
  detailTotalNote: document.querySelector("#detail-total-note"),
  detailPace: document.querySelector("#detail-pace"),
  detailPaceNote: document.querySelector("#detail-pace-note"),
  detailDelta: document.querySelector("#detail-delta"),
  detailDeltaNote: document.querySelector("#detail-delta-note"),
  historyCount: document.querySelector("#history-count"),
  historyEmpty: document.querySelector("#history-empty"),
  historyResults: document.querySelector("#history-results"),
  historyCaption: document.querySelector("#history-caption"),
  historyBody: document.querySelector("#history-body"),
  historyChart: document.querySelector("#history-chart"),
  historyStatusTitle: document.querySelector("#history-status-title"),
  historyStatusCopy: document.querySelector("#history-status-copy"),
  activityExplore: document.querySelector("#activity-explore"),
};

const state = {
  rankingMode: "largest",
  rankingOffset: 0,
  rankingPayload: null,
  rankingController: null,
  summaryController: null,
  summaryLargest: null,
  summaryGrowth: null,
  comparisonIds: new Set(),
  compareController: null,
  detailController: null,
  detailReturnFocus: null,
};

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function createElement(tagName, className, text) {
  const node = document.createElement(tagName);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function createSvgElement(tagName, attributes = {}) {
  const node = document.createElementNS(SVG_NAMESPACE, tagName);
  Object.entries(attributes).forEach(([name, value]) => node.setAttribute(name, String(value)));
  return node;
}

async function fetchJson(path, signal) {
  const response = await fetch(path, {
    method: "GET",
    headers: { Accept: "application/json" },
    credentials: "same-origin",
    signal,
  });
  if (!response.ok) {
    let message = `The public API returned ${response.status}.`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string" && body.detail.trim()) message = body.detail;
    } catch {
      // A bounded status remains useful when no structured detail is available.
    }
    throw new ApiError(message, response.status);
  }
  return response.json();
}

function normalizedNumber(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function formatNumber(value) {
  const number = normalizedNumber(value);
  return number === null ? "—" : integerFormatter.format(number);
}

function formatCompactNumber(value) {
  const number = normalizedNumber(value);
  return number === null ? "—" : compactFormatter.format(number);
}

function formatSigned(value, formatter = integerFormatter) {
  const number = normalizedNumber(value);
  return number === null ? "—" : `${number > 0 ? "+" : ""}${formatter.format(number)}`;
}

function validDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatDate(value) {
  const date = validDate(value);
  return date === null ? "Unknown time" : dateFormatter.format(date);
}

function formatDateOnly(value) {
  const date = validDate(value);
  return date === null ? "Unknown date" : dateOnlyFormatter.format(date);
}

function relativeDate(value) {
  const date = validDate(value);
  if (date === null) return "Unknown time";
  const seconds = Math.round((date.getTime() - Date.now()) / 1000);
  const intervals = [["year", 31_536_000], ["month", 2_592_000], ["day", 86_400], ["hour", 3_600], ["minute", 60]];
  for (const [unit, duration] of intervals) {
    if (Math.abs(seconds) >= duration || unit === "minute") {
      return relativeFormatter.format(Math.round(seconds / duration), unit);
    }
  }
  return "just now";
}

function labelFromIdentifier(value, fallback = "Not reported") {
  if (typeof value !== "string" || !value.trim()) return fallback;
  return value.split("_").map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(" ");
}

function provenanceLabel(value) {
  return labelFromIdentifier(value);
}

function provenanceClass(value) {
  const classes = {
    observed: "provenance-observed",
    estimated: "provenance-estimated",
    owner_verified: "provenance-owner-verified",
  };
  return classes[value] || "";
}

function createProvenanceBadge(value, { linked = true } = {}) {
  const badge = createElement(linked ? "a" : "span", `provenance-badge ${provenanceClass(value)}`.trim(), provenanceLabel(value));
  const help = PROVENANCE_HELP[value] || "Metric evidence class reported by the API.";
  badge.title = help;
  badge.setAttribute("aria-label", help);
  if (linked) badge.href = "#methodology";
  return badge;
}

function safePublicUrl(value) {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
}

function publicDomain(value) {
  const safeUrl = safePublicUrl(value);
  return safeUrl === null ? "Public source" : new URL(safeUrl).hostname.replace(/^www\./, "");
}

function sourceInitial(name) {
  return typeof name === "string" && name.trim() ? name.trim().charAt(0) : "?";
}

function numberTone(value) {
  const number = normalizedNumber(value);
  if (number === null || number === 0) return "number-neutral";
  return number > 0 ? "number-positive" : "number-negative";
}

function rankingMetric(item) {
  if (item.unit === "posts") {
    return { primary: formatCompactNumber(item.value), unit: "posts", exact: `${formatNumber(item.value)} posts` };
  }
  if (item.unit === "posts/day") {
    return { primary: formatSigned(item.value, rateFormatter), unit: "posts / day", exact: `${formatSigned(item.value)} posts per day` };
  }
  return { primary: `${formatSigned(item.value, percentFormatter)}%`, unit: "per day", exact: `${formatSigned(item.value, percentFormatter)} percent per day` };
}

function ineligibilityPresentation(reason) {
  return INELIGIBILITY_PRESENTATION[reason] || {
    title: "Ranking unavailable",
    detail: "This source is not currently eligible for the selected ranking.",
  };
}

function growthUnavailableLabel(reason) {
  return GROWTH_UNAVAILABLE_LABELS[reason] || "Growth unavailable";
}

function setNavigationOpen(open) {
  elements.navToggle.setAttribute("aria-expanded", String(open));
  elements.navToggle.setAttribute("aria-label", open ? "Close navigation" : "Open navigation");
  elements.primaryNav.classList.toggle("is-open", open);
}

function setConnectionState(kind, label) {
  elements.heroStatus.dataset.state = kind;
  elements.rankingConnectionLabel.textContent = label;
  elements.rankingFreshness.textContent = label;
}

function validateRankingPayload(payload, expectedMode) {
  if (!payload || payload.mode !== expectedMode || !Array.isArray(payload.items)
      || !Number.isInteger(payload.total) || !Number.isInteger(payload.eligible_count)
      || !Number.isInteger(payload.limit) || !Number.isInteger(payload.offset)) {
    throw new ApiError("The ranking response was not recognized.", 500);
  }
  payload.items.forEach((item) => {
    if (!item || typeof item.eligible !== "boolean" || typeof item.booru_id !== "string"
        || typeof item.name !== "string" || typeof item.canonical_url !== "string") {
      throw new ApiError("A ranking row was not recognized.", 500);
    }
    if (item.eligible) {
      if (!Number.isInteger(item.rank) || item.rank < 1 || normalizedNumber(item.value) === null
          || item.unit !== payload.unit || !PROVENANCE_HELP[item.provenance]) {
        throw new ApiError("An eligible ranking row was not recognized.", 500);
      }
    } else {
      const forbiddenFields = ["value", "unit", "provenance", "latest_captured_at", "previous_captured_at", "elapsed_hours", "posts_delta"];
      if (item.rank !== null || typeof item.reason !== "string"
          || forbiddenFields.some((field) => Object.hasOwn(item, field))) {
        throw new ApiError("An ineligible ranking row was not recognized.", 500);
      }
    }
  });
  return payload;
}

async function fetchRanking(mode, offset, signal) {
  const query = new URLSearchParams({ mode, limit: String(RANKING_LIMIT), offset: String(offset) });
  const payload = await fetchJson(`/api/v1/rankings?${query.toString()}`, signal);
  return validateRankingPayload(payload, mode);
}

function setActiveRankingMode(mode) {
  const definition = RANKING_MODES[mode];
  elements.rankingTabs.forEach((tab) => {
    const selected = tab.dataset.rankingMode === mode;
    tab.classList.toggle("is-active", selected);
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
    if (selected) elements.rankingPanel.setAttribute("aria-labelledby", tab.id);
  });
  elements.rankingModeDescription.textContent = definition.description;
  elements.rankingMetricHeading.textContent = definition.metricHeading;
  elements.rankingContextHeading.textContent = definition.contextHeading;
}

function setRankingView(mode, message = "") {
  elements.rankingLoading.hidden = mode !== "loading";
  elements.rankingError.hidden = mode !== "error";
  elements.rankingEmpty.hidden = mode !== "empty";
  elements.rankingResults.hidden = mode !== "ready";
  elements.rankingPagination.hidden = mode !== "ready" || Boolean(state.rankingPayload && state.rankingPayload.total <= state.rankingPayload.limit);
  elements.rankingPanel.setAttribute("aria-busy", String(mode === "loading"));
  if (mode === "loading") {
    elements.rankingBody.replaceChildren();
    elements.rankingSummary.textContent = "Loading rankings";
  }
  if (message) elements.rankingErrorMessage.textContent = message;
}

function createRankingEntity(item) {
  const wrapper = createElement("div", "ranking-entity");
  wrapper.append(createElement("span", "source-avatar", sourceInitial(item.name)));
  const text = createElement("div");
  const button = createElement("button", "entity-button", item.name);
  button.type = "button";
  button.addEventListener("click", () => openDetail(item.booru_id, button));
  text.append(button, createElement("span", "source-domain", publicDomain(item.canonical_url)));
  wrapper.append(text);
  return wrapper;
}

function createRankingMetricCell(item) {
  const cell = createElement("td", "ranking-metric-cell");
  cell.dataset.label = "Metric";
  if (!item.eligible) {
    const presentation = ineligibilityPresentation(item.reason);
    const unavailable = createElement("div", "ineligibility-state");
    unavailable.append(createElement("strong", null, presentation.title), createElement("span", null, presentation.detail));
    unavailable.title = `${presentation.detail} Reason: ${item.reason}.`;
    cell.append(unavailable);
    return cell;
  }
  const metric = rankingMetric(item);
  const wrapper = createElement("div", `ranking-metric ${numberTone(item.value)}`);
  const value = createElement("strong", null, metric.primary);
  value.title = metric.exact;
  wrapper.append(value, createElement("span", null, metric.unit));
  cell.append(wrapper);
  return cell;
}

function createRankingContext(item) {
  const wrapper = createElement("div", "ranking-measurement");
  if (!item.eligible) {
    wrapper.append(createElement("strong", null, "Not ranked"), createElement("span", null, "No numeric substitute"));
    return wrapper;
  }
  if (item.unit === "posts") {
    const relative = createElement("strong", null, relativeDate(item.latest_captured_at));
    relative.title = formatDate(item.latest_captured_at);
    wrapper.append(relative, createElement("span", null, formatDate(item.latest_captured_at)));
    return wrapper;
  }
  const hours = normalizedNumber(item.elapsed_hours);
  const windowLabel = hours === null ? "Window unavailable" : `${hours.toFixed(1)}h window`;
  const delta = createElement("span", numberTone(item.posts_delta), `${formatSigned(item.posts_delta)} posts · ${relativeDate(item.latest_captured_at)}`);
  wrapper.append(createElement("strong", null, windowLabel), delta);
  wrapper.title = hours === null ? "Measurement interval unavailable" : `${formatDate(item.previous_captured_at)} to ${formatDate(item.latest_captured_at)}`;
  return wrapper;
}

function createCompareControl(item) {
  const label = createElement("label", "compare-check");
  const checkbox = createElement("input");
  checkbox.type = "checkbox";
  checkbox.value = item.booru_id;
  checkbox.dataset.compareId = item.booru_id;
  checkbox.checked = state.comparisonIds.has(item.booru_id);
  checkbox.setAttribute("aria-label", `Select ${item.name} for comparison`);
  checkbox.addEventListener("change", () => {
    if (checkbox.checked) {
      if (state.comparisonIds.size >= 8) {
        checkbox.checked = false;
        return;
      }
      state.comparisonIds.add(item.booru_id);
    } else {
      state.comparisonIds.delete(item.booru_id);
    }
    updateComparisonSelection();
  });
  label.append(checkbox, createElement("span", null, "Compare"));
  return label;
}

function createRankingRow(item) {
  const row = createElement("tr", item.eligible ? "ranking-row" : "ranking-row is-ineligible");
  const rankCell = createElement("td", "ranking-rank-cell");
  rankCell.dataset.label = "Rank";
  const rank = createElement("span", item.eligible ? "rank-number" : "rank-number rank-unavailable", item.eligible ? `#${item.rank}` : "—");
  rank.setAttribute("aria-label", item.eligible ? `Global rank ${item.rank}` : "Not eligible for a global rank");
  rankCell.append(rank);

  const entityCell = createElement("td", "ranking-entity-cell");
  entityCell.dataset.label = "Booru";
  entityCell.append(createRankingEntity(item));

  const evidenceCell = createElement("td", "ranking-evidence-cell");
  evidenceCell.dataset.label = "Provenance";
  if (item.eligible) {
    evidenceCell.append(createProvenanceBadge(item.provenance));
  } else {
    const unavailable = createElement("span", "evidence-unavailable", "Unavailable");
    unavailable.title = "The ranking contract does not provide provenance for ineligible rows.";
    evidenceCell.append(unavailable);
  }

  const contextCell = createElement("td", "ranking-context-cell");
  contextCell.dataset.label = RANKING_MODES[state.rankingMode].contextHeading;
  contextCell.append(createRankingContext(item));

  const actionCell = createElement("td", "ranking-action-cell");
  actionCell.append(createCompareControl(item));
  const viewButton = createElement("button", "row-action", "View");
  viewButton.type = "button";
  viewButton.setAttribute("aria-label", `View ${item.name} history and growth`);
  viewButton.addEventListener("click", () => openDetail(item.booru_id, viewButton));
  actionCell.append(viewButton);

  row.append(rankCell, entityCell, createRankingMetricCell(item), evidenceCell, contextCell, actionCell);
  return row;
}

function renderRanking(payload) {
  // API order and rank are canonical. Never sort or synthesize page-relative ranks here.
  const rows = payload.items.map(createRankingRow);
  elements.rankingBody.replaceChildren(...rows);
  elements.rankingSummary.textContent = `${formatNumber(payload.eligible_count)} of ${formatNumber(payload.total)} sources eligible`;
  elements.rankingCaption.textContent = `${RANKING_MODES[payload.mode].label} ranking: ${payload.eligible_count} of ${payload.total} sources eligible`;
  const first = payload.items.length ? payload.offset + 1 : 0;
  const last = payload.offset + payload.items.length;
  elements.rankingPageStatus.textContent = payload.items.length ? `Showing ${formatNumber(first)}–${formatNumber(last)} of ${formatNumber(payload.total)} sources` : "No sources on this page";
  elements.rankingPrevious.disabled = payload.offset === 0;
  elements.rankingNext.disabled = payload.offset + payload.items.length >= payload.total;
  updateComparisonSelection();
  setRankingView(payload.items.length ? "ready" : "empty");
}

function updateEcosystemSnapshot() {
  const largest = state.summaryLargest;
  const growth = state.summaryGrowth;
  const countSource = largest || growth;
  const largestItem = largest?.items.find((item) => item.eligible) || null;
  const growthItem = growth?.items.find((item) => item.eligible) || null;
  elements.snapshotTracked.textContent = countSource ? formatNumber(countSource.total) : "—";
  elements.heroSourceCount.textContent = countSource ? `${formatNumber(countSource.total)} tracked ${countSource.total === 1 ? "source" : "sources"}` : "Ranking data unavailable";

  if (largestItem) {
    elements.snapshotLargestName.textContent = largestItem.name;
    elements.snapshotLargestValue.textContent = `${formatCompactNumber(largestItem.value)} posts · ${provenanceLabel(largestItem.provenance)}`;
  } else {
    elements.snapshotLargestName.textContent = "—";
    elements.snapshotLargestValue.textContent = largest ? "No eligible source" : "Ranking unavailable";
  }
  if (growthItem) {
    elements.snapshotGrowthValue.textContent = `${formatSigned(growthItem.value, rateFormatter)} / day`;
    elements.snapshotGrowthNote.textContent = `${growthItem.name} · ${provenanceLabel(growthItem.provenance)}`;
  } else {
    elements.snapshotGrowthValue.textContent = "—";
    elements.snapshotGrowthNote.textContent = growth ? "Building compatible history" : "Growth ranking unavailable";
  }
  if (growth) {
    elements.snapshotEligible.textContent = `${formatNumber(growth.eligible_count)} / ${formatNumber(growth.total)}`;
    elements.snapshotEligibleNote.textContent = growth.eligible_count === 1 ? "Source with a compatible latest pair" : "Sources with compatible latest pairs";
  } else {
    elements.snapshotEligible.textContent = "—";
    elements.snapshotEligibleNote.textContent = "Coverage unavailable";
  }
  if (largest) {
    elements.historyStatusTitle.textContent = "Building trustworthy history";
    elements.historyStatusCopy.textContent = `${largest.eligible_count} of ${largest.total} tracked sources currently have a rankable latest total. Ecosystem-wide history will appear only when it can be represented without fabrication.`;
  } else {
    elements.historyStatusTitle.textContent = "History view unavailable";
    elements.historyStatusCopy.textContent = "The static methodology remains available while the ranking connection recovers.";
  }
  elements.heroLatestState.textContent = countSource ? "Ranking API connected" : "Static methodology available";
  elements.ecosystemMetrics.setAttribute("aria-busy", "false");
}

async function loadRanking() {
  state.rankingController?.abort();
  const controller = new AbortController();
  state.rankingController = controller;
  const mode = state.rankingMode;
  const offset = state.rankingOffset;
  state.rankingPayload = null;
  setActiveRankingMode(mode);
  setRankingView("loading");
  setConnectionState("connecting", "Updating live ranking");
  try {
    const payload = await fetchRanking(mode, offset, controller.signal);
    if (controller !== state.rankingController) return;
    state.rankingPayload = payload;
    if (mode === "largest" && offset === 0) state.summaryLargest = payload;
    if (mode === "fastest_growth" && offset === 0) state.summaryGrowth = payload;
    renderRanking(payload);
    updateEcosystemSnapshot();
    setConnectionState("online", "Live API data");
  } catch (error) {
    if (error.name === "AbortError") return;
    const message = error instanceof Error ? error.message : "The ranking could not be loaded.";
    setRankingView("error", message);
    elements.rankingSummary.textContent = "Ranking unavailable";
    setConnectionState("error", "Ranking API unavailable");
  }
}

async function loadGrowthSummary() {
  state.summaryController?.abort();
  const controller = new AbortController();
  state.summaryController = controller;
  try {
    state.summaryGrowth = await fetchRanking("fastest_growth", 0, controller.signal);
  } catch (error) {
    if (error.name === "AbortError") return;
    state.summaryGrowth = null;
  }
  if (controller === state.summaryController) updateEcosystemSnapshot();
}

function selectRankingMode(mode) {
  if (!RANKING_MODES[mode] || mode === state.rankingMode) return;
  state.rankingMode = mode;
  state.rankingOffset = 0;
  loadRanking();
}

function updateComparisonSelection() {
  const count = state.comparisonIds.size;
  elements.compareSelection.textContent = count ? `${count} ${count === 1 ? "source" : "sources"} selected` : "Choose 2–8 sources from the ranking.";
  elements.compareButton.disabled = count < 2 || count > 8;
  document.querySelectorAll("[data-compare-id]").forEach((checkbox) => {
    const selected = state.comparisonIds.has(checkbox.dataset.compareId);
    checkbox.checked = selected;
    checkbox.disabled = !selected && count >= 8;
  });
}

function setCompareView(mode, message = "") {
  elements.comparePanel.hidden = false;
  elements.compareLoading.hidden = mode !== "loading";
  elements.compareError.hidden = mode !== "error";
  elements.compareResults.hidden = mode !== "ready";
  elements.comparePanel.setAttribute("aria-busy", String(mode === "loading"));
  if (message) elements.compareErrorMessage.textContent = message;
}

function appendPrimaryCell(row, primary, secondary, label) {
  const cell = createElement("td");
  cell.dataset.label = label;
  const wrapper = createElement("div", "table-primary");
  wrapper.append(createElement("strong", null, primary));
  if (secondary) wrapper.append(createElement("span", null, secondary));
  cell.append(wrapper);
  row.append(cell);
}

function appendTextCell(row, text, label, className = "") {
  const cell = createElement("td", className, text);
  cell.dataset.label = label;
  row.append(cell);
}

function renderComparison(items) {
  const rows = items.map((item) => {
    const row = createElement("tr");
    const booru = item.booru;
    const growth = item.growth;
    const snapshot = booru.latest_snapshot;
    appendPrimaryCell(row, booru.name, publicDomain(booru.canonical_url), "Source");
    appendTextCell(row, formatNumber(snapshot?.total_posts?.value), "Total posts");
    const evidenceCell = createElement("td");
    evidenceCell.dataset.label = "Evidence";
    evidenceCell.append(snapshot?.total_posts ? createProvenanceBadge(snapshot.total_posts.provenance) : createElement("span", "evidence-unavailable", "Unavailable"));
    row.append(evidenceCell);
    if (growth.status === "available") {
      appendTextCell(row, `${formatSigned(growth.posts_per_day, rateFormatter)} / day`, "Daily pace", numberTone(growth.posts_per_day));
      appendTextCell(row, formatSigned(growth.posts_delta), "Net change", numberTone(growth.posts_delta));
    } else {
      appendTextCell(row, growthUnavailableLabel(growth.reason), "Daily pace", "table-muted");
      appendTextCell(row, "—", "Net change", "table-muted");
    }
    appendTextCell(row, snapshot ? formatDate(snapshot.captured_at) : "No snapshot", "Latest capture", "table-muted");
    return row;
  });
  elements.compareBody.replaceChildren(...rows);
}

async function runComparison() {
  if (state.comparisonIds.size < 2 || state.comparisonIds.size > 8) return;
  state.compareController?.abort();
  const controller = new AbortController();
  state.compareController = controller;
  setCompareView("loading");
  elements.comparePanel.scrollIntoView({ behavior: "smooth", block: "start" });
  const query = new URLSearchParams();
  state.comparisonIds.forEach((id) => query.append("booru_id", id));
  try {
    const payload = await fetchJson(`/api/v1/compare?${query.toString()}`, controller.signal);
    if (controller !== state.compareController) return;
    if (!Array.isArray(payload.items)) throw new ApiError("The comparison response was not recognized.", 500);
    renderComparison(payload.items);
    setCompareView("ready");
    elements.compareClose.focus({ preventScroll: true });
  } catch (error) {
    if (error.name === "AbortError") return;
    setCompareView("error", error instanceof Error ? error.message : "The comparison could not be loaded.");
  }
}

function closeComparison() {
  state.compareController?.abort();
  elements.comparePanel.hidden = true;
  elements.compareButton.focus({ preventScroll: true });
}

function setDetailView(mode, message = "") {
  elements.detailLoading.hidden = mode !== "loading";
  elements.detailError.hidden = mode !== "error";
  elements.detailContent.hidden = mode !== "ready";
  elements.detailPanel.setAttribute("aria-busy", String(mode === "loading"));
  if (message) elements.detailErrorMessage.textContent = message;
}

function configureDetailLink(value) {
  const safeUrl = safePublicUrl(value);
  elements.detailLink.hidden = safeUrl === null;
  if (safeUrl) elements.detailLink.href = safeUrl;
  else elements.detailLink.removeAttribute("href");
}

function renderGrowth(growth) {
  if (growth.status !== "available") {
    elements.detailPace.textContent = "—";
    elements.detailPace.className = "number-neutral";
    elements.detailPaceNote.textContent = growthUnavailableLabel(growth.reason);
    elements.detailDelta.textContent = "—";
    elements.detailDelta.className = "number-neutral";
    elements.detailDeltaNote.textContent = "No numeric substitute for unavailable growth";
    return;
  }
  elements.detailPace.textContent = `${formatSigned(growth.posts_per_day, rateFormatter)} / day`;
  elements.detailPace.className = numberTone(growth.posts_per_day);
  elements.detailPaceNote.textContent = `${provenanceLabel(growth.provenance)} · ${growth.elapsed_hours.toFixed(1)}h window`;
  elements.detailDelta.textContent = formatSigned(growth.posts_delta);
  elements.detailDelta.className = numberTone(growth.posts_delta);
  elements.detailDeltaNote.textContent = "Between the newest compatible snapshots";
}

function renderHistoryChart(snapshots) {
  const observations = snapshots.map((snapshot) => ({
    snapshot,
    capturedAt: validDate(snapshot.captured_at),
    value: normalizedNumber(snapshot.total_posts?.value),
  })).filter((item) => item.capturedAt !== null && item.value !== null)
    .sort((left, right) => left.capturedAt.getTime() - right.capturedAt.getTime());
  elements.historyChart.replaceChildren();
  if (observations.length < 2) {
    const building = createElement("div", "history-building");
    const radar = createElement("span", "history-radar");
    radar.setAttribute("aria-hidden", "true");
    building.append(radar, createElement("strong", null, "Building history"), createElement("p", null, observations.length ? "One accepted observation is available. A trend requires compatible history." : "More trend data will appear as accepted observations accumulate."));
    elements.historyChart.append(building);
    elements.historyChart.setAttribute("aria-label", "Building snapshot history");
    return;
  }

  const width = 720;
  const height = 300;
  const padding = { top: 30, right: 36, bottom: 44, left: 52 };
  const times = observations.map((item) => item.capturedAt.getTime());
  const values = observations.map((item) => item.value);
  const minTime = Math.min(...times);
  const maxTime = Math.max(...times);
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const timeRange = Math.max(maxTime - minTime, 1);
  const valueRange = Math.max(maxValue - minValue, 1);
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const points = observations.map((item) => ({
    ...item,
    x: padding.left + ((item.capturedAt.getTime() - minTime) / timeRange) * plotWidth,
    y: padding.top + (1 - (item.value - minValue) / valueRange) * plotHeight,
  }));
  const svg = createSvgElement("svg", {
    class: "history-svg",
    viewBox: `0 0 ${width} ${height}`,
    role: "img",
    "aria-label": `${observations.length} accepted observations from ${formatDateOnly(observations[0].snapshot.captured_at)} to ${formatDateOnly(observations.at(-1).snapshot.captured_at)}`,
  });
  [padding.top, padding.top + plotHeight / 2, padding.top + plotHeight].forEach((y) => {
    svg.append(createSvgElement("line", { class: "chart-guide", x1: padding.left, y1: y, x2: width - padding.right, y2: y }));
  });
  const areaPath = [`M ${points[0].x} ${padding.top + plotHeight}`, ...points.map((point) => `L ${point.x} ${point.y}`), `L ${points.at(-1).x} ${padding.top + plotHeight}`, "Z"].join(" ");
  svg.append(createSvgElement("path", { class: "chart-area", d: areaPath }));
  svg.append(createSvgElement("polyline", { class: "chart-line", points: points.map((point) => `${point.x},${point.y}`).join(" ") }));
  points.forEach((point) => {
    const circle = createSvgElement("circle", { class: "chart-point", cx: point.x, cy: point.y, r: 5 });
    const title = createSvgElement("title");
    title.textContent = `${formatDate(point.snapshot.captured_at)}: ${formatNumber(point.value)} posts, ${provenanceLabel(point.snapshot.total_posts.provenance)}`;
    circle.append(title);
    svg.append(circle);
  });
  const labels = [
    [padding.left, height - 14, "start", formatDateOnly(observations[0].snapshot.captured_at)],
    [width - padding.right, height - 14, "end", formatDateOnly(observations.at(-1).snapshot.captured_at)],
    [padding.left, padding.top - 10, "start", `${formatCompactNumber(maxValue)} posts`],
  ];
  labels.forEach(([x, y, anchor, text]) => {
    const label = createSvgElement("text", { class: "chart-label", x, y, "text-anchor": anchor });
    label.textContent = text;
    svg.append(label);
  });
  elements.historyChart.append(svg);
  elements.historyChart.setAttribute("aria-label", `${observations.length} exact accepted snapshot observations`);
}

function renderHistory(booru, snapshots) {
  elements.historyCount.textContent = `${snapshots.length} ${snapshots.length === 1 ? "observation" : "observations"}`;
  elements.historyCaption.textContent = `${booru.name} accepted observations, newest first`;
  elements.historyEmpty.hidden = snapshots.length !== 0;
  elements.historyResults.hidden = snapshots.length === 0;
  renderHistoryChart(snapshots);
  const rows = snapshots.map((snapshot) => {
    const row = createElement("tr");
    appendPrimaryCell(row, formatDate(snapshot.captured_at), relativeDate(snapshot.captured_at), "Captured");
    appendTextCell(row, formatNumber(snapshot.total_posts?.value), "Total posts");
    const evidenceCell = createElement("td");
    evidenceCell.dataset.label = "Evidence";
    evidenceCell.append(snapshot.total_posts ? createProvenanceBadge(snapshot.total_posts.provenance) : createElement("span", "evidence-unavailable", "Unavailable"));
    row.append(evidenceCell);
    return row;
  });
  elements.historyBody.replaceChildren(...rows);
}

async function openDetail(booruId, returnFocus = null) {
  state.detailController?.abort();
  const controller = new AbortController();
  state.detailController = controller;
  state.detailReturnFocus = returnFocus;
  elements.detailPanel.hidden = false;
  elements.detailTitle.textContent = "Loading source";
  elements.detailFamily.textContent = "Reading accepted public data";
  setDetailView("loading");
  elements.detailPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  const encodedId = encodeURIComponent(booruId);
  try {
    const [booru, snapshots, growth] = await Promise.all([
      fetchJson(`/api/v1/boorus/${encodedId}`, controller.signal),
      fetchJson(`/api/v1/boorus/${encodedId}/snapshots?limit=30`, controller.signal),
      fetchJson(`/api/v1/boorus/${encodedId}/growth`, controller.signal),
    ]);
    if (controller !== state.detailController) return;
    if (!Array.isArray(snapshots.items)) throw new ApiError("The history response was not recognized.", 500);
    elements.detailTitle.textContent = booru.name;
    const adapterName = booru.adapter_name ? `${labelFromIdentifier(booru.adapter_name)} · ` : "";
    elements.detailFamily.textContent = `${adapterName}${labelFromIdentifier(booru.adapter_family)} adapter family`;
    configureDetailLink(booru.canonical_url);
    const latest = booru.latest_snapshot;
    elements.detailTotal.textContent = formatNumber(latest?.total_posts?.value);
    elements.detailTotalNote.textContent = latest?.total_posts ? `${provenanceLabel(latest.total_posts.provenance)} · ${formatDate(latest.captured_at)}` : "No accepted count";
    renderGrowth(growth);
    renderHistory(booru, snapshots.items);
    setDetailView("ready");
    elements.detailClose.focus({ preventScroll: true });
  } catch (error) {
    if (error.name === "AbortError") return;
    setDetailView("error", error instanceof Error ? error.message : "The detail view could not be loaded.");
  }
}

function closeDetail() {
  state.detailController?.abort();
  elements.detailPanel.hidden = true;
  if (state.detailReturnFocus?.isConnected) state.detailReturnFocus.focus({ preventScroll: true });
  document.querySelector("#rankings-title")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

elements.navToggle.addEventListener("click", () => setNavigationOpen(elements.navToggle.getAttribute("aria-expanded") !== "true"));
elements.primaryNav.addEventListener("click", (event) => {
  if (event.target.closest("a")) setNavigationOpen(false);
});
elements.rankingTabs.forEach((tab, index) => {
  tab.addEventListener("click", () => selectRankingMode(tab.dataset.rankingMode));
  tab.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const direction = event.key === "ArrowRight" ? 1 : -1;
    const target = elements.rankingTabs.at((index + direction + elements.rankingTabs.length) % elements.rankingTabs.length);
    target.focus();
    target.click();
  });
});
elements.rankingRetry.addEventListener("click", loadRanking);
elements.rankingPrevious.addEventListener("click", () => {
  if (!state.rankingPayload || state.rankingOffset === 0) return;
  state.rankingOffset = Math.max(0, state.rankingOffset - RANKING_LIMIT);
  loadRanking();
  document.querySelector("#rankings-title").scrollIntoView({ behavior: "smooth" });
});
elements.rankingNext.addEventListener("click", () => {
  if (!state.rankingPayload || state.rankingOffset + state.rankingPayload.items.length >= state.rankingPayload.total) return;
  state.rankingOffset += RANKING_LIMIT;
  loadRanking();
  document.querySelector("#rankings-title").scrollIntoView({ behavior: "smooth" });
});
elements.compareButton.addEventListener("click", runComparison);
elements.compareClose.addEventListener("click", closeComparison);
elements.detailClose.addEventListener("click", closeDetail);
elements.activityExplore.addEventListener("click", () => {
  const source = state.rankingPayload?.items[0] || state.summaryLargest?.items[0];
  if (source) openDetail(source.booru_id, elements.activityExplore);
  else document.querySelector("#rankings-title").scrollIntoView({ behavior: "smooth" });
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && elements.navToggle.getAttribute("aria-expanded") === "true") {
    setNavigationOpen(false);
    elements.navToggle.focus();
  }
});
window.addEventListener("resize", () => {
  if (window.innerWidth > 900) setNavigationOpen(false);
});

setActiveRankingMode(state.rankingMode);
Promise.allSettled([loadRanking(), loadGrowthSummary()]).then(() => {
  elements.ecosystemMetrics.setAttribute("aria-busy", "false");
});
