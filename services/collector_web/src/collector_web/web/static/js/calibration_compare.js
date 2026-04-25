const compareForm = document.querySelector("[data-calibration-compare-form]");
const compareUrlInput = document.querySelector("[data-calibration-compare-url]");
const compareThinkingInput = document.querySelector("[data-calibration-compare-thinking]");
const compareButton = document.querySelector("[data-calibration-compare-button]");
const compareResultPanel = document.querySelector("[data-calibration-compare-result]");

let comparePollTimer = null;
let currentCompareJobId = "";

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
  const directoryLink = job.directory_url
    ? `
      <a class="action-button" href="${escapeCompareHtml(job.directory_url)}" target="_blank" rel="noopener">
        打开结果目录
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
      ${directoryLink}
      ${fileLinks}
    </div>
  `;
  compareResultPanel.hidden = false;
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

async function requestCompareJson(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json();
  return { response, payload };
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
    if (["success", "partial", "failed"].includes(job.status)) {
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
