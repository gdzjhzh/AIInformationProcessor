import { AlertTriangle, CheckCircle2, CircleDashed } from "lucide-react";

import { statusToneClass } from "@/lib/view-model";

export function StatusPill({
  tone,
  children,
}: {
  tone?: string;
  children: React.ReactNode;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded border px-2.5 py-1 text-xs font-semibold ${statusToneClass(
        tone,
      )}`}
    >
      {tone === "success" || tone === "live" ? (
        <CheckCircle2 className="h-3.5 w-3.5" />
      ) : tone === "error" || tone === "warning" ? (
        <AlertTriangle className="h-3.5 w-3.5" />
      ) : (
        <CircleDashed className="h-3.5 w-3.5" />
      )}
      {children}
    </span>
  );
}

export function StatCard({
  label,
  value,
  detail,
}: {
  label: string;
  value: string | number;
  detail: string;
}) {
  return (
    <article className="rounded-lg border border-stone-200 bg-white p-4 shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.14em] text-stone-500">
        {label}
      </p>
      <strong className="mt-3 block font-mono text-3xl font-semibold tracking-normal text-stone-950">
        {value}
      </strong>
      <p className="mt-2 text-sm leading-6 text-stone-600">{detail}</p>
    </article>
  );
}

export function SectionTitle({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string;
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
      <div>
        <p className="text-xs font-bold uppercase tracking-[0.18em] text-emerald-700">
          {eyebrow}
        </p>
        <h2 className="mt-1 text-2xl font-semibold tracking-normal text-stone-950">
          {title}
        </h2>
      </div>
      {children}
    </div>
  );
}

export function EmptyPanel({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-stone-300 bg-white/70 p-5 text-sm leading-6 text-stone-600">
      {children}
    </div>
  );
}
