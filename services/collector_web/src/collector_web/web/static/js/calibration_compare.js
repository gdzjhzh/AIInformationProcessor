const compareForm = document.querySelector("[data-calibration-compare-form]");
const compareUrlInput = document.querySelector("[data-calibration-compare-url]");
const compareThinkingInput = document.querySelector("[data-calibration-compare-thinking]");
const compareButton = document.querySelector("[data-calibration-compare-button]");
const compareResultPanel = document.querySelector("[data-calibration-compare-result]");
const compareHistoryPanel = document.querySelector("[data-calibration-compare-history]");
const compareHistorySummary = document.querySelector("[data-calibration-compare-history-summary]");

let comparePollTimer = null;
let compareHistoryPollTimer = null;
let currentCompareJobId = "";

const compareHistoryStorageKey = "aip.calibrationCompare.history";
const compareHistoryLimit = 12;
const terminalCompareStatuses = ["success", "partial", "failed"];

function escapeCompareHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function setCompareButton(label, disabled) {
  if (!compareButton) {
    return;
  }
  compareButton.textContent = label;
  compareButton.disabled = disabled;
}

function compareTone(status) {
  if (status === "success") {
    return "success";
  }
  if (status === "failed") {
    return "error";
  }
  return "warning";
}

function isCompareTerminal(status) {
  return terminalCompareStatuses.includes(status);
}

function renderCompareModels(models) {
  if (!models || models.length === 0) {
    return "";
  }
  return models
    .map((model) => {
      const effort = model.reasoning_effort ? ` / reasoning: ${model.reasoning_effort}` : "";
      const thinking = model.thinking_type ? ` / thinking: ${model.thinking_type}` : "";
      return `<span class="status-badge tone-muted">${escapeCompareHtml(model.label || model.key)}: ${escapeCompareHtml(model.model || "")}${escapeCompareHtml(effort + thinking)}</span>`;
    })
    .join("");
}

function readCompareHistory() {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(compareHistoryStorageKey) || "[]");
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed.filter((item) => item && item.job_id);
  } catch {
    return [];
  }
}

function writeCompareHistory(items) {
  try {
    window.localStorage.setItem(compareHistoryStorageKey, JSON.stringify(items.slice(0, compareHistoryLimit)));
  } catch {
    // Keep the page usable if localStorage is disabled.
  }
}

function compactCompareJob(job) {
  return {
    job_id: job.job_id || "",
    url: job.url || "",
    title: job.title || "",
    status: job.status || "",
    status_label: job.status_label || "",
    message: job.message || "",
    stage: job.stage || "",
    created_at: job.created_at || "",
    updated_at: job.updated_at || "",
    output_dir: job.output_dir || "",
    directory_url: job.directory_url || "",
    file_links: job.file_links || [],
    errors: job.errors || [],
    models: job.models || [],
    enable_thinking: Boolean(job.enable_thinking),
  };
}

function rememberCompareJob(job) {
  if (!job || !job.job_id) {
    return;
  }
  const compact = compactCompareJob(job);
  const existing = readCompareHistory().filter((item) => item.job_id !== compact.job_id);
  const merged = [compact, ...existing].slice(0, compareHistoryLimit);
  writeCompareHistory(merged);
  renderCompareHistory(merged);
}

function renderCompareJob(job) {
  if (!compareResultPanel || !job) {
    return;
  }

  const tone = compareTone(job.status);
  const fileLinks = (job.file_links || [])
    .map((link) => `
      <a class="text-link-button" href="${escapeCompareHtml(link.url)}" target="_blank" rel="noopener">
        ${escapeCompareHtml(link.label || link.filename)}
      </a>
    `)
    .join("");
  const openDirectoryButton = job.job_id && job.output_dir
    ? `
      <button class="action-button" type="button" data-calibration-compare-open-directory="${escapeCompareHtml(job.job_id)}">
        打开结果目录
      </button>
    `
    : "";
  const directoryLink = job.directory_url
    ? `
      <a class="text-link-button" href="${escapeCompareHtml(job.directory_url)}" target="_blank" rel="noopener">
        查看文件列表
      </a>
    `
    : "";
  const errors = (job.errors || [])
    .map((item) => `<p class="status-line is-error">${escapeCompareHtml(item.model)}：${escapeCompareHtml(item.message)}</p>`)
    .join("");
  const thinkingLabel = job.enable_thinking ? "已启用思考模式" : "未启用思考模式";

  compareResultPanel.className = `submit-result is-${tone}`;
  compareResultPanel.innerHTML = `
    <h3>${escapeCompareHtml(job.status_label || "处理中")}</h3>
    <div class="submit-result-body">
      <p>${escapeCompareHtml(job.message || "")}</p>
      <p>任务：${escapeCompareHtml(job.job_id || "")}</p>
      <p>思考：${escapeCompareHtml(thinkingLabel)}</p>
      ${job.title ? `<p>标题：${escapeCompareHtml(job.title)}</p>` : ""}
      ${job.output_dir ? `<p>本地目录：${escapeCompareHtml(job.output_dir)}</p>` : ""}
      <div class="compare-model-list">${renderCompareModels(job.models || [])}</div>
      ${errors}
    </div>
    <div class="submit-result-actions">
      ${openDirectoryButton}
      ${directoryLink}
      ${fileLinks}
    </div>
  `;
  compareResultPanel.hidden = false;
  rememberCompareJob(job);
}

function renderCompareMessage(message, tone = "warning") {
  if (!compareResultPanel) {
    return;
  }
  const title = tone === "error" ? "提交失败" : "任务已提交";
  compareResultPanel.className = `submit-result is-${tone}`;
  compareResultPanel.innerHTML = `
    <h3>${escapeCompareHtml(title)}</h3>
    <div class="submit-result-body">
      <p>${escapeCompareHtml(message)}</p>
    </div>
  `;
  compareResultPanel.hidden = false;
}

function renderCompareHistory(items = readCompareHistory()) {
  if (!compareHistoryPanel) {
    return;
  }

  if (compareHistorySummary) {
    const activeCount = items.filter((item) => !isCompareTerminal(item.status)).length;
    compareHistorySummary.innerHTML = `
      <span>本机最近 ${items.length} 条</span>
      <span>${activeCount} 条处理中</span>
    `;
  }

  if (items.length === 0) {
    compareHistoryPanel.innerHTML = `
      <div class="empty-state">
        <p>还没有校对对比记录。</p>
        <p>提交一次小宇宙 URL 后，这里会保留最近任务和结果目录入口。</p>
      </div>
    `;
    return;
  }

  compareHistoryPanel.innerHTML = items
    .map((job) => {
      const tone = compareTone(job.status);
      const title = job.title || job.url || job.job_id;
      const createdAt = job.created_at || job.updated_at || "";
      const statusLabel = job.status_label || job.status || "处理中";
      const openDirectoryButton = job.output_dir
        ? `
          <button class="action-button" type="button" data-calibration-compare-open-directory="${escapeCompareHtml(job.job_id)}">
            打开结果目录
          </button>
        `
        : "";
      const directoryLink = job.directory_url
        ? `
          <a class="text-link-button" href="${escapeCompareHtml(job.directory_url)}" target="_blank" rel="noopener">
            查看文件列表
          </a>
        `
        : "";

      return `
        <article class="history-item" data-calibration-compare-history-item="${escapeCompareHtml(job.job_id)}">
          <div class="history-main">
            <div class="history-title-row">
              <strong>${escapeCompareHtml(title)}</strong>
              <span class="status-badge tone-${escapeCompareHtml(tone)}">${escapeCompareHtml(statusLabel)}</span>
            </div>
            <p class="history-meta">${escapeCompareHtml(job.url || job.job_id)}</p>
            <p class="history-meta secondary">
              阶段：${escapeCompareHtml(job.stage || "pending")}
              · 思考：${job.enable_thinking ? "已启用" : "未启用"}
            </p>
            ${job.message ? `<p class="history-meta secondary">${escapeCompareHtml(job.message)}</p>` : ""}
            <div class="history-actions">
              <button class="text-link-button" type="button" data-calibration-compare-load-job="${escapeCompareHtml(job.job_id)}">
                查看状态
              </button>
              ${openDirectoryButton}
              ${directoryLink}
            </div>
          </div>
          <div class="history-side">
            <span>${escapeCompareHtml(job.job_id.slice(0, 8))}</span>
            <strong>${escapeCompareHtml(createdAt)}</strong>
          </div>
        </article>
      `;
    })
    .join("");
}

async function requestCompareJson(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json();
  return { response, payload };
}

async function loadCompareJob(jobId) {
  if (!jobId) {
    return;
  }
  const { response, payload } = await requestCompareJson(`/api/calibration-compare/${encodeURIComponent(jobId)}`);
  if (!response.ok) {
    throw new Error(payload.detail || `HTTP ${response.status}`);
  }
  currentCompareJobId = payload?.job?.job_id || jobId;
  renderCompareJob(payload.job);
  if (!isCompareTerminal(payload.job.status)) {
    if (comparePollTimer) {
      window.clearInterval(comparePollTimer);
    }
    comparePollTimer = window.setInterval(() => pollCompareJob(currentCompareJobId), 5000);
  }
}

async function refreshCompareHistoryStatus(jobId) {
  try {
    const { response, payload } = await requestCompareJson(`/api/calibration-compare/${encodeURIComponent(jobId)}`);
    if (!response.ok || !payload.job) {
      return;
    }
    rememberCompareJob(payload.job);
  } catch {
    // The backend may have restarted; keep the cached entry for file-list access.
  }
}

function refreshCompareHistoryStatuses() {
  const items = readCompareHistory();
  Promise.all(items.map((item) => refreshCompareHistoryStatus(item.job_id))).finally(() => {
    scheduleCompareHistoryPolling();
  });
}

function scheduleCompareHistoryPolling() {
  if (compareHistoryPollTimer) {
    window.clearInterval(compareHistoryPollTimer);
  }
  const hasActive = readCompareHistory().some((item) => !isCompareTerminal(item.status));
  if (!hasActive) {
    compareHistoryPollTimer = null;
    return;
  }
  compareHistoryPollTimer = window.setInterval(refreshCompareHistoryStatuses, 5000);
}

async function openCompareDirectory(jobId, button) {
  const previousLabel = button.textContent;
  button.disabled = true;
  button.textContent = "正在打开...";

  try {
    const { response, payload } = await requestCompareJson(
      `/api/calibration-compare/${encodeURIComponent(jobId)}/open-directory`,
      { method: "POST" },
    );
    if (!response.ok) {
      throw new Error(payload.detail || `HTTP ${response.status}`);
    }
    button.textContent = "已打开目录";
  } catch (error) {
    renderCompareMessage(error instanceof Error ? error.message : "打开目录失败", "error");
  } finally {
    window.setTimeout(() => {
      if (!button.isConnected) {
        return;
      }
      button.disabled = false;
      button.textContent = previousLabel || "打开结果目录";
    }, 1500);
  }
}

async function pollCompareJob(jobId) {
  if (!jobId) {
    return;
  }
  try {
    const { response, payload } = await requestCompareJson(`/api/calibration-compare/${jobId}`);
    if (!response.ok) {
      return;
    }
    const job = payload.job;
    renderCompareJob(job);
    scheduleCompareHistoryPolling();
    if (isCompareTerminal(job.status)) {
      window.clearInterval(comparePollTimer);
      comparePollTimer = null;
      setCompareButton("开始对比", false);
    }
  } catch {
    // Keep polling while the backend is still processing.
  }
}

async function handleCompareSubmit(event) {
  event.preventDefault();
  if (!compareForm || !compareUrlInput) {
    return;
  }

  const url = compareUrlInput.value.trim();
  if (!url) {
    renderCompareMessage("请先填写小宇宙 URL。", "error");
    return;
  }

  if (comparePollTimer) {
    window.clearInterval(comparePollTimer);
    comparePollTimer = null;
  }

  const enableThinking = Boolean(compareThinkingInput && compareThinkingInput.checked);
  const thinkingNote = enableThinking ? "，并为两个模型启用思考模式" : "";

  setCompareButton("正在提交...", true);
  renderCompareMessage(`已提交任务，正在等待后端下载、转录并生成两份校对稿${thinkingNote}。`);

  try {
    const { response, payload } = await requestCompareJson("/api/calibration-compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, enable_thinking: enableThinking }),
    });

    if (!response.ok) {
      throw new Error(payload.detail || `HTTP ${response.status}`);
    }

    currentCompareJobId = payload?.job?.job_id || "";
    if (!currentCompareJobId) {
      throw new Error("后端没有返回 job_id。");
    }

    renderCompareJob(payload.job);
    scheduleCompareHistoryPolling();
    comparePollTimer = window.setInterval(() => pollCompareJob(currentCompareJobId), 5000);
    pollCompareJob(currentCompareJobId);
  } catch (error) {
    renderCompareMessage(error instanceof Error ? error.message : "提交失败", "error");
    setCompareButton("开始对比", false);
  }
}

if (compareForm) {
  compareForm.addEventListener("submit", handleCompareSubmit);
}

document.addEventListener("click", (event) => {
  const target = event.target instanceof Element ? event.target : null;
  if (!target) {
    return;
  }

  const openTarget = target.closest("[data-calibration-compare-open-directory]");
  if (openTarget) {
    const jobId = openTarget.getAttribute("data-calibration-compare-open-directory") || "";
    if (jobId) {
      openCompareDirectory(jobId, openTarget);
    }
    return;
  }

  const loadTarget = target.closest("[data-calibration-compare-load-job]");
  if (loadTarget) {
    const jobId = loadTarget.getAttribute("data-calibration-compare-load-job") || "";
    if (jobId) {
      loadCompareJob(jobId).catch((error) => {
        renderCompareMessage(error instanceof Error ? error.message : "读取历史任务失败", "error");
      });
    }
  }
});

renderCompareHistory();
refreshCompareHistoryStatuses();
scheduleCompareHistoryPolling();
