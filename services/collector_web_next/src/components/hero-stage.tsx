"use client";

import { useRef } from "react";
import type { ElementType } from "react";
import { motion, useScroll, useTransform } from "framer-motion";
import { Boxes, GitBranch, ShieldCheck } from "lucide-react";

import { GooeyText } from "@/components/gooey-text";

type TokenUsage = {
  totalTokens: number;
  inputTokens: number;
  outputTokens: number;
  calls: number;
  usageMissing: number;
  hasData: boolean;
};

type TokenHistoryPoint = {
  date: string;
  label: string;
  totalTokens: number;
};

export function HeroStage({
  apiMode,
  subscriptionCount,
  activeCount,
  tokenUsage,
  tokenHistory,
}: {
  apiMode: "live" | "offline";
  subscriptionCount: number;
  activeCount: number;
  tokenUsage: TokenUsage;
  tokenHistory?: TokenHistoryPoint[];
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({
    target: containerRef,
    offset: ["start start", "end start"],
  });

  const rotateX = useTransform(scrollYProgress, [0, 1], [14, 0]);
  const scale = useTransform(scrollYProgress, [0, 1], [0.96, 1]);
  const translateY = useTransform(scrollYProgress, [0, 1], [0, -42]);

  return (
    <section ref={containerRef} className="relative grid gap-5">
      <motion.div
        style={{ y: translateY }}
        className="relative overflow-hidden rounded-lg border border-emerald-300/20 bg-slate-950/68 p-6 text-white shadow-2xl shadow-emerald-950/20 backdrop-blur-sm"
      >
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_18%_18%,rgba(16,185,129,0.24),transparent_32%),linear-gradient(135deg,rgba(2,6,23,0.46),rgba(2,6,23,0.88))]" />
        <div className="relative z-10">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded border border-emerald-300/40 bg-emerald-300/10 px-2.5 py-1 text-xs font-semibold text-emerald-100">
              Next Frontend Lab
            </span>
            <span className="rounded border border-white/15 bg-white/10 px-2.5 py-1 text-xs font-semibold text-stone-100">
              {apiMode === "live" ? "FastAPI 已连接" : "FastAPI 离线态"}
            </span>
          </div>
          <h2 className="mt-5 max-w-xl text-4xl font-semibold leading-tight tracking-normal text-white">
            <span className="block">用现代组件方式重画</span>
            <span className="sr-only"> Collector Web</span>
            <GooeyText
              texts={["Collector Web"]}
              morphTime={0.55}
              cooldownTime={2.1}
              className="mt-1 h-[3.4rem] sm:h-[4rem]"
              textClassName="text-left text-4xl font-semibold leading-tight text-cyan-100 drop-shadow-[0_0_18px_rgba(56,189,248,0.22)]"
            />
          </h2>
          <p className="mt-4 max-w-2xl text-base leading-7 text-stone-300">
            当前版本只读取已有 FastAPI API，不执行提交、重跑、切换模型等操作。
          </p>
          <div className="mt-6 grid gap-3 sm:grid-cols-3">
            <MiniMetric label="订阅源" value={subscriptionCount} />
            <MiniMetric label="启用中" value={activeCount} />
            <MiniMetric label="交互按钮" value="0" />
          </div>
        </div>
      </motion.div>

      <div className="min-h-[28rem] [perspective:1200px]">
        <motion.div
          style={{ rotateX, scale }}
          className="h-full rounded-xl border border-white/10 bg-black p-2 shadow-2xl shadow-emerald-950/30"
        >
          <div className="grid h-full overflow-hidden rounded-lg border border-white/10 bg-slate-950 p-4">
            <div className="flex items-center justify-between border-b border-white/10 pb-3">
              <div>
                <p className="text-xs font-bold uppercase tracking-[0.18em] text-slate-500">
                  Runtime Surface
                </p>
                <h3 className="text-lg font-semibold text-white">Read-only cockpit</h3>
              </div>
              <div className="flex gap-1.5">
                <span className="h-2.5 w-2.5 rounded-full bg-rose-400" />
                <span className="h-2.5 w-2.5 rounded-full bg-amber-400" />
                <span className="h-2.5 w-2.5 rounded-full bg-emerald-500" />
              </div>
            </div>
            <div className="grid gap-3 py-4 md:grid-cols-3">
              <PreviewTile
                icon={Boxes}
                label="Total tokens"
                value={formatTokenNumber(tokenUsage.totalTokens)}
              />
              <PreviewTile
                icon={ShieldCheck}
                label="Input tokens"
                value={formatTokenNumber(tokenUsage.inputTokens)}
              />
              <PreviewTile
                icon={GitBranch}
                label="Output tokens"
                value={formatTokenNumber(tokenUsage.outputTokens)}
              />
            </div>
            <TokenUsageChart tokenUsage={tokenUsage} tokenHistory={tokenHistory} />
          </div>
        </motion.div>
      </div>
    </section>
  );
}

function MiniMetric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-white/15 bg-white/10 p-3 backdrop-blur-sm">
      <p className="text-xs font-medium text-stone-300">{label}</p>
      <strong className="mt-1 block font-mono text-2xl font-semibold tracking-normal text-white">
        {value}
      </strong>
    </div>
  );
}

function PreviewTile({
  icon: Icon,
  label,
  value,
}: {
  icon: ElementType;
  label: string;
  value: string | number;
}) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.045] p-3">
      <Icon className="h-4 w-4 text-emerald-300" />
      <p className="mt-3 text-xs font-semibold uppercase tracking-[0.12em] text-slate-400">
        {label}
      </p>
      <strong className="mt-1 block truncate font-mono text-xl font-semibold tracking-normal text-white">
        {value}
      </strong>
    </div>
  );
}

function TokenUsageChart({
  tokenUsage,
  tokenHistory,
}: {
  tokenUsage: TokenUsage;
  tokenHistory?: TokenHistoryPoint[];
}) {
  const history = tokenHistory ?? [];
  const points =
    history.length > 0
      ? history
      : [{ date: "latest", label: "Today", totalTokens: tokenUsage.totalTokens }];
  const maxTotal = Math.max(...points.map((point) => point.totalTokens), 0);

  return (
    <div className="rounded-lg border border-emerald-300/15 bg-emerald-300/[0.055] p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-emerald-200/70">
          Daily total tokens
        </p>
        <span className="rounded border border-emerald-300/30 bg-emerald-300/10 px-2 py-1 text-xs font-semibold text-emerald-100">
          {tokenUsage.hasData ? "live" : "pending"}
        </span>
      </div>
      <div className="mt-4">
        <TokenLineChart points={points} maxTotal={maxTotal} />
      </div>
      <div className="mt-2 flex items-center justify-between gap-3 text-xs text-slate-400">
        <span>Days</span>
        <span className="font-mono">Total token</span>
      </div>
    </div>
  );
}

function TokenLineChart({
  points,
  maxTotal,
}: {
  points: TokenHistoryPoint[];
  maxTotal: number;
}) {
  const chartWidth = 420;
  const chartHeight = 172;
  const paddingLeft = 52;
  const paddingRight = 18;
  const paddingTop = 18;
  const paddingBottom = 34;
  const plotWidth = chartWidth - paddingLeft - paddingRight;
  const plotHeight = chartHeight - paddingTop - paddingBottom;
  const denominator = Math.max(maxTotal, 1);
  const yTicks = maxTotal > 0 ? [maxTotal, Math.round(maxTotal / 2), 0] : [0];
  const coordinates = points.map((point, index) => {
    const x =
      points.length <= 1
        ? paddingLeft + plotWidth / 2
        : paddingLeft + (plotWidth * index) / (points.length - 1);
    const y = paddingTop + plotHeight - (Math.max(point.totalTokens, 0) / denominator) * plotHeight;
    return { ...point, x, y };
  });
  const linePath = coordinates
    .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`)
    .join(" ");
  const areaPath =
    coordinates.length > 0
      ? `${linePath} L ${coordinates[coordinates.length - 1].x.toFixed(2)} ${paddingTop + plotHeight} L ${coordinates[0].x.toFixed(2)} ${paddingTop + plotHeight} Z`
      : "";

  return (
    <svg
      className="h-44 w-full overflow-visible"
      viewBox={`0 0 ${chartWidth} ${chartHeight}`}
      role="img"
      aria-label="Daily total token line chart"
    >
      <line
        x1={paddingLeft}
        x2={paddingLeft}
        y1={paddingTop}
        y2={paddingTop + plotHeight}
        stroke="rgba(148,163,184,0.34)"
        strokeWidth="1"
      />
      <line
        x1={paddingLeft}
        x2={chartWidth - paddingRight}
        y1={paddingTop + plotHeight}
        y2={paddingTop + plotHeight}
        stroke="rgba(148,163,184,0.34)"
        strokeWidth="1"
      />
      {yTicks.map((tick) => {
        const y = paddingTop + plotHeight - (tick / denominator) * plotHeight;
        return (
          <g key={`y-${tick}`}>
            <line
              x1={paddingLeft}
              x2={chartWidth - paddingRight}
              y1={y}
              y2={y}
              stroke="rgba(148,163,184,0.13)"
              strokeWidth="1"
            />
            <text
              x={paddingLeft - 10}
              y={y + 4}
              fill="rgb(148,163,184)"
              fontSize="10"
              textAnchor="end"
            >
              {formatCompactNumber(tick)}
            </text>
          </g>
        );
      })}
      {areaPath ? <path d={areaPath} fill="rgba(45,212,191,0.12)" /> : null}
      {linePath ? (
        <path
          d={linePath}
          fill="none"
          stroke="rgb(94,234,212)"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="3"
        />
      ) : null}
      {coordinates.map((point) => (
        <g key={`${point.date}-${point.x}`}>
          <circle cx={point.x} cy={point.y} r="4" fill="rgb(94,234,212)" />
          <circle cx={point.x} cy={point.y} r="7" fill="rgba(94,234,212,0.16)" />
        </g>
      ))}
      {coordinates.map((point, index) => {
        const shouldShow = index === 0 || index === coordinates.length - 1 || coordinates.length <= 6;
        return shouldShow ? (
          <text
            key={`${point.date}-label`}
            x={point.x}
            y={chartHeight - 9}
            fill="rgb(148,163,184)"
            fontSize="10"
            textAnchor="middle"
          >
            {point.label}
          </text>
        ) : null;
      })}
    </svg>
  );
}

function formatCompactNumber(value: number) {
  if (value >= 1000000) {
    return `${Math.round(value / 100000) / 10}M`;
  }
  if (value >= 1000) {
    return `${Math.round(value / 100) / 10}K`;
  }
  return formatTokenNumber(value);
}

function formatTokenNumber(value: number) {
  return new Intl.NumberFormat("en-US").format(Math.max(Math.round(value), 0));
}
