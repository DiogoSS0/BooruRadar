"use strict";

const numberFormatter = new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 });
const compactNumberFormatter = new Intl.NumberFormat(undefined, {
  notation: "compact",
  maximumFractionDigits: 1,
});
const dateFormatter = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});
const relativeFormatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

const elements = {
  systemState: document.querySelector("#system-state"),
  systemStateLabel: document.querySelector("#system-state-label"),
  refreshButton: document.querySelector("#refresh-button"),
  lastSynchronized: document.querySelector("#last-synchronized"),
  signalDetail: document.querySelector("#signal-detail"),
  overviewMetrics: document.querySelector("#overview-metrics"),
  metricSources: document.querySelector("#metric-sources"),
  metricSourcesNote: document.querySelector("#metric-sources-note"),
  metricPosts: document.querySelector("#metric-posts"),
  metricPostsNote: document.querySelector("#metric-posts-note"),
  metricReporting: document.querySelector("#metric-reporting"),
  metricCapture: document.querySelector("#metric-capture"),
  metricCaptureNote: document.querySelector("#metric-capture-note"),
  catalogSummary: document.querySelector("#catalog-summary"),
  catalogLoading: document.querySelector("#catalog-loading"),
  catalogError: document.querySelector("#catalog-error"),
  catalogErrorMessage: document.querySelector("#catalog-error-message"),
  catalogRetry: document.querySelector("#catalog-retry"),
  catalogEmpty: document.querySelector("#catalog-empty"),
  booruGrid: document.querySelector("#booru-grid"),
  compareSelection: document.querySelector("#compare-selection"),
  compareButton: document.querySelector("#compare-button"),
  compareEmpty: document.querySelector("#compare-empty"),
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
};

const state = {
  boorus: [],
  comparisonIds: new Set(),
  catalogController: null,
  detailController: null,
  compareController: null,
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
  if (className) {
    node.className = className;
  }
  if (text !== undefined) {
    node.textContent = text;
  }
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
    let message = `The API returned ${response.status}.`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string" && body.detail.trim()) {
        message = body.detail;
      }
    } catch {
      // The status code remains the useful error when no JSON detail is available.
    }
    throw new ApiError(message, response.status);
  }

  return response.json();
}

function normalizedNumber(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return null;
  }
  return value;
}

function formatNumber(value) {
  const normalized = normalizedNumber(value);
  return normalized === null ? "—" : numberFormatter.format(normalized);
}

function formatCompactNumber(value) {
  const normalized = normalizedNumber(value);
  return normalized === null ? "—" : compactNumberFormatter.format(normalized);
}

function formatSignedNumber(value) {
  const normalized = normalizedNumber(value);
  if (normalized === null) {
    return "—";
  }
  const prefix = normalized > 0 ? "+" : "";
  return `${prefix}${numberFormatter.format(normalized)}`;
}

function formatDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Unknown time" : dateFormatter.format(date);
}

function relativeDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Unknown time";
  }

  const seconds = Math.round((date.getTime() - Date.now()) / 1000);
  const intervals = [
    ["year", 31_536_000],
    ["month", 2_592_000],
    ["day", 86_400],
    ["hour", 3_600],
    ["minute", 60],
  ];
  for (const [unit, duration] of intervals) {
    if (Math.abs(seconds) >= duration || unit === "minute") {
      return relativeFormatter.format(Math.round(seconds / duration), unit);
    }
  }
  return "just now";
}

function provenanceLabel(value) {
  if (typeof value !== "string" || !value) {
    return "Not reported";
  }
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function familyLabel(value) {
  return provenanceLabel(value);
}

function unavailableLabel(value) {
  if (typeof value !== "string" || !value) {
    return "Growth unavailable";
  }
  const labels = {
    insufficient_history: "More history required",
    incompatible_snapshots: "Compatible history required",
    invalid_interval: "Valid time interval required",
  };
  if (labels[value]) {
    return labels[value];
  }
  return value.replaceAll("_", " ");
}

function safePublicUrl(value) {
  if (typeof value !== "string") {
    return null;
  }
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
}

function setSystemState(kind, label) {
  elements.systemState.classList.remove("is-online", "is-error");
  if (kind === "online") {
    elements.systemState.classList.add("is-online");
  }
  if (kind === "error") {
    elements.systemState.classList.add("is-error");
  }
  elements.systemStateLabel.textContent = label;
}

function setCatalogMode(mode, message = "") {
  elements.catalogLoading.hidden = mode !== "loading";
  elements.catalogError.hidden = mode !== "error";
  elements.catalogEmpty.hidden = mode !== "empty";
  elements.booruGrid.hidden = mode !== "ready";
  elements.overviewMetrics.setAttribute("aria-busy", String(mode === "loading"));
  elements.refreshButton.disabled = mode === "loading";
  if (message) {
    elements.catalogErrorMessage.textContent = message;
  }
}

function updateOverview(boorus) {
  const latestSnapshots = boorus
    .map((booru) => booru.latest_snapshot)
    .filter((snapshot) => snapshot !== null && snapshot !== undefined);
  const totals = latestSnapshots
    .map((snapshot) => normalizedNumber(snapshot.total_posts?.value))
    .filter((value) => value !== null);
  const aggregatePosts = totals.reduce((sum, value) => sum + value, 0);
  const latestDates = latestSnapshots
    .map((snapshot) => new Date(snapshot.captured_at))
    .filter((date) => !Number.isNaN(date.getTime()))
    .sort((left, right) => right.getTime() - left.getTime());
  const provenanceKinds = new Set(
    latestSnapshots
      .map((snapshot) => snapshot.total_posts?.provenance)
      .filter((provenance) => typeof provenance === "string"),
  );

  elements.metricSources.textContent = formatNumber(boorus.length);
  elements.metricSourcesNote.textContent = boorus.length === 1 ? "Enabled source" : "Enabled sources";
  elements.metricPosts.textContent = totals.length ? formatCompactNumber(aggregatePosts) : "—";
  elements.metricPosts.title = totals.length ? formatNumber(aggregatePosts) : "No accepted totals";
  const provenanceKindsLabel = [...provenanceKinds]
    .map(provenanceLabel)
    .sort()
    .join(" + ");
  if (!totals.length) {
    elements.metricPostsNote.textContent = "No accepted totals";
  } else if (provenanceKinds.size === 1) {
    elements.metricPostsNote.textContent = `${provenanceKindsLabel} provenance`;
  } else if (provenanceKinds.size > 1) {
    elements.metricPostsNote.textContent = `Mixed provenance: ${provenanceKindsLabel}`;
  } else {
    elements.metricPostsNote.textContent = "Provenance unavailable";
  }
  elements.metricReporting.textContent = formatNumber(latestSnapshots.length);

  if (latestDates.length) {
    const latest = latestDates[0];
    elements.metricCapture.textContent = relativeDate(latest.toISOString());
    elements.metricCaptureNote.textContent = formatDate(latest.toISOString());
  } else {
    elements.metricCapture.textContent = "—";
    elements.metricCaptureNote.textContent = "No observation loaded";
  }
}

function createBooruCard(booru) {
  const card = createElement("article", "booru-card");
  const top = createElement("div", "booru-card-top");
  top.append(
    createElement(
      "span",
      "family-badge",
      familyLabel(booru.adapter_name || booru.adapter_family),
    ),
  );

  const snapshot = booru.latest_snapshot;
  if (snapshot?.total_posts) {
    top.append(
      createElement(
        "span",
        "provenance-badge",
        provenanceLabel(snapshot.total_posts.provenance),
      ),
    );
  } else {
    top.append(createElement("span", "family-badge", "Awaiting data"));
  }
  card.append(top);

  const body = createElement("div");
  body.append(createElement("h3", "booru-card-title", booru.name));
  const metadata = createElement("div", "booru-card-meta");
  metadata.append(createElement("span", null, snapshot ? relativeDate(snapshot.captured_at) : "No snapshot"));
  body.append(metadata);

  const latest = createElement("div", "booru-latest");
  latest.append(createElement("span", null, "Latest total posts"));
  latest.append(createElement("strong", null, formatNumber(snapshot?.total_posts?.value)));
  body.append(latest);
  card.append(body);

  const actions = createElement("div", "booru-card-actions");
  const compareLabel = createElement("label", "compare-check");
  const checkbox = createElement("input");
  checkbox.type = "checkbox";
  checkbox.value = booru.id;
  checkbox.dataset.compareId = booru.id;
  checkbox.checked = state.comparisonIds.has(booru.id);
  checkbox.setAttribute("aria-label", `Compare ${booru.name}`);
  checkbox.addEventListener("change", () => {
    if (checkbox.checked) {
      if (state.comparisonIds.size >= 8) {
        checkbox.checked = false;
        return;
      }
      state.comparisonIds.add(booru.id);
    } else {
      state.comparisonIds.delete(booru.id);
    }
    updateComparisonSelection();
  });
  compareLabel.append(checkbox, createElement("span", null, "Compare"));

  const openButton = createElement("button", "card-open", "View detail →");
  openButton.type = "button";
  openButton.setAttribute("aria-label", `View ${booru.name} detail and history`);
  openButton.addEventListener("click", () => openDetail(booru.id));
  actions.append(compareLabel, openButton);
  card.append(actions);
  return card;
}

function renderCatalog(boorus) {
  elements.booruGrid.replaceChildren(...boorus.map(createBooruCard));
  elements.catalogSummary.textContent = `${boorus.length} enabled ${boorus.length === 1 ? "source" : "sources"}`;
  updateComparisonSelection();
}

function updateComparisonSelection() {
  const count = state.comparisonIds.size;
  elements.compareSelection.textContent = `${count} selected`;
  elements.compareButton.disabled = count < 2 || count > 8;
  document.querySelectorAll("[data-compare-id]").forEach((checkbox) => {
    const isSelected = state.comparisonIds.has(checkbox.dataset.compareId);
    checkbox.disabled = !isSelected && count >= 8;
  });
}

async function loadCatalog() {
  state.catalogController?.abort();
  state.catalogController = new AbortController();
  setCatalogMode("loading");
  setSystemState("connecting", "Connecting");

  try {
    const payload = await fetchJson(
      "/api/v1/boorus?limit=100&offset=0",
      state.catalogController.signal,
    );
    if (!Array.isArray(payload.items)) {
      throw new ApiError("The catalog response was not recognized.", 500);
    }

    state.boorus = payload.items;
    const knownIds = new Set(state.boorus.map((booru) => booru.id));
    state.comparisonIds.forEach((id) => {
      if (!knownIds.has(id)) {
        state.comparisonIds.delete(id);
      }
    });

    updateOverview(state.boorus);
    renderCatalog(state.boorus);
    setCatalogMode(state.boorus.length ? "ready" : "empty");
    setSystemState("online", "API connected");

    const synchronizedAt = new Date();
    elements.lastSynchronized.textContent = dateFormatter.format(synchronizedAt);
    elements.signalDetail.textContent = state.boorus.length
      ? `${state.boorus.length} public ${state.boorus.length === 1 ? "source" : "sources"} returned.`
      : "The catalog is connected and currently empty.";
  } catch (error) {
    if (error.name === "AbortError") {
      return;
    }
    const message = error instanceof Error ? error.message : "The API could not be reached.";
    setCatalogMode("error", message);
    setSystemState("error", "API unavailable");
    elements.lastSynchronized.textContent = "Connection failed";
    elements.signalDetail.textContent = "Retry when the local API is available.";
  }
}

function setCompareMode(mode, message = "") {
  elements.compareEmpty.hidden = mode !== "empty";
  elements.compareLoading.hidden = mode !== "loading";
  elements.compareError.hidden = mode !== "error";
  elements.compareResults.hidden = mode !== "ready";
  elements.compareButton.disabled = mode === "loading" || state.comparisonIds.size < 2;
  if (message) {
    elements.compareErrorMessage.textContent = message;
  }
}

function appendPrimaryCell(row, primary, secondary) {
  const cell = createElement("td");
  const wrapper = createElement("div", "table-primary");
  wrapper.append(createElement("strong", null, primary));
  if (secondary) {
    wrapper.append(createElement("span", null, secondary));
  }
  cell.append(wrapper);
  row.append(cell);
}

function numberTone(value) {
  const normalized = normalizedNumber(value);
  if (normalized === null || normalized === 0) {
    return "number-neutral";
  }
  return normalized > 0 ? "number-positive" : "number-negative";
}

function renderComparison(items) {
  const rows = items.map((item) => {
    const row = createElement("tr");
    const booru = item.booru;
    const growth = item.growth;
    const snapshot = booru.latest_snapshot;
    appendPrimaryCell(row, booru.name, familyLabel(booru.adapter_family));

    const totalCell = createElement("td", null, formatNumber(snapshot?.total_posts?.value));
    row.append(totalCell);

    const evidenceCell = createElement("td");
    evidenceCell.append(
      createElement(
        "span",
        snapshot?.total_posts ? "provenance-badge" : "family-badge",
        provenanceLabel(snapshot?.total_posts?.provenance),
      ),
    );
    row.append(evidenceCell);

    if (growth.status === "available") {
      const paceCell = createElement(
        "td",
        numberTone(growth.posts_per_day),
        `${formatSignedNumber(growth.posts_per_day)} / day`,
      );
      const deltaCell = createElement(
        "td",
        numberTone(growth.posts_delta),
        formatSignedNumber(growth.posts_delta),
      );
      row.append(paceCell, deltaCell);
    } else {
      const unavailable = unavailableLabel(growth.reason);
      row.append(
        createElement("td", "table-muted", unavailable),
        createElement("td", "table-muted", "—"),
      );
    }

    const captureCell = createElement(
      "td",
      "table-muted",
      snapshot ? formatDate(snapshot.captured_at) : "No snapshot",
    );
    row.append(captureCell);
    return row;
  });
  elements.compareBody.replaceChildren(...rows);
}

async function runComparison() {
  if (state.comparisonIds.size < 2 || state.comparisonIds.size > 8) {
    return;
  }

  state.compareController?.abort();
  state.compareController = new AbortController();
  setCompareMode("loading");

  const query = new URLSearchParams();
  state.comparisonIds.forEach((id) => query.append("booru_id", id));

  try {
    const payload = await fetchJson(
      `/api/v1/compare?${query.toString()}`,
      state.compareController.signal,
    );
    if (!Array.isArray(payload.items)) {
      throw new ApiError("The comparison response was not recognized.", 500);
    }
    renderComparison(payload.items);
    setCompareMode("ready");
  } catch (error) {
    if (error.name === "AbortError") {
      return;
    }
    const message = error instanceof Error ? error.message : "The comparison could not be loaded.";
    setCompareMode("error", message);
  }
}

function setDetailMode(mode, message = "") {
  elements.detailLoading.hidden = mode !== "loading";
  elements.detailError.hidden = mode !== "error";
  elements.detailContent.hidden = mode !== "ready";
  if (message) {
    elements.detailErrorMessage.textContent = message;
  }
}

function configureDetailLink(value) {
  const safeUrl = safePublicUrl(value);
  elements.detailLink.hidden = safeUrl === null;
  if (safeUrl) {
    elements.detailLink.href = safeUrl;
  } else {
    elements.detailLink.removeAttribute("href");
  }
}

function renderGrowth(growth) {
  if (growth.status !== "available") {
    elements.detailPace.textContent = "—";
    elements.detailPace.className = "metric-value";
    elements.detailPaceNote.textContent = unavailableLabel(growth.reason);
    elements.detailDelta.textContent = "—";
    elements.detailDelta.className = "metric-value";
    elements.detailDeltaNote.textContent = growth.detail || "Compatible history is required";
    return;
  }

  elements.detailPace.textContent = `${formatSignedNumber(growth.posts_per_day)} / day`;
  elements.detailPace.className = `metric-value ${numberTone(growth.posts_per_day)}`;
  elements.detailPaceNote.textContent = `${provenanceLabel(growth.provenance)} · normalized over ${growth.elapsed_hours.toFixed(1)} hours`;
  elements.detailDelta.textContent = formatSignedNumber(growth.posts_delta);
  elements.detailDelta.className = `metric-value ${numberTone(growth.posts_delta)}`;
  elements.detailDeltaNote.textContent = "Between the latest compatible snapshots";
}

function renderHistory(booru, snapshots) {
  elements.historyCount.textContent = `${snapshots.length} ${snapshots.length === 1 ? "observation" : "observations"}`;
  elements.historyCaption.textContent = `${booru.name} accepted observations, newest first`;
  elements.historyEmpty.hidden = snapshots.length !== 0;
  elements.historyResults.hidden = snapshots.length === 0;

  const rows = snapshots.map((snapshot) => {
    const row = createElement("tr");
    appendPrimaryCell(row, formatDate(snapshot.captured_at), relativeDate(snapshot.captured_at));
    row.append(createElement("td", null, formatNumber(snapshot.total_posts?.value)));

    const evidenceCell = createElement("td");
    evidenceCell.append(
      createElement(
        "span",
        snapshot.total_posts ? "provenance-badge" : "family-badge",
        provenanceLabel(snapshot.total_posts?.provenance),
      ),
    );
    row.append(evidenceCell);

    const identifier = typeof snapshot.id === "string" ? snapshot.id.slice(0, 8) : "—";
    const identifierCell = createElement("td", "table-muted", identifier);
    if (typeof snapshot.id === "string") {
      identifierCell.title = snapshot.id;
    }
    row.append(identifierCell);
    return row;
  });
  elements.historyBody.replaceChildren(...rows);
}

async function openDetail(booruId) {
  state.detailController?.abort();
  state.detailController = new AbortController();
  elements.detailPanel.hidden = false;
  setDetailMode("loading");
  elements.detailPanel.scrollIntoView({ behavior: "smooth", block: "start" });

  const encodedId = encodeURIComponent(booruId);
  try {
    const [booru, snapshots, growth] = await Promise.all([
      fetchJson(`/api/v1/boorus/${encodedId}`, state.detailController.signal),
      fetchJson(`/api/v1/boorus/${encodedId}/snapshots?limit=30`, state.detailController.signal),
      fetchJson(`/api/v1/boorus/${encodedId}/growth`, state.detailController.signal),
    ]);
    if (!Array.isArray(snapshots.items)) {
      throw new ApiError("The history response was not recognized.", 500);
    }

    elements.detailTitle.textContent = booru.name;
    const adapterName = booru.adapter_name
      ? `${familyLabel(booru.adapter_name)} · `
      : "";
    elements.detailFamily.textContent = `${adapterName}${familyLabel(booru.adapter_family)} adapter family`;
    configureDetailLink(booru.canonical_url);

    const latest = booru.latest_snapshot;
    elements.detailTotal.textContent = formatNumber(latest?.total_posts?.value);
    elements.detailTotalNote.textContent = latest?.total_posts
      ? `${provenanceLabel(latest.total_posts.provenance)} · ${formatDate(latest.captured_at)}`
      : "No accepted count";
    renderGrowth(growth);
    renderHistory(booru, snapshots.items);
    setDetailMode("ready");
    elements.detailClose.focus({ preventScroll: true });
  } catch (error) {
    if (error.name === "AbortError") {
      return;
    }
    const message = error instanceof Error ? error.message : "The detail view could not be loaded.";
    setDetailMode("error", message);
  }
}

function closeDetail() {
  state.detailController?.abort();
  elements.detailPanel.hidden = true;
  document.querySelector("#catalog-title")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

elements.refreshButton.addEventListener("click", loadCatalog);
elements.catalogRetry.addEventListener("click", loadCatalog);
elements.compareButton.addEventListener("click", runComparison);
elements.detailClose.addEventListener("click", closeDetail);

loadCatalog();
