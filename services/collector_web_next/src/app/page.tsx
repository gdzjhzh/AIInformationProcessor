import { AppShell } from "@/components/app-shell";
import { HeroStage } from "@/components/hero-stage";
import { EmptyPanel, SectionTitle, StatCard, StatusPill } from "@/components/ui";
import {
  getCollections,
  getCollectorApiBaseUrl,
  getLatestRssPoll,
  getServiceStatus,
} from "@/lib/collector-api";
import { apiTone, numberValue, shortError, textValue } from "@/lib/view-model";

export default async function HomePage() {
  const [collections, status, rssPoll] = await Promise.all([
    getCollections(),
    getServiceStatus(),
    getLatestRssPoll(),
  ]);
  const mode = apiTone([collections, status, rssPoll]);
  const summary = collections.data.summary ?? {};
  const platformGroups = collections.data.platform_groups ?? [];
  const recentSubmissions = collections.data.manual_submissions ?? [];
  const pollSummary = rssPoll.data.poll ?? {};
  const llmUsage = pollSummary.llm_usage ?? rssPoll.data.llm_usage ?? {};
  const hasTokenUsage =
    Boolean(pollSummary.llm_usage || rssPoll.data.llm_usage) ||
    "llm_total_tokens" in pollSummary ||
    "llm_prompt_tokens" in pollSummary ||
    "llm_completion_tokens" in pollSummary ||
    "llm_total_tokens" in rssPoll.data;
  const tokenUsage = {
    totalTokens: numberValue(llmUsage.total_tokens ?? pollSummary.llm_total_tokens ?? rssPoll.data.llm_total_tokens),
    inputTokens: numberValue(llmUsage.prompt_tokens ?? pollSummary.llm_prompt_tokens ?? rssPoll.data.llm_prompt_tokens),
    outputTokens: numberValue(
      llmUsage.completion_tokens ?? pollSummary.llm_completion_tokens ?? rssPoll.data.llm_completion_tokens,
    ),
    calls: numberValue(llmUsage.calls ?? pollSummary.llm_calls ?? rssPoll.data.llm_calls),
    usageMissing: numberValue(
      llmUsage.usage_missing ?? pollSummary.llm_usage_missing ?? rssPoll.data.llm_usage_missing,
    ),
    hasData: hasTokenUsage,
  };
  const tokenHistory = (rssPoll.data.token_history ?? []).map((point) => ({
    date: textValue(point.date, ""),
    label: textValue(point.label, textValue(point.date, "")),
    inputTokens: numberValue(point.llm_prompt_tokens),
    outputTokens: numberValue(point.llm_completion_tokens),
    totalTokens: numberValue(point.llm_total_tokens),
  }));

  return (
    <AppShell>
      <div className="grid gap-6">
        <HeroStage
          apiMode={mode}
          subscriptionCount={numberValue(summary.subscription_count)}
          activeCount={numberValue(summary.active_subscription_count)}
          tokenUsage={tokenUsage}
          tokenHistory={tokenHistory}
        />

        <section className="grid gap-4 md:grid-cols-3">
          <StatCard
            label="平台数"
            value={numberValue(summary.platform_count)}
            detail="来自 FastAPI /api/collections 的平台分组。"
          />
          <StatCard
            label="订阅总数"
            value={numberValue(summary.subscription_count)}
            detail="当前 Collector Web 识别到的订阅源数量。"
          />
          <StatCard
            label="启用中"
            value={numberValue(summary.active_subscription_count)}
            detail="状态为 active 的订阅源。"
          />
        </section>

        <section className="grid gap-5 lg:grid-cols-[1.2fr_0.8fr]">
          <div>
            <SectionTitle eyebrow="Sources" title="订阅源分布">
              <StatusPill tone={mode}>{mode === "live" ? "实时数据" : "离线占位"}</StatusPill>
            </SectionTitle>
            {platformGroups.length ? (
              <div className="grid gap-3">
                {platformGroups.slice(0, 5).map((group, index) => (
                  <article
                    key={`${group.platform ?? "platform"}-${index}`}
                    className="rounded-lg border border-white/10 bg-white/[0.045] p-4 shadow-2xl shadow-black/15 backdrop-blur"
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0">
                        <h3 className="truncate text-base font-semibold">
                          {textValue(group.label, "未命名平台")}
                        </h3>
                        <p className="mt-1 font-mono text-xs text-slate-500">
                          {textValue(group.platform, "unknown")}
                        </p>
                      </div>
                      <StatusPill tone="success">
                        {numberValue(group.active_subscription_count)} active
                      </StatusPill>
                    </div>
                    <div className="mt-4 grid gap-2">
                      {(group.subscriptions ?? []).slice(0, 3).map((subscription, itemIndex) => (
                        <div
                          key={`${subscription.source_url ?? "source"}-${itemIndex}`}
                          className="rounded border border-white/10 bg-white/[0.035] px-3 py-2"
                        >
                          <p className="truncate text-sm font-medium">
                            {textValue(subscription.display_name, "未命名订阅")}
                          </p>
                          <p className="mt-1 truncate font-mono text-xs text-slate-500">
                            {textValue(subscription.source_url, "")}
                          </p>
                        </div>
                      ))}
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <EmptyPanel>
                没有拿到订阅源列表。FastAPI 地址：
                <span className="font-mono"> {getCollectorApiBaseUrl()}</span>
                {collections.ok ? "" : `；错误：${shortError(collections.error)}`}
              </EmptyPanel>
            )}
          </div>

          <div className="grid gap-5">
            <section>
              <SectionTitle eyebrow="Status" title="后端状态" />
              <article className="rounded-lg border border-white/10 bg-white/[0.045] p-4 shadow-2xl shadow-black/15 backdrop-blur">
                <div className="flex items-center justify-between gap-3">
                  <h3 className="text-base font-semibold">FastAPI 控制层</h3>
                  <StatusPill tone={status.data.overall_status_tone ?? mode}>
                    {textValue(status.data.overall_status_label, mode)}
                  </StatusPill>
                </div>
                <div className="mt-4 space-y-3">
                  {(status.data.checks ?? []).slice(0, 4).map((check) => (
                    <div key={check.id ?? check.title} className="rounded border border-white/10 bg-white/[0.025] p-3">
                      <p className="text-sm font-semibold">{textValue(check.title, "检查项")}</p>
                      <p className="mt-1 text-sm leading-6 text-slate-400">
                        {textValue(check.summary, "暂无摘要")}
                      </p>
                    </div>
                  ))}
                </div>
              </article>
            </section>

            <section>
              <SectionTitle eyebrow="Recent" title="手动提交历史" />
              <article className="rounded-lg border border-white/10 bg-white/[0.045] p-4 shadow-2xl shadow-black/15 backdrop-blur">
                {recentSubmissions.length ? (
                  <div className="space-y-3">
                    {recentSubmissions.slice(0, 4).map((submission) => (
                      <div
                        key={submission.id ?? submission.request_url ?? submission.url}
                        className="rounded border border-white/10 bg-white/[0.025] p-3"
                      >
                        <p className="truncate text-sm font-medium">
                          {textValue(
                            submission.title || submission.request_url || submission.url,
                            "未命名提交",
                          )}
                        </p>
                        <p className="mt-1 font-mono text-xs text-slate-500">
                          {textValue(submission.status, "unknown")}
                        </p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm leading-6 text-slate-400">
                    暂无可展示的提交历史。
                  </p>
                )}
              </article>
            </section>
          </div>
        </section>

        <section>
          <SectionTitle eyebrow="RSS" title="最近一轮轮询" />
          <article className="rounded-lg border border-white/10 bg-white/[0.045] p-4 shadow-2xl shadow-black/15 backdrop-blur">
            <div className="grid gap-3 sm:grid-cols-4">
              <StatCard
                label="订阅源"
                value={numberValue(rssPoll.data.sources?.length)}
                detail="本轮摘要中出现的 source 数。"
              />
              <StatCard
                label="写入"
                value={numberValue(
                  rssPoll.data.sources?.reduce(
                    (total, source) => total + numberValue(source.wrote_count),
                    0,
                  ),
                )}
                detail="本轮写入 Obsidian 的数量。"
              />
              <StatCard
                label="新增"
                value={numberValue(
                  rssPoll.data.sources?.reduce(
                    (total, source) => total + numberValue(source.new_item_count),
                    0,
                  ),
                )}
                detail="本轮识别到的新 item。"
              />
              <StatCard
                label="Qdrant"
                value={numberValue(
                  rssPoll.data.sources?.reduce(
                    (total, source) => total + numberValue(source.qdrant_commit_count),
                    0,
                  ),
                )}
                detail="本轮向量提交计数。"
              />
            </div>
          </article>
        </section>
      </div>
    </AppShell>
  );
}
