const form = document.querySelector("[data-manual-submit-form]");
const urlInput = document.querySelector("[data-manual-submit-url]");
const submitButton = document.querySelector("[data-manual-submit-button]");
const resultPanel = document.querySelector("[data-manual-submit-result]");
const statusPanel = document.querySelector("[data-submission-detail]");
const selectedSubmissionId = Number(
  document.querySelector("[data-selected-submission-id]")?.dataset.selectedSubmissionId || "",
);

const manualSubmitPageBaseUrl = "/manual-media-submit";

let pollTimer = null;
let lastSubmissionStatus = "";
let pendingSubmitUrl = "";

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function statusTone(status) {
  switch (status) {
    case "running":
      return "accent";
    case "completed":
      return "success";
    case "needs_confirmation":
      return "warning";
    case "cancelled":
      return "muted";
    case "error":
      return "error";
    default:
      return "muted";
  }
}

function statusLabel(status) {
  switch (status) {
    case "queued":
      return "已排队";
    case "running":
      return "处理中";
    case "completed":
      return "已完成";
    case "needs_confirmation":
      return "发现重复";
    case "cancelled":
      return "已取消";
    case "error":
      return "处理失败";
    default:
      return status || "未知状态";
  }
}

function setSubmitButtonState(label, disabled) {
  if (!submitButton) {
    return;
  }
  submitButton.disabled = disabled;
  submitButton.textContent = label;
}

function renderSubmitMessage(message, tone = "success") {
  if (!resultPanel) {
    return;
  }

  let title = "请求已提交";
  if (tone === "error") {
    title = "提交失败";
  } else if (tone === "warning") {
    title = "提交前预检查";
  }

  resultPanel.className = `submit-result is-${tone}`;
  resultPanel.innerHTML = `
    <h3>${escapeHtml(title)}</h3>
    <div class="submit-result-body">
      <p>${escapeHtml(message)}</p>
    </div>
  `;
  resultPanel.hidden = false;
}

function renderPrecheckWarning(precheck) {
  if (!resultPanel) {
    return;
  }

  const matched = precheck.matched_submission || {};
  const details = [];
  if (matched.id) {
    details.push(`<p>命中记录：提交 #${escapeHtml(matched.id)}</p>`);
  }
  if (matched.status_label || matched.status) {
    details.push(`<p>当前状态：${escapeHtml(matched.status_label || statusLabel(matched.status))}</p>`);
  }
  if (matched.created_at) {
    details.push(`<p>首次时间：${escapeHtml(matched.created_at)}</p>`);
  }
  if (precheck.match_reason === "canonical_url" && precheck.canonical_url) {
    details.push(`<p>规范链接：${escapeHtml(precheck.canonical_url)}</p>`);
  } else if (precheck.match_reason === "resolved_url" && precheck.resolved_url) {
    details.push(`<p>解析链接：${escapeHtml(precheck.resolved_url)}</p>`);
  }

  resultPanel.className = "submit-result is-warning";
  resultPanel.innerHTML = `
    <h3>提交前预检查</h3>
    <div class="submit-result-body">
      <p>${escapeHtml(precheck.summary || "这条链接已经有历史记录。")}</p>
      ${details.join("")}
    </div>
    <div class="submit-result-actions">
      ${matched.id ? `<a class="text-link-button" href="${manualSubmitPageBaseUrl}?submission_id=${escapeHtml(matched.id)}">查看现有记录</a>` : ""}
      <button class="secondary-button" type="button" data-precheck-continue>仍然继续提交</button>
    </div>
  `;
  resultPanel.hidden = false;
}

function renderSubmissionDetail(submission) {
  if (!statusPanel || !submission) {
    return;
  }

  const detailLines = [];
  if (submission.summary) {
    detailLines.push(`<p class="status-line">${escapeHtml(submission.summary)}</p>`);
  }
  if (submission.canonical_url) {
    detailLines.push(`
      <p class="status-line">
        规范链接：
        <a href="${escapeHtml(submission.canonical_url)}" target="_blank" rel="noopener">${escapeHtml(submission.canonical_url)}</a>
      </p>
    `);
  }
  if (submission.vault_path) {
    detailLines.push(`<p class="status-line">笔记路径：${escapeHtml(submission.vault_path)}</p>`);
  }
  if (submission.item_id) {
    detailLines.push(`<p class="status-line">item_id：${escapeHtml(submission.item_id)}</p>`);
  }
  if (submission.cancellation_note) {
    detailLines.push(`<p class="status-line">说明：${escapeHtml(submission.cancellation_note)}</p>`);
  } else if (submission.error) {
    detailLines.push(`<p class="status-line is-error">错误：${escapeHtml(submission.error)}</p>`);
  }
  if (submission.rerun_of_submission_id) {
    detailLines.push(
      `<p class="status-line">这是一次重跑，来源于提交 #${escapeHtml(submission.rerun_of_submission_id)}</p>`,
    );
  }
  if (submission.qdrant_delete_detail) {
    detailLines.push(
      `<p class="status-line">这次重跑前已尝试删除旧向量：删除前 ${escapeHtml(submission.qdrant_delete_detail.count_before)} 条，删除后 ${escapeHtml(submission.qdrant_delete_detail.count_after)} 条。</p>`,
    );
  }

  const cancelActionHtml = submission.can_cancel
    ? `
      <div class="status-actions">
        <button
          class="secondary-button"
          type="button"
          data-cancel-submission
          data-submission-id="${escapeHtml(submission.id)}"
          data-cancel-label="${escapeHtml(submission.cancel_action_label || "取消提交")}"
        >
          ${escapeHtml(submission.cancel_action_label || "取消提交")}
        </button>
        <p class="status-action-hint">
          ${escapeHtml(submission.cancel_action_hint || "如果请求还没发出去，会直接取消。")}
        </p>
      </div>
    `
    : "";

  const rerunActionHtml = submission.can_delete_vector_and_rerun
    ? `
      <div class="status-actions">
        <button
          class="action-button"
          type="button"
          data-delete-vector-and-rerun
          data-submission-id="${escapeHtml(submission.id)}"
        >
          删除旧向量并重跑
        </button>
        <p class="status-action-hint">
          当前这条提交被静默去重拦住了。这个动作只删除 Qdrant 里的旧向量，不删除历史笔记。
        </p>
      </div>
    `
    : "";

  statusPanel.innerHTML = `
    <header class="status-header">
      <div>
        <p class="eyebrow">处理状态</p>
        <div class="status-title-row">
          <h2>${escapeHtml(submission.title || submission.request_url)}</h2>
          <span class="status-badge tone-${statusTone(submission.status)}">${escapeHtml(statusLabel(submission.status))}</span>
        </div>
        <p class="status-text">
          当前阶段：${escapeHtml(submission.stage || "manual_media_submit")}
          ${submission.is_active ? "，页面会自动刷新状态。" : ""}
        </p>
      </div>
      <div class="status-side">
        <span>提交 #${escapeHtml(submission.id)}</span>
        <strong>${escapeHtml(submission.created_at || "")}</strong>
      </div>
    </header>

    <div class="status-grid">
      <article class="detail-card">
        <span class="detail-label">原始 URL</span>
        <strong class="detail-value break-all">${escapeHtml(submission.request_url || "")}</strong>
      </article>
      <article class="detail-card">
        <span class="detail-label">耗时</span>
        <strong class="detail-value">${escapeHtml(submission.duration_label || "等待开始")}</strong>
      </article>
      <article class="detail-card">
        <span class="detail-label">写入状态</span>
        <strong class="detail-value">${escapeHtml(submission.vault_write_status || "pending")}</strong>
      </article>
      <article class="detail-card">
        <span class="detail-label">去重动作</span>
        <strong class="detail-value">${escapeHtml(submission.dedupe_action || "pending")}</strong>
      </article>
    </div>

    <div class="status-body">
      ${detailLines.join("")}
    </div>
    ${cancelActionHtml}
    ${rerunActionHtml}
  `;
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json();
  return { response, payload };
}

async function runPrecheck(url) {
  const { response, payload } = await requestJson("/api/manual-media-submit/precheck", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });

  if (!response.ok) {
    throw new Error(payload.detail || `预检查失败，HTTP ${response.status}`);
  }

  return payload;
}

async function submitManualUrl(url) {
  setSubmitButtonState("正在提交...", true);
  renderSubmitMessage("已经创建请求，马上跳转到状态页。");

  const { response, payload } = await requestJson("/api/manual-media-submit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });

  if (!response.ok) {
    throw new Error(payload.detail || `请求失败，HTTP ${response.status}`);
  }

  const submissionId = payload?.submission?.id;
  if (!submissionId) {
    throw new Error("请求已提交，但没有拿到 submission_id。");
  }

  window.location.assign(`${manualSubmitPageBaseUrl}?submission_id=${submissionId}`);
}

async function handleSubmit(event) {
  event.preventDefault();
  if (!form || !urlInput) {
    return;
  }

  const url = urlInput.value.trim();
  if (!url) {
    renderSubmitMessage("请先填写 URL。", "error");
    return;
  }

  pendingSubmitUrl = "";
  setSubmitButtonState("正在预检查...", true);

  try {
    const precheck = await runPrecheck(url);
    if (precheck.duplicate_found) {
      pendingSubmitUrl = url;
      renderPrecheckWarning(precheck);
      return;
    }

    await submitManualUrl(url);
  } catch (error) {
    try {
      renderSubmitMessage("预检查失败，已直接继续提交。");
      await submitManualUrl(url);
    } catch (submitError) {
      renderSubmitMessage(
        submitError instanceof Error ? submitError.message : "请求失败",
        "error",
      );
    }
  } finally {
    setSubmitButtonState("开始处理", false);
  }
}

async function pollSubmission(submissionId) {
  try {
    const { response, payload } = await requestJson(`/api/manual-media-submit/${submissionId}`);
    if (!response.ok) {
      return;
    }

    const submission = payload.submission;
    renderSubmissionDetail(submission);

    if (lastSubmissionStatus && lastSubmissionStatus !== submission.status && !submission.is_active) {
      window.location.reload();
      return;
    }

    lastSubmissionStatus = submission.status;
    if (!submission.is_active && pollTimer) {
      window.clearInterval(pollTimer);
      pollTimer = null;
    }
  } catch {
    // Keep the current view. The next poll may recover.
  }
}

async function handleDeleteVectorAndRerun(event) {
  const button = event.target.closest("[data-delete-vector-and-rerun]");
  if (!button) {
    return false;
  }

  const submissionId = Number(button.dataset.submissionId || "");
  if (!submissionId) {
    return true;
  }

  const confirmed = window.confirm("检测到重复内容。要删除旧向量并重新跑一遍吗？");
  if (!confirmed) {
    return true;
  }

  button.disabled = true;
  button.textContent = "正在删除并重跑...";

  try {
    const { response, payload } = await requestJson(
      `/api/manual-media-submit/${submissionId}/delete-vector-and-rerun`,
      { method: "POST" },
    );

    if (!response.ok) {
      window.alert(payload.detail || `请求失败，HTTP ${response.status}`);
      button.disabled = false;
      button.textContent = "删除旧向量并重跑";
      return true;
    }

    const newSubmissionId = payload?.submission?.id;
    if (!newSubmissionId) {
      window.alert("已经发起重跑，但没有拿到新的 submission_id。");
      button.disabled = false;
      button.textContent = "删除旧向量并重跑";
      return true;
    }

    window.location.assign(`${manualSubmitPageBaseUrl}?submission_id=${newSubmissionId}`);
  } catch (error) {
    window.alert(error instanceof Error ? error.message : "重跑请求失败");
    button.disabled = false;
    button.textContent = "删除旧向量并重跑";
  }

  return true;
}

async function handleCancelSubmission(event) {
  const button = event.target.closest("[data-cancel-submission]");
  if (!button) {
    return false;
  }

  const submissionId = Number(button.dataset.submissionId || "");
  if (!submissionId) {
    return true;
  }

  const actionLabel = button.dataset.cancelLabel || "取消提交";
  const confirmed = window.confirm(
    actionLabel === "停止跟踪"
      ? "这不会强制中断已经发给 n8n 的处理，只会停止当前记录继续等待结果。要继续吗？"
      : "要取消这条手动提交吗？",
  );
  if (!confirmed) {
    return true;
  }

  button.disabled = true;
  button.textContent = "正在处理...";

  try {
    const { response, payload } = await requestJson(
      `/api/manual-media-submit/${submissionId}/cancel`,
      { method: "POST" },
    );

    if (!response.ok) {
      window.alert(payload.detail || `请求失败，HTTP ${response.status}`);
      button.disabled = false;
      button.textContent = actionLabel;
      return true;
    }

    window.location.assign(`${manualSubmitPageBaseUrl}?submission_id=${submissionId}`);
  } catch (error) {
    window.alert(error instanceof Error ? error.message : "取消请求失败");
    button.disabled = false;
    button.textContent = actionLabel;
  }

  return true;
}

async function handlePrecheckContinue(event) {
  const button = event.target.closest("[data-precheck-continue]");
  if (!button) {
    return false;
  }

  if (!pendingSubmitUrl) {
    renderSubmitMessage("没有待继续提交的 URL，请重新点一次开始处理。", "error");
    return true;
  }

  button.disabled = true;
  button.textContent = "正在继续提交...";

  try {
    await submitManualUrl(pendingSubmitUrl);
  } catch (error) {
    renderSubmitMessage(
      error instanceof Error ? error.message : "请求失败",
      "error",
    );
    button.disabled = false;
    button.textContent = "仍然继续提交";
  }

  return true;
}

if (form) {
  form.addEventListener("submit", handleSubmit);
}

document.addEventListener("click", async (event) => {
  if (await handleCancelSubmission(event)) {
    return;
  }
  if (await handleDeleteVectorAndRerun(event)) {
    return;
  }
  await handlePrecheckContinue(event);
});

if (selectedSubmissionId) {
  lastSubmissionStatus = document
    .querySelector("[data-selected-submission-active]")
    ?.dataset.selectedSubmissionActive === "true"
    ? "running"
    : "";
  pollSubmission(selectedSubmissionId);
  pollTimer = window.setInterval(() => pollSubmission(selectedSubmissionId), 3000);
}
