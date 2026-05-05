const rssSearchInput = document.querySelector("[data-rss-search]");
const rssSourceFilter = document.querySelector("[data-rss-source-filter]");
const rssStatusFilter = document.querySelector("[data-rss-status-filter]");
const rssScoreFilter = document.querySelector("[data-rss-score-filter]");
const rssRows = Array.from(document.querySelectorAll("[data-rss-item-row]"));
const rssSourceSections = Array.from(document.querySelectorAll("[data-rss-source-section]"));
const rssEmptyFilter = document.querySelector("[data-rss-empty-filter]");

function normalizeFilterValue(value) {
  return String(value || "").trim().toLowerCase();
}

function itemMatchesFilters(row) {
  const query = normalizeFilterValue(rssSearchInput?.value);
  const source = rssSourceFilter?.value || "all";
  const status = rssStatusFilter?.value || "all";
  const scoreState = rssScoreFilter?.value || "all";

  const rowSearch = normalizeFilterValue(row.dataset.search);
  const rowSource = row.dataset.source || "";
  const rowStatus = row.dataset.status || "";
  const rowScoreState = row.dataset.scoreState || "";

  if (query && !rowSearch.includes(query)) {
    return false;
  }
  if (source !== "all" && rowSource !== source) {
    return false;
  }
  if (status !== "all" && rowStatus !== status) {
    return false;
  }
  if (scoreState !== "all" && rowScoreState !== scoreState) {
    return false;
  }
  return true;
}

function updateRssAuditFilters() {
  const query = normalizeFilterValue(rssSearchInput?.value);
  const source = rssSourceFilter?.value || "all";
  const status = rssStatusFilter?.value || "all";
  const scoreState = rssScoreFilter?.value || "all";
  const hasRowFilter = Boolean(query) || status !== "all" || scoreState !== "all";
  let visibleRows = 0;
  for (const row of rssRows) {
    const visible = itemMatchesFilters(row);
    row.hidden = !visible;
    if (visible) {
      visibleRows += 1;
    }
  }

  for (const section of rssSourceSections) {
    const rows = Array.from(section.querySelectorAll("[data-rss-item-row]"));
    if (!rows.length) {
      const sourceMismatch = source !== "all" && section.dataset.sourceName !== source;
      section.hidden = sourceMismatch || hasRowFilter;
      continue;
    }
    section.hidden = rows.every((row) => row.hidden);
  }

  if (rssEmptyFilter) {
    rssEmptyFilter.hidden = visibleRows > 0;
  }
}

for (const control of [rssSearchInput, rssSourceFilter, rssStatusFilter, rssScoreFilter]) {
  control?.addEventListener("input", updateRssAuditFilters);
  control?.addEventListener("change", updateRssAuditFilters);
}

updateRssAuditFilters();
