import { AppShell } from "@/components/app-shell";
import { EmptyPanel, SectionTitle, StatCard, StatusPill } from "@/components/ui";
import { getCollectorApiBaseUrl, getLatestRssPoll } from "@/lib/collector-api";
import { numberValue, shortError, textValue } from "@/lib/view-model";

export default async function RssPollPage() {
  const poll = await getLatestRssPoll();
  const sources = poll.data.sources ?? [];

  const totals = sources.reduce(
    (acc, source) => ({
      items: acc.items + numberValue(source.item_count),
      newItems: acc.newItems + numberValue(source.new_item_count),
      wrote: acc.wrote + numberValue(source.wrote_count),
      qdrant: acc.qdrant + numberValue(source.qdrant_commit_count),
    }),
    { items: 0, newItems: 0, wrote: 0, qdrant: 0 },
  );

  return (
    <AppShell>
      <div className="grid gap-6">
        <SectionTitle eyebrow="RSS Poll" title="RSS 轮询审计">
          <StatusPill tone={poll.ok ? "live" : "muted"}>
            {poll.ok ? "实时数据" : "离线占位"}
          </StatusPill>
        </SectionTitle>

        {!poll.ok && (
          <EmptyPanel>
            当前没有连接到 FastAPI：
            <span className="font-mono"> {getCollectorApiBaseUrl()}</span>
            <span>；错误：{shortError(poll.error)}</span>
          </EmptyPanel>
        )}

        <section className="grid gap-4 md:grid-cols-4">
          <StatCard label="源数量" value={sources.length} detail="本轮摘要覆盖的订阅源。" />
          <StatCard label="Item" value={totals.items} detail="RSS 返回的 item 总数。" />
          <StatCard label="新增" value={totals.newItems} detail="通过新内容判断的 item。" />
          <StatCard label="写入" value={totals.wrote} detail="最终写入 Obsidian 的数量。" />
        </section>

        <section className="rounded-lg border border-white/10 bg-white/[0.045] shadow-2xl shadow-black/15 backdrop-blur">
          <div className="border-b border-white/10 p-4">
            <p className="text-sm font-medium text-slate-400">
              最近完成时间：
              <span className="font-mono text-white">
                {textValue(poll.data.run_finished_at, "无数据")}
              </span>
            </p>
            <p className="mt-1 break-all font-mono text-xs text-slate-500">
              {textValue(poll.data.file_path, "没有 poll_runs 文件路径")}
            </p>
          </div>

          {sources.length ? (
            <div className="divide-y divide-white/10">
              {sources.map((source, index) => (
                <article key={`${source.feed_url ?? "source"}-${index}`} className="p-4">
                  <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
                    <div className="min-w-0">
                      <h3 className="truncate text-base font-semibold">
                        {textValue(source.source_name, "未命名源")}
                      </h3>
                      <p className="mt-1 truncate font-mono text-xs text-slate-500">
                        {textValue(source.feed_url, "")}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <StatusPill tone={source.rss_status === "success" ? "success" : "muted"}>
                        RSS {textValue(source.rss_status, "unknown")}
                      </StatusPill>
                      <StatusPill tone={source.transcript_status === "success" ? "success" : "muted"}>
                        Transcript {textValue(source.transcript_status, "unknown")}
                      </StatusPill>
                    </div>
                  </div>
                  <div className="mt-4 grid gap-3 sm:grid-cols-4">
                    <Mini label="item" value={source.item_count} />
                    <Mini label="new" value={source.new_item_count} />
                    <Mini label="wrote" value={source.wrote_count} />
                    <Mini label="qdrant" value={source.qdrant_commit_count} />
                  </div>
                  {!!source.new_titles?.length && (
                    <div className="mt-4 rounded border border-emerald-400/20 bg-emerald-400/10 p-3">
                      <p className="text-xs font-semibold uppercase tracking-[0.12em] text-emerald-200">
                        New titles
                      </p>
                      <ul className="mt-2 space-y-1 text-sm text-slate-300">
                        {source.new_titles.slice(0, 3).map((title) => (
                          <li key={title} className="truncate">
                            {title}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </article>
              ))}
            </div>
          ) : (
            <div className="p-4">
              <EmptyPanel>暂无 RSS 轮询摘要。</EmptyPanel>
            </div>
          )}
        </section>
      </div>
    </AppShell>
  );
}

function Mini({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="rounded border border-white/10 bg-white/[0.035] p-3">
      <p className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-500">
        {label}
      </p>
      <p className="mt-1 font-mono text-xl font-semibold text-white">
        {numberValue(value)}
      </p>
    </div>
  );
}
