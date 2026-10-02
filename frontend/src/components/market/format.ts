import { TrendingDown, TrendingUp, MoveRight, HelpCircle } from "lucide-react";
import type { Trend } from "@/lib/api/market-client";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** 2450 -> "₹2,450" (Indian digit grouping). */
export function rupees(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `₹${Math.round(value).toLocaleString("en-IN")}`;
}

/** 4.23 -> "+4.2%", -1 -> "−1.0%". */
export function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "—";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${Math.abs(value).toFixed(digits)}%`;
}

/** "2026-09-25" -> "25 Sep 2026" (parsed by hand -- no timezone shifts). */
export function longDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

/** "2026-09-25" -> "25 Sep". */
export function shortDate(iso: string): string {
  const [, m, d] = iso.slice(0, 10).split("-").map(Number);
  return `${d} ${MONTHS[m - 1]}`;
}

export function isoDaysAgo(days: number, from = new Date()): string {
  const d = new Date(Date.UTC(from.getFullYear(), from.getMonth(), from.getDate()));
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

export function daysBetween(fromIso: string, toIso: string): number {
  return Math.round((Date.parse(toIso.slice(0, 10)) - Date.parse(fromIso.slice(0, 10))) / 86_400_000);
}

/** Trend -> text + icon + colour. The text always carries the meaning, so
 * nothing relies on colour alone. */
export const TREND_META: Record<Trend, { label: string; Icon: typeof TrendingUp; className: string }> = {
  increasing: { label: "Increasing", Icon: TrendingUp, className: "text-emerald-700 bg-emerald-50 border-emerald-200" },
  stable: { label: "Stable", Icon: MoveRight, className: "text-slate-700 bg-slate-50 border-slate-200" },
  decreasing: { label: "Decreasing", Icon: TrendingDown, className: "text-rose-700 bg-rose-50 border-rose-200" },
  insufficient_data: { label: "Not enough data", Icon: HelpCircle, className: "text-farm-muted bg-farm-gray border-farm-border-color" },
};

export function changeClass(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0) return "text-farm-dark";
  return value > 0 ? "text-emerald-700" : "text-rose-700";
}

export const MODEL_LABELS: Record<string, string> = {
  naive: "Naive (last price)",
  moving_average: "7-day moving average",
  seasonal_naive: "Seasonal naive (last year's pattern)",
  ridge: "Linear regression (ridge)",
  random_forest: "Random forest",
  lightgbm: "LightGBM (gradient-boosted trees)",
  lightgbm_huber: "LightGBM, robust loss (gradient-boosted trees)",
};
