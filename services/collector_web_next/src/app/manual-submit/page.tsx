import { AppShell } from "@/components/app-shell";
import { EmptyPanel, SectionTitle, StatCard, StatusPill } from "@/components/ui";
import { getCollections, getCollectorApiBaseUrl } from "@/lib/collector-api";
import { numberValue, shortError, textValue } from "@/lib/view-model";

export default async function ManualSubmitPage() {
  const collections = await getCollections();
  const summary = collections.data.manual_submission_summary ?? {};
  const submissions = collections.data.manual_submissions ?? [];

  return (
    <AppShell>
      <div className="grid gap-6">
        <SectionTitle eyebrow="Manual Media" title="手动提交只读页">
          <StatusPill tone={collections.ok ? "live" : "muted"}>
            {collections.ok ? "实时数据" : "离线占位"}
          </StatusPill>
        </SectionTitle>

        {!collections.ok && (
          <EmptyPanel>
            当前没有连接到 FastAPI：
            <span className="font-mono"> {getCollectorApiBaseUrl()}</span>
            <span>；错误：{shortError(collections.error)}</span>
          </EmptyPanel>
        )}

        <section className="grid gap-5 lg:grid-cols-[0.92fr_1.08fr]">
          <article className="rounded-lg border border-stone-200 bg-white p-5 shadow-sm">
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-emerald-700">
              Submit Surface
            </p>
            <h2 className="mt-2 text-2xl font-semibold tracking-normal">
              保留表单外观，暂不触发真实提交
            </h2>
            <div className="mt-5 grid gap-3">
              <label className="grid gap-2">
                <span className="text-sm font-semibold text-stone-700">媒体 URL</span>
                <input
                  disabled
                  placeholder="https://example.com/media"
                  className="h-12 rounded-md border border-stone-200 bg-stone-100 px-3 text-sm text-stone-500"
                />
              </label>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="grid gap-2">
                  <span className="text-sm font-semibold text-stone-700">轮询次数</span>
                  <input
                    disabled
                    placeholder="默认"
                    className="h-12 rounded-md border border-stone-200 bg-stone-100 px-3 text-sm text-stone-500"
                  />
                </label>
                <label className="grid gap-2">
                  <span className="text-sm font-semibold text-stone-700">说话人识别</span>
                  <select
                    disabled
                    className="h-12 rounded-md border border-stone-200 bg-stone-100 px-3 text-sm text-stone-500"
                  >
                    <option>由 04_video_transcript_ingest 决定</option>
                  </select>
                </label>
              </div>
              <button
                disabled
                className="mt-2 h-12 rounded-md bg-stone-300 px-4 text-sm font-semibold text-stone-600"
              >
                提交功能暂未接入
              </button>
            </div>
          </article>

          <div className="grid gap-4 md:grid-cols-2">
            <StatCard
              label="总提交"
              value={numberValue(summary.total_count)}
              detail="FastAPI 记录的手动提交总数。"
            />
            <StatCard
              label="运行中"
              value={numberValue(summary.running_count)}
              detail="仍在处理或等待回调的提交。"
            />
            <StatCard
              label="成功"
              value={numberValue(summary.success_count)}
              detail="已完成并返回成功结果的提交。"
            />
            <StatCard
              label="失败"
              value={numberValue(summary.failed_count)}
              detail="提交或下游处理失败的记录。"
            />
          </div>
        </section>

        <section>
          <SectionTitle eyebrow="History" title="最近提交记录" />
          <div className="rounded-lg border border-stone-200 bg-white shadow-sm">
            {submissions.length ? (
              <div className="divide-y divide-stone-200">
                {submissions.map((submission) => (
                  <article key={submission.id ?? submission.url} className="p-4">
                    <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
                      <div className="min-w-0">
                        <h3 className="truncate text-base font-semibold">
                          {textValue(submission.title || submission.url, "未命名提交")}
                        </h3>
                        <p className="mt-1 break-all font-mono text-xs text-stone-500">
                          {textValue(submission.url, "")}
                        </p>
                      </div>
                      <StatusPill tone={submission.status === "success" ? "success" : "muted"}>
                        {textValue(submission.status, "unknown")}
                      </StatusPill>
                    </div>
                    <div className="mt-3 grid gap-2 sm:grid-cols-3">
                      <Meta label="创建" value={submission.created_at} />
                      <Meta label="更新" value={submission.updated_at} />
                      <Meta label="去重动作" value={submission.dedupe_action} />
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <div className="p-4">
                <EmptyPanel>暂无手动提交历史。</EmptyPanel>
              </div>
            )}
          </div>
        </section>
      </div>
    </AppShell>
  );
}

function Meta({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="rounded border border-stone-200 bg-stone-50 p-3">
      <p className="text-xs font-semibold uppercase tracking-[0.12em] text-stone-500">
        {label}
      </p>
      <p className="mt-1 break-words font-mono text-xs text-stone-800">
        {textValue(value, "无数据")}
      </p>
    </div>
  );
}
