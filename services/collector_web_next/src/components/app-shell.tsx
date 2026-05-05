import Link from "next/link";
import { Activity, DatabaseZap, Radio, SendHorizontal } from "lucide-react";

import { SparklesCore } from "@/components/sparkles-core";

const navItems = [
  { href: "/", label: "总览", icon: Activity },
  { href: "/status", label: "服务状态", icon: DatabaseZap },
  { href: "/rss-poll", label: "RSS 审计", icon: Radio },
  { href: "/manual-submit", label: "手动提交", icon: SendHorizontal },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative min-h-screen bg-slate-950 text-slate-100">
      <div className="pointer-events-none fixed inset-0 z-0 bg-[radial-gradient(circle_at_16%_12%,rgba(16,185,129,0.13),transparent_30%),radial-gradient(circle_at_84%_8%,rgba(59,130,246,0.12),transparent_28%),linear-gradient(180deg,#020617,#030712_34%,#050816)]" />
      <div aria-hidden="true" className="pointer-events-none fixed inset-0 z-0 opacity-[0.38]">
        <SparklesCore
          id="collector-page-sparkles"
          background="transparent"
          className="absolute inset-0"
          maxSize={1.35}
          minSize={0.3}
          particleColor="#8ff8d2"
          particleDensity={52}
          speed={1.8}
        />
      </div>
      <header className="sticky top-0 z-30 border-b border-white/10 bg-slate-950/78 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
          <Link href="/" className="min-w-0">
            <p className="text-[0.68rem] font-bold uppercase tracking-[0.18em] text-emerald-300">
              Signal to Obsidian
            </p>
            <h1 className="truncate text-lg font-semibold tracking-normal text-white">
              Collector Web Next
            </h1>
          </Link>
          <nav className="flex shrink-0 gap-1 rounded-md border border-white/10 bg-white/5 p-1 shadow-2xl shadow-black/20">
            {navItems.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className="inline-flex h-9 items-center gap-2 rounded px-3 text-sm font-medium text-slate-300 transition hover:bg-white/10 hover:text-white"
              >
                <item.icon className="h-4 w-4" aria-hidden="true" />
                <span className="hidden sm:inline">{item.label}</span>
              </Link>
            ))}
          </nav>
        </div>
      </header>
      <main className="relative z-10 mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:py-8">
        {children}
      </main>
    </div>
  );
}
