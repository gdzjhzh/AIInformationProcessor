"use client";

import { useRef } from "react";
import type { ElementType } from "react";
import { motion, useScroll, useTransform } from "framer-motion";
import { Boxes, GitBranch, ShieldCheck } from "lucide-react";

import { GooeyText } from "@/components/gooey-text";
import { SparklesCore } from "@/components/sparkles-core";

export function HeroStage({
  apiMode,
  subscriptionCount,
  activeCount,
}: {
  apiMode: "live" | "offline";
  subscriptionCount: number;
  activeCount: number;
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
    <section ref={containerRef} className="relative grid gap-5 lg:grid-cols-[0.86fr_1.14fr]">
      <motion.div
        style={{ y: translateY }}
        className="relative overflow-hidden rounded-lg border border-emerald-300/20 bg-stone-950 p-6 text-white shadow-2xl shadow-emerald-950/20"
      >
        <SparklesCore
          background="#020617"
          className="absolute inset-0"
          maxSize={1.8}
          minSize={0.4}
          particleColor="#8ff8d2"
          particleDensity={85}
          speed={2.4}
        />
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
            <span className="sr-only"> Collector Web 控制台</span>
            <GooeyText
              texts={["Collector Web 控制台", "Collector Web 审计台", "Collector Web 驾驶舱"]}
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
                <h3 className="text-lg font-semibold text-white">
                  Read-only cockpit
                </h3>
              </div>
              <div className="flex gap-1.5">
                <span className="h-2.5 w-2.5 rounded-full bg-rose-400" />
                <span className="h-2.5 w-2.5 rounded-full bg-amber-400" />
                <span className="h-2.5 w-2.5 rounded-full bg-emerald-500" />
              </div>
            </div>
            <div className="grid gap-3 py-4 md:grid-cols-3">
              <PreviewTile icon={Boxes} label="Sources" value={subscriptionCount} />
              <PreviewTile icon={ShieldCheck} label="Active" value={activeCount} />
              <PreviewTile icon={GitBranch} label="Backend" value={apiMode} />
            </div>
            <div className="grid gap-3 md:grid-cols-[1.2fr_0.8fr]">
              <div className="rounded-lg border border-white/10 bg-white/[0.045] p-4">
                <div className="mb-3 h-2 w-24 rounded-full bg-emerald-400/60" />
                <div className="space-y-2">
                  <div className="h-3 rounded-full bg-white/10" />
                  <div className="h-3 w-5/6 rounded-full bg-white/10" />
                  <div className="h-3 w-2/3 rounded-full bg-white/10" />
                </div>
              </div>
              <div className="rounded-lg border border-white/10 bg-white/[0.045] p-4">
                <div className="mb-4 flex items-end gap-2">
                  <span className="h-12 flex-1 rounded bg-sky-400/50" />
                  <span className="h-20 flex-1 rounded bg-emerald-400/70" />
                  <span className="h-9 flex-1 rounded bg-amber-300/60" />
                  <span className="h-16 flex-1 rounded bg-slate-500/60" />
                </div>
                <div className="h-3 w-20 rounded-full bg-white/10" />
              </div>
            </div>
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
