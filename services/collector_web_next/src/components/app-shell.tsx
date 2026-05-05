import Link from "next/link";
import { Activity, DatabaseZap, Radio, SendHorizontal } from "lucide-react";

const navItems = [
  { href: "/", label: "总览", icon: Activity },
  { href: "/status", label: "服务状态", icon: DatabaseZap },
  { href: "/rss-poll", label: "RSS 审计", icon: Radio },
  { href: "/manual-submit", label: "手动提交", icon: SendHorizontal },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-[#f6f6f2] text-stone-950">
      <header className="sticky top-0 z-30 border-b border-stone-200/80 bg-[#f6f6f2]/90 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
          <Link href="/" className="min-w-0">
            <p className="text-[0.68rem] font-bold uppercase tracking-[0.18em] text-emerald-700">
              Signal to Obsidian
            </p>
            <h1 className="truncate text-lg font-semibold tracking-normal">
              Collector Web Next
            </h1>
          </Link>
          <nav className="flex shrink-0 gap-1 rounded-md border border-stone-200 bg-white/75 p-1 shadow-sm">
            {navItems.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className="inline-flex h-9 items-center gap-2 rounded px-3 text-sm font-medium text-stone-600 transition hover:bg-stone-100 hover:text-stone-950"
              >
                <item.icon className="h-4 w-4" aria-hidden="true" />
                <span className="hidden sm:inline">{item.label}</span>
              </Link>
            ))}
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:py-8">
        {children}
      </main>
    </div>
  );
}
