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
      return "border-emerald-200 bg-emerald-50 text-emerald-800";
    case "warning":
    case "action":
      return "border-amber-200 bg-amber-50 text-amber-800";
    case "error":
      return "border-rose-200 bg-rose-50 text-rose-800";
    case "accent":
      return "border-sky-200 bg-sky-50 text-sky-800";
    default:
      return "border-stone-200 bg-stone-100 text-stone-700";
  }
}

export function shortError(error?: string) {
  if (!error) {
    return "";
  }
  return error.length > 120 ? `${error.slice(0, 117)}...` : error;
}
