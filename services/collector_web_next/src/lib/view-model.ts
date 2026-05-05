import type { ApiState } from "./collector-api";

export function numberValue(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

export function textValue(value: unknown, fallback = "未提供") {
  const text = String(value ?? "").trim();
  return text || fallback;
}

export function apiTone(apiStates: Array<ApiState<unknown>>) {
  return apiStates.every((state) => state.ok) ? "live" : "offline";
}

export function statusToneClass(tone?: string) {
  switch (tone) {
    case "success":
    case "live":
      return "border-emerald-400/30 bg-emerald-400/10 text-emerald-200";
    case "warning":
    case "action":
      return "border-amber-400/30 bg-amber-400/10 text-amber-200";
    case "error":
      return "border-rose-400/30 bg-rose-400/10 text-rose-200";
    case "accent":
      return "border-sky-400/30 bg-sky-400/10 text-sky-200";
    default:
      return "border-slate-500/30 bg-slate-400/10 text-slate-200";
  }
}

export function shortError(error?: string) {
  if (!error) {
    return "";
  }
  return error.length > 120 ? `${error.slice(0, 117)}...` : error;
}
