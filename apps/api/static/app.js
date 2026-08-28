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
const dateOnlyFormatter = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });
const relativeFormatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
const SVG_NAMESPACE = "http://www.w3.org/2000/svg";

const elements = {
  navToggle: document.querySelector("#nav-toggle"),
  primaryNav: document.querySelector("#primary-nav"),
  catalogConnection: document.querySelector("#catalog-connection"),
  catalogConnectionLabel: document.querySelector("#catalog-connection-label"),
  catalogSignals: document.querySelector("#catalog-signals"),
  signalTracked: document.querySelector("#signal-tracked"),
  signalTrackedNote: document.querySelector("#signal-tracked-note"),
  signalReporting: document.querySelector("#signal-reporting"),
  signalLatest: document.querySelector("#signal-latest"),
  signalLatestNote: document.querySelector("#signal-latest-note"),
  historyStatusTitle: document.querySelector("#history-status-title"),
  historyStatusCopy: document.querySelector("#history-status-copy"),
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
  historyChart: document.querySelector("#history-chart"),
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

function createSvgElement(tagName, attributes = {}) {
  const node = document.createElementNS(SVG_NAMESPACE, tagName);
  Object.entries(attributes).forEach(([name, value]) => {
    node.setAttribute(name, String(value));
  });
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
      if (typeof body.detail === "string" && body.detail.trim()) {
        message = body.detail;
      }
    } catch {
      // The bounded status message remains useful when no JSON detail is available.
    }
    throw new ApiError(message, response.status);
  }

  return response.json();
}

function normalizedNumber(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
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
  return `${normalized > 0 ? "+" : ""}${numberFormatter.format(normalized)}`;
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
  if (date === null) {
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

function labelFromIdentifier(value, fallback = "Not reported") {
  if (typeof value !== "string" || !value.trim()) {
    return fallback;
  }
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function provenanceLabel(value) {
  return labelFromIdentifier(value);
}

function provenanceClass(value) {
  const knownClasses = {
    observed: "provenance-observed",
    estimated: "provenance-estimated",
    owner_verified: "provenance-owner-verified",
  };
  return knownClasses[value] || "";
}

function unavailableLabel(value) {
  const labels = {
    insufficient_history: "More history required",
    incompatible_snapshots: "Compatible history required",
    invalid_interval: "Valid time interval required",
  };
  if (typeof value !== "string" || !value) {
    return "Growth unavailable";
  }
  return labels[value] || value.replaceAll("_", " ");
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

function publicDomain(value) {
  const safeUrl = safePublicUrl(value);
  if (safeUrl === null) {
    return "Public source";
  }
  return new URL(safeUrl).hostname.replace(/^www\./, "");
}

function setNavigationOpen(open) {
  elements.navToggle.setAttribute("aria-expanded", String(open));
  elements.navToggle.setAttribute("aria-label", open ? "Close navigation" : "Open navigation");
  elements.primaryNav.classList.toggle("is-open", open);
  document.body.classList.toggle("nav-open", open);
}

function setConnectionState(kind, label) {
  elements.catalogConnection.classList.remove("is-online", "is-error");
  if (kind === "online") {
    elements.catalogConnection.classList.add("is-online");
  }
  if (kind === "error") {
    elements.catalogConnection.classList.add("is-error");
  }
  elements.catalogConnectionLabel.textContent = label;
}

function setCatalogMode(mode, message = "") {
  elements.catalogLoading.hidden = mode !== "loading";
  elements.catalogError.hidden = mode !== "error";
  elements.catalogEmpty.hidden = mode !== "empty";
  elements.booruGrid.hidden = mode !== "ready";
  elements.catalogSignals.setAttribute("aria-busy", String(mode === "loading"));
  if (message) {
    elements.catalogErrorMessage.textContent = message;
  }
}

function updateSignals(boorus) {
  const snapshots = boorus
    .map((booru) => booru.latest_snapshot)
    .filter((snapshot) => snapshot !== null && snapshot !== undefined);
  const latestDates = snapshots
    .map((snapshot) => validDate(snapshot.captured_at))
    .filter((date) => date !== null)
    .sort((left, right) => right.getTime() - left.getTime());

  elements.signalTracked.textContent = formatNumber(boorus.length);
  elements.signalTrackedNote.textContent = boorus.length === 1 ? "Enabled source" : "Enabled sources";
  elements.signalReporting.textContent = formatNumber(snapshots.length);

  if (latestDates.length) {
    const latest = latestDates[0];
    elements.signalLatest.textContent = relativeDate(latest.toISOString());
    elements.signalLatestNote.textContent = formatDate(latest.toISOString());
  } else {
    elements.signalLatest.textContent = "—";
    elements.signalLatestNote.textContent = "No accepted observation yet";
  }

  if (snapshots.length) {
    elements.historyStatusTitle.textContent = "History is accumulating";
    elements.historyStatusCopy.textContent = `${snapshots.length} ${snapshots.length === 1 ? "source has" : "sources have"} an accepted latest observation. Open a source to inspect its exact history.`;
  } else {
    elements.historyStatusTitle.textContent = "Building history";
    elements.historyStatusCopy.textContent = "The catalog is ready, but no accepted observations are available yet.";
  }
}

function sourceInitial(name) {
  if (typeof name !== "string" || !name.trim()) {
    return "?";
  }
  return name.trim().charAt(0);
}

function createBooruCard(booru) {
  const card = createElement("article", "booru-card");
  const top = createElement("div", "booru-card-top");
  const identity = createElement("div", "source-identity");
  identity.append(createElement("span", "source-avatar", sourceInitial(booru.name)));

  const title = createElement("div", "source-title");
  title.append(createElement("h3", null, booru.name));
  title.append(createElement("span", "source-domain", publicDomain(booru.canonical_url)));
  identity.append(title);
  top.append(identity);
  top.append(
    createElement(
      "span",
      "family-badge",
      labelFromIdentifier(booru.adapter_family, "Source"),
    ),
  );
  card.append(top);

  const snapshot = booru.latest_snapshot;
  const body = createElement("div", "booru-card-body");
  body.append(createElement("span", "booru-total-label", "Latest total posts"));
  const total = createElement(
    "strong",
    "booru-total",
    snapshot?.total_posts ? formatCompactNumber(snapshot.total_posts.value) : "Awaiting data",
  );
  total.title = snapshot?.total_posts
    ? `${formatNumber(snapshot.total_posts.value)} posts`
    : "No accepted total";
  body.append(total);

  if (snapshot?.total_posts) {
    body.append(
      createElement(
        "span",
        `provenance-badge ${provenanceClass(snapshot.total_posts.provenance)}`.trim(),
        provenanceLabel(snapshot.total_posts.provenance),
      ),
    );
  } else {
    body.append(createElement("span", "family-badge", "No snapshot"));
  }
  body.append(
    createElement(
      "span",
      "booru-capture",
      snapshot ? `Captured ${relativeDate(snapshot.captured_at)}` : "Waiting for an accepted observation",
    ),
  );
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

  const openButton = createElement("button", "card-open", "View history →");
  openButton.type = "button";
  openButton.setAttribute("aria-label", `View ${booru.name} history and growth`);
  openButton.addEventListener("click", () => openDetail(booru.id));
  actions.append(compareLabel, openButton);
  card.append(actions);
  return card;
}

function renderCatalog(boorus) {
  elements.booruGrid.replaceChildren(...boorus.map(createBooruCard));
  updateComparisonSelection();
}

function updateComparisonSelection() {
  const count = state.comparisonIds.size;
  elements.compareSelection.textContent = `${count} selected`;
  elements.compareButton.disabled = count < 2 || count > 8;
  document.querySelectorAll("[data-compare-id]").forEach((checkbox) => {
    const selected = state.comparisonIds.has(checkbox.dataset.compareId);
    checkbox.disabled = !selected && count >= 8;
  });
}

async function loadCatalog() {
  state.catalogController?.abort();
  state.catalogController = new AbortController();
  setCatalogMode("loading");
  setConnectionState("connecting", "Connecting to the public API");

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

    updateSignals(state.boorus);
    renderCatalog(state.boorus);
    setCatalogMode(state.boorus.length ? "ready" : "empty");
    setConnectionState("online", "Public API connected");
  } catch (error) {
    if (error.name === "AbortError") {
      return;
    }
    const message = error instanceof Error ? error.message : "The public API could not be reached.";
    setCatalogMode("error", message);
    setConnectionState("error", "Public API unavailable");
    elements.catalogSignals.setAttribute("aria-busy", "false");
    elements.historyStatusTitle.textContent = "Live history unavailable";
    elements.historyStatusCopy.textContent = "Static product information remains available while the catalog connection recovers.";
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
    appendPrimaryCell(row, booru.name, publicDomain(booru.canonical_url));
    row.append(createElement("td", null, formatNumber(snapshot?.total_posts?.value)));

    const evidenceCell = createElement("td");
    evidenceCell.append(
      createElement(
        "span",
        snapshot?.total_posts
          ? `provenance-badge ${provenanceClass(snapshot.total_posts.provenance)}`.trim()
          : "family-badge",
        provenanceLabel(snapshot?.total_posts?.provenance),
      ),
    );
    row.append(evidenceCell);

    if (growth.status === "available") {
      row.append(
        createElement(
          "td",
          numberTone(growth.posts_per_day),
          `${formatSignedNumber(growth.posts_per_day)} / day`,
        ),
        createElement("td", numberTone(growth.posts_delta), formatSignedNumber(growth.posts_delta)),
      );
    } else {
      row.append(
        createElement("td", "table-muted", unavailableLabel(growth.reason)),
        createElement("td", "table-muted", "—"),
      );
    }

    row.append(
      createElement(
        "td",
        "table-muted",
        snapshot ? formatDate(snapshot.captured_at) : "No snapshot",
      ),
    );
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
    elements.compareResults.scrollIntoView({ behavior: "smooth", block: "nearest" });
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
    elements.detailPace.className = "";
    elements.detailPaceNote.textContent = unavailableLabel(growth.reason);
    elements.detailDelta.textContent = "—";
    elements.detailDelta.className = "";
    elements.detailDeltaNote.textContent = growth.detail || "Compatible history is required";
    return;
  }

  elements.detailPace.textContent = `${formatSignedNumber(growth.posts_per_day)} / day`;
  elements.detailPace.className = numberTone(growth.posts_per_day);
  elements.detailPaceNote.textContent = `${provenanceLabel(growth.provenance)} over ${growth.elapsed_hours.toFixed(1)} hours`;
  elements.detailDelta.textContent = formatSignedNumber(growth.posts_delta);
  elements.detailDelta.className = numberTone(growth.posts_delta);
  elements.detailDeltaNote.textContent = "Between the latest compatible snapshots";
}

function renderHistoryChart(snapshots) {
  const observations = snapshots
    .map((snapshot) => ({
      snapshot,
      capturedAt: validDate(snapshot.captured_at),
      value: normalizedNumber(snapshot.total_posts?.value),
    }))
    .filter((item) => item.capturedAt !== null && item.value !== null)
    .sort((left, right) => left.capturedAt.getTime() - right.capturedAt.getTime());

  elements.historyChart.replaceChildren();
  if (observations.length < 2) {
    const building = createElement("div", "history-building");
    building.append(
      createElement("span", "history-radar"),
      createElement("strong", null, "Building history"),
      createElement(
        "p",
        null,
        observations.length
          ? "One accepted observation is available. A trend requires compatible history."
          : "More trend data will appear as accepted observations accumulate.",
      ),
    );
    building.firstChild.setAttribute("aria-hidden", "true");
    elements.historyChart.append(building);
    elements.historyChart.setAttribute("aria-label", "Building snapshot history");
    return;
  }

  const width = 720;
  const height = 280;
  const padding = { top: 28, right: 34, bottom: 42, left: 48 };
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
    svg.append(createSvgElement("line", {
      class: "chart-guide",
      x1: padding.left,
      y1: y,
      x2: width - padding.right,
      y2: y,
    }));
  });

  const pointString = points.map((point) => `${point.x},${point.y}`).join(" ");
  const areaPath = [
    `M ${points[0].x} ${padding.top + plotHeight}`,
    ...points.map((point) => `L ${point.x} ${point.y}`),
    `L ${points.at(-1).x} ${padding.top + plotHeight}`,
    "Z",
  ].join(" ");
  svg.append(createSvgElement("path", { class: "chart-area", d: areaPath }));
  svg.append(createSvgElement("polyline", { class: "chart-line", points: pointString }));

  points.forEach((point) => {
    const circle = createSvgElement("circle", {
      class: "chart-point",
      cx: point.x,
      cy: point.y,
      r: 5,
    });
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
    const label = createSvgElement("text", {
      class: "chart-label",
      x,
      y,
      "text-anchor": anchor,
    });
    label.textContent = text;
    svg.append(label);
  });

  elements.historyChart.append(svg);
  elements.historyChart.setAttribute(
    "aria-label",
    `${observations.length} exact accepted snapshot observations`,
  );
}

function renderHistory(booru, snapshots) {
  elements.historyCount.textContent = `${snapshots.length} ${snapshots.length === 1 ? "observation" : "observations"}`;
  elements.historyCaption.textContent = `${booru.name} accepted observations, newest first`;
  elements.historyEmpty.hidden = snapshots.length !== 0;
  elements.historyResults.hidden = snapshots.length === 0;
  renderHistoryChart(snapshots);

  const rows = snapshots.map((snapshot) => {
    const row = createElement("tr");
    appendPrimaryCell(row, formatDate(snapshot.captured_at), relativeDate(snapshot.captured_at));
    row.append(createElement("td", null, formatNumber(snapshot.total_posts?.value)));

    const evidenceCell = createElement("td");
    evidenceCell.append(
      createElement(
        "span",
        snapshot.total_posts
          ? `provenance-badge ${provenanceClass(snapshot.total_posts.provenance)}`.trim()
          : "family-badge",
        provenanceLabel(snapshot.total_posts?.provenance),
      ),
    );
    row.append(evidenceCell);
    return row;
  });
  elements.historyBody.replaceChildren(...rows);
}

async function openDetail(booruId) {
  state.detailController?.abort();
  state.detailController = new AbortController();
  elements.detailPanel.hidden = false;
  elements.detailTitle.textContent = "Loading source";
  elements.detailFamily.textContent = "Reading accepted public data";
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
      ? `${labelFromIdentifier(booru.adapter_name)} · `
      : "";
    elements.detailFamily.textContent = `${adapterName}${labelFromIdentifier(booru.adapter_family)} adapter family`;
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
  document.querySelector("#explore-title")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

elements.navToggle.addEventListener("click", () => {
  setNavigationOpen(elements.navToggle.getAttribute("aria-expanded") !== "true");
});

elements.primaryNav.addEventListener("click", (event) => {
  if (event.target.closest("a")) {
    setNavigationOpen(false);
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && elements.navToggle.getAttribute("aria-expanded") === "true") {
    setNavigationOpen(false);
    elements.navToggle.focus();
  }
});

window.addEventListener("resize", () => {
  if (window.innerWidth > 900) {
    setNavigationOpen(false);
  }
});

elements.catalogRetry.addEventListener("click", loadCatalog);
elements.compareButton.addEventListener("click", runComparison);
elements.detailClose.addEventListener("click", closeDetail);

loadCatalog();
