const rssRerunForm = document.querySelector("[data-rss-rerun-form]");
const rssRerunButton = document.querySelector("[data-rss-rerun-button]");
const rssRerunResult = document.querySelector("[data-rss-rerun-result]");

function escapeStatusHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderRssRerunMessage(message, tone = "success") {
  if (!rssRerunResult) {
    return;
  }

  rssRerunResult.className = `submit-result is-${tone}`;
  rssRerunResult.innerHTML = `
    <h3>${tone === "error" ? "重跑触发失败" : "已触发 RSS 重跑"}</h3>
    <div class="submit-result-body">
      <p>${escapeStatusHtml(message)}</p>
    </div>
  `;
  rssRerunResult.hidden = false;
}

async function requestStatusJson(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json();
  return { response, payload };
}

function waitForNextPollRun(previousFinishedAt) {
  let attempts = 0;
  const timer = window.setInterval(async () => {
    attempts += 1;
    try {
      const { response, payload } = await requestStatusJson("/api/status");
      const nextFinishedAt = payload?.rss_poll?.run_finished_at_raw || "";
      if (response.ok && nextFinishedAt && nextFinishedAt !== previousFinishedAt) {
        window.clearInterval(timer);
        window.location.reload();
      }
    } catch {
      // Keep waiting. The workflow may still be running or n8n may be restarting.
    }

    if (attempts >= 60) {
      window.clearInterval(timer);
      renderRssRerunMessage("重跑已经触发，但 5 分钟内还没有看到新的 poll_runs 摘要。可以稍后刷新本页。", "warning");
      if (rssRerunButton) {
        rssRerunButton.disabled = false;
        rssRerunButton.textContent = "手动重跑 RSS";
      }
    }
  }, 5000);
}

async function handleRssRerunSubmit(event) {
  event.preventDefault();
  if (!rssRerunButton || !rssRerunForm) {
    return;
  }

  const previousFinishedAt = rssRerunForm.dataset.currentRunFinishedAt || "";
  rssRerunButton.disabled = true;
  rssRerunButton.textContent = "正在触发...";
  renderRssRerunMessage("正在请求 n8n 手动执行 RSS 主链。");

  try {
    const { response, payload } = await requestStatusJson("/api/rss-poll/rerun", {
      method: "POST",
    });
    if (!response.ok) {
      throw new Error(payload.detail || `请求失败，HTTP ${response.status}`);
    }

    renderRssRerunMessage("n8n 已接受手动重跑请求。本页会等待新的 poll_runs 摘要，完成后自动刷新。");
    waitForNextPollRun(previousFinishedAt);
  } catch (error) {
    rssRerunButton.disabled = false;
    rssRerunButton.textContent = "手动重跑 RSS";
    renderRssRerunMessage(error instanceof Error ? error.message : "请求失败", "error");
  }
}

if (rssRerunForm) {
  rssRerunForm.addEventListener("submit", handleRssRerunSubmit);
}
