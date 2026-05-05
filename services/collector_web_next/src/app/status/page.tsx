import { AppShell } from "@/components/app-shell";
import { EmptyPanel, SectionTitle, StatCard, StatusPill } from "@/components/ui";
import { getCollectorApiBaseUrl, getServiceStatus } from "@/lib/collector-api";
import { numberValue, shortError, textValue } from "@/lib/view-model";

export default async function StatusPage() {
  const status = await getServiceStatus();
  const checks = status.data.checks ?? [];
  const mainline = status.data.mainline_llm ?? {};
  const rssPoll = status.data.rss_poll ?? {};

  return (
    <AppShell>
      <div className="grid gap-6">
        <SectionTitle eyebrow="Runtime" title="服务状态">
          <StatusPill tone={status.data.overall_status_tone}>
            {textValue(status.data.overall_status_label, status.ok ? "正常" : "离线")}
          </StatusPill>
        </SectionTitle>

        {!status.ok && (
          <EmptyPanel>
            当前没有连接到 FastAPI：
            <span className="font-mono"> {getCollectorApiBaseUrl()}</span>
            <span>；错误：{shortError(status.error)}</span>
          </EmptyPanel>
        )}

        <section className="grid gap-4 md:grid-cols-4">
          <StatCard
            label="检查项"
            value={checks.length}
            detail="FastAPI 返回的运行检查数量。"
          />
          <StatCard
            label="RSS 写入"
            value={numberValue(rssPoll.wrote_count)}
            detail="最近一轮 RSS 写入数量。"
          />
          <StatCard
            label="RSS 源"
            value={numberValue(rssPoll.source_count)}
            detail="最近一轮检查的订阅源数量。"
          />
          <StatCard
            label="RSS 错误"
            value={numberValue(rssPoll.error_count)}
            detail="最近一轮出现错误的源数量。"
          />
        </section>

        <section className="grid gap-5 lg:grid-cols-[1.1fr_0.9fr]">
          <div>
            <SectionTitle eyebrow="Checks" title="运行检查" />
            <div className="grid gap-3">
              {checks.length ? (
                checks.map((check) => (
                  <article
                    key={check.id ?? check.title}
                    className="rounded-lg border border-white/10 bg-white/[0.045] p-4 shadow-2xl shadow-black/15 backdrop-blur"
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <h3 className="text-base font-semibold">
                          {textValue(check.title, "检查项")}
                        </h3>
                        <p className="mt-2 text-sm leading-6 text-slate-400">
                          {textValue(check.summary, "暂无摘要")}
                        </p>
                      </div>
                      <StatusPill tone={check.status_tone}>
                        {textValue(check.status_label, "unknown")}
                      </StatusPill>
                    </div>
                    {!!check.detail_lines?.length && (
                      <ul className="mt-4 grid gap-2">
                        {check.detail_lines.slice(0, 4).map((line) => (
                          <li
                            key={line}
                            className="rounded border border-white/10 bg-white/[0.035] px-3 py-2 font-mono text-xs text-slate-400"
                          >
                            {line}
                          </li>
                        ))}
                      </ul>
                    )}
                  </article>
                ))
              ) : (
                <EmptyPanel>暂无服务检查数据。</EmptyPanel>
              )}
            </div>
          </div>

          <div>
            <SectionTitle eyebrow="Mainline" title="主链模型状态" />
            <article className="rounded-lg border border-white/10 bg-white/[0.045] p-4 shadow-2xl shadow-black/15 backdrop-blur">
              <div className="grid gap-3">
                <KeyValue label="配置模型" value={mainline.configured_model} />
                <KeyValue label="运行模型" value={mainline.live_model} />
                <KeyValue label="配置 reasoning" value={mainline.configured_reasoning_effort} />
                <KeyValue label="运行 reasoning" value={mainline.live_reasoning_effort} />
                <KeyValue label="配置 thinking" value={mainline.configured_thinking_type} />
                <KeyValue label="运行 thinking" value={mainline.live_thinking_type} />
              </div>
            </article>
          </div>
        </section>
      </div>
    </AppShell>
  );
}

function KeyValue({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="rounded border border-white/10 bg-white/[0.035] p-3">
      <p className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-500">
        {label}
      </p>
      <p className="mt-1 break-words font-mono text-sm text-slate-200">
        {textValue(value, "无数据")}
      </p>
    </div>
  );
}
