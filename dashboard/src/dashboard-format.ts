/** Numbers and dates on dashboards, the same on the server and in the browser. */
import type { MessageChart } from "./backend/types";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/** A unit like "$" or "€" goes before the number; a word like "kg" after it. */
export function withUnit(text: string, unit?: string): string {
  if (!unit) return text;
  if (/^[^\p{L}\d\s]{1,3}$/u.test(unit)) return text.startsWith("-") ? `-${unit}${text.slice(1)}` : `${unit}${text}`;
  return `${text} ${unit}`;
}

/** 1,284 · 12.5 · 0.75; `compact`: 12.9K, 4.2M for big numbers (stat tiles, axis ticks). */
export function formatValue(value: number | null | undefined, unit?: string, compact = false): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  const abs = Math.abs(value);
  const text =
    compact && abs >= 10_000
      ? value.toLocaleString("en-US", { notation: "compact", maximumFractionDigits: 1 })
      : value.toLocaleString("en-US", { maximumFractionDigits: abs < 10 ? 2 : abs < 1000 ? 1 : 0 });
  return withUnit(text, unit);
}

function parts(day: string): { y: number; m: number; d: number; weekday: number } {
  const [y, m, d] = day.slice(0, 10).split("-").map(Number);
  return { y, m, d, weekday: new Date(Date.UTC(y, m - 1, d)).getUTCDay() };
}

/** A trend's bar under the axis: "Oct 13" for a day or week, "Oct" for a month. */
export function bucketLabel(start: string, every: "day" | "week" | "month"): string {
  const { m, d } = parts(start);
  return every === "month" ? MONTHS[m - 1] : `${MONTHS[m - 1]} ${d}`;
}

/** The same bar, in full: "Thu, Oct 15", "Week of Oct 13", "October 2026". */
export function bucketTitle(start: string, every: "day" | "week" | "month"): string {
  const { y, m, d, weekday } = parts(start);
  if (every === "month") return `${MONTH_NAMES[m - 1]} ${y}`;
  if (every === "week") return `Week of ${MONTHS[m - 1]} ${d}`;
  return `${DAYS[weekday]}, ${MONTHS[m - 1]} ${d}`;
}

export const PERIOD_WORDS: Record<string, [string, string]> = {
  week: ["this week", "last week"],
  month: ["this month", "last month"],
  quarter: ["this quarter", "last quarter"],
  year: ["this year", "last year"],
};

/** The top of a chart's scale: a round number at or above the largest value (1, 2, 2.5, 5 × 10ⁿ). */
export function niceMax(max: number): number {
  if (!(max > 0)) return 1;
  const power = 10 ** Math.floor(Math.log10(max));
  for (const step of [1, 2, 2.5, 5, 10]) if (step * power >= max) return step * power;
  return 10 * power;
}

/** A library table's address with filters on top of its view (the grid shows "Only rows where ..."). */
export function tableHref(tableId: string, where: Record<string, string> = {}, row?: string): string {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(where)) params.set(`where.${k}`, v);
  if (row) params.set("row", row);
  const qs = params.toString();
  return `/library/${encodeURIComponent(tableId)}${qs ? `?${qs}` : ""}`;
}

/** What a chart in a message shows, in one line of words (for Telegram, which can't draw it). */
export function chartWords(chart: MessageChart): string {
  const d = chart.data;
  const n = (v: number | null | undefined) => formatValue(v, d.unit);
  let says: string;
  if (chart.type === "bars") says = (d.items ?? []).map((i) => `${i.label} ${n(i.value)}`).join(", ") + (d.more ? `, and ${d.more} more` : "") || "nothing yet";
  else if (chart.type === "trend") says = (d.points ?? []).slice(-6).map((p) => `${bucketLabel(p.start, chart.every ?? "week")} ${n(p.value)}`).join(", ");
  else if (chart.type === "progress") says = `${n(d.value)} of ${n(d.goal)}`;
  else says = n(d.value) + (chart.period && d.previous !== undefined ? ` (${PERIOD_WORDS[chart.period][1]}: ${n(d.previous)})` : "");
  return `${chart.title}: ${says}`;
}
