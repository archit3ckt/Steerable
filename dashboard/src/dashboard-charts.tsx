"use client";

import { ArrowDown, ArrowUp, Check } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import type { CellValue, DashboardWidget, DashboardWidgetData, MessageChart } from "./backend/types";
import { PERIOD_WORDS, bucketLabel, bucketTitle, formatValue, niceMax, tableHref } from "./dashboard-format";
import { cx } from "./ui";

/** A dashboard's widget, or a chart in a message (no table when a routine gave its own figures). */
type Shown = DashboardWidget | MessageChart;

/**
 * What a dashboard widget shows. Mostly one series, so the accent marks it and the title names it (no
 * legend); "this vs last" adds the period before in a quiet gray, with a legend. Every value is also
 * reachable without hovering: labels, the table it opens, or the grid.
 */
export function WidgetBody({ widget }: { widget: Shown }) {
  const data = widget.data ?? {};
  switch (widget.type) {
    case "number":
      return <NumberTile widget={widget} data={data} />;
    case "progress":
      return <Progress data={data} />;
    case "bars":
      return <Bars widget={widget} data={data} />;
    case "trend":
      return <Trend widget={widget} data={data} />;
    case "funnel":
      return <Funnel widget={widget} data={data} />;
    case "pace":
      return <Pace widget={widget} data={data} />;
    default:
      return widget.table ? <Rows widget={{ ...widget, table: widget.table }} data={data} /> : null;
  }
}

function NumberTile({ widget, data }: { widget: Shown; data: DashboardWidgetData }) {
  const words = widget.period ? PERIOD_WORDS[widget.period] : null;
  const change = data.previous !== undefined && data.value !== null && data.value !== undefined && data.previous !== null ? data.value - data.previous : null;
  return (
    <div>
      <p className="text-4xl font-semibold tracking-tight text-ink">{formatValue(data.value, data.unit, true)}</p>
      {words && (
        <p className="mt-1.5 flex flex-wrap items-center gap-x-1.5 text-sm text-ink-3">
          <span>{words[0]}</span>
          {change !== null && (
            <>
              <span aria-hidden>·</span>
              {change === 0 ? (
                <span>same as {words[1]}</span>
              ) : (
                <span className="inline-flex items-center gap-0.5">
                  {change > 0 ? <ArrowUp className="size-3.5" aria-label="up" /> : <ArrowDown className="size-3.5" aria-label="down" />}
                  {formatValue(Math.abs(change), data.unit, true)} vs {words[1]}
                </span>
              )}
            </>
          )}
        </p>
      )}
    </div>
  );
}

function Progress({ data }: { data: DashboardWidgetData }) {
  const value = data.value ?? 0;
  const goal = data.goal ?? 1;
  const share = Math.max(0, Math.min(value / goal, 1));
  const done = value >= goal;
  return (
    <div>
      <p className="flex items-baseline gap-1.5">
        <span className="text-4xl font-semibold tracking-tight text-ink">{formatValue(data.value, data.unit, true)}</span>
        <span className="text-ink-3">of {formatValue(goal, data.unit, true)}</span>
      </p>
      <div
        className="mt-3 h-2.5 overflow-hidden rounded-full bg-accent-soft"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={goal}
        aria-valuenow={value}
        aria-label="Progress to the goal"
      >
        <div className="h-full rounded-full bg-accent" style={{ width: `${share * 100}%` }} />
      </div>
      <p className="mt-1.5 flex items-center gap-1 text-sm text-ink-3">
        {done ? (
          <>
            <Check className="size-3.5" aria-hidden /> Goal reached
          </>
        ) : (
          `${Math.round(share * 100)}% there`
        )}
      </p>
    </div>
  );
}

const BAR_ROW = "grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] items-center gap-3 rounded-lg px-2 py-1.5 sm:grid-cols-[minmax(0,11rem)_minmax(0,1fr)]";

function Bars({ widget, data }: { widget: Shown; data: DashboardWidgetData }) {
  const items = data.items ?? [];
  if (!items.length) return <NoRows />;
  const words = widget.period && items.some((i) => i.previous !== undefined) ? PERIOD_WORDS[widget.period] : null;
  const max = Math.max(...items.map((i) => Math.max(i.value ?? 0, words ? (i.previous ?? 0) : 0)), 0) || 1;
  const by = data.by ?? widget.by ?? "";
  const table = widget.table;
  return (
    <div>
      {words && <Legend keys={[{ label: capital(words[0]), className: "bg-accent" }, { label: capital(words[1]), className: "bg-chart-previous" }]} />}
      <ul className="-mx-2 space-y-0.5">
        {items.map((item, i) => {
          const bar = (
            <>
              <span className="truncate text-sm text-ink-2 group-hover:text-ink" dir="auto">
                {item.label}
              </span>
              {words ? (
                <span className="flex min-w-0 flex-col gap-0.5">
                  <BarLine value={item.value} max={max} unit={data.unit} className="h-3.5 bg-accent" />
                  <BarLine value={item.previous ?? null} max={max} unit={data.unit} className="h-2.5 bg-chart-previous" muted />
                </span>
              ) : (
                <BarLine value={item.value} max={max} unit={data.unit} className="h-5 bg-accent" />
              )}
            </>
          );
          return (
            <li key={`${item.label}-${item.filter ?? i}`}>
              {table && item.filter !== undefined ? (
                <Link
                  href={tableHref(table, { ...widget.where, [by]: item.filter })}
                  title={`${item.label}: ${formatValue(item.value, data.unit)}${words ? `, ${words[1]} ${formatValue(item.previous ?? null, data.unit)}` : ""}. Open these rows`}
                  className={cx("group transition-colors hover:bg-surface-2", BAR_ROW)}
                >
                  {bar}
                </Link>
              ) : (
                <div className={BAR_ROW} title={`${item.label}: ${formatValue(item.value, data.unit)}${words ? `, ${words[1]} ${formatValue(item.previous ?? null, data.unit)}` : ""}`}>
                  {bar}
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {data.more ? (
        table ? (
          <Link href={tableHref(table, widget.where)} className="mt-2 inline-block text-sm text-ink-3 hover:text-ink">
            and {data.more} more
          </Link>
        ) : (
          <p className="mt-2 text-sm text-ink-3">and {data.more} more</p>
        )
      ) : null}
    </div>
  );
}

const capital = (text: string) => text[0].toUpperCase() + text.slice(1);

/** One bar from the baseline with its value at the tip (text in ink, never the bar's color). */
function BarLine({ value, max, unit, className, muted }: { value: number | null; max: number; unit?: string; className: string; muted?: boolean }) {
  return (
    <span className="flex min-w-0 items-center gap-2">
      <span
        className={cx("min-w-0.5 shrink-0 rounded-r-[4px] transition-opacity group-hover:opacity-80", className)}
        style={{ width: `calc((100% - 4.5rem) * ${Math.max(value ?? 0, 0) / max})` }}
      />
      <span className={cx("tabular-nums", muted ? "text-xs text-ink-3" : "text-sm text-ink-2")}>{formatValue(value, unit, true)}</span>
    </span>
  );
}

/** The key for a chart with two series: a swatch (or a line) beside each name, in ink. */
function Legend({ keys }: { keys: { label: string; className: string; line?: "solid" | "dashed" }[] }) {
  return (
    <p className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-3">
      {keys.map((k) => (
        <span key={k.label} className="inline-flex items-center gap-1.5">
          {k.line ? (
            <span className={cx("w-4 border-t-2", k.className, k.line === "dashed" && "border-dashed")} aria-hidden />
          ) : (
            <span className={cx("size-2.5 rounded-[3px]", k.className)} aria-hidden />
          )}
          {k.label}
        </span>
      ))}
    </p>
  );
}

/**
 * A funnel: a status column's stages in order, each counting the rows that reached it (at it or past
 * it), with the share that moved on from the stage before. Rows in other statuses (like Lost) are
 * listed under it rather than guessed into a stage.
 */
function Funnel({ widget, data }: { widget: Shown; data: DashboardWidgetData }) {
  const items = data.items ?? [];
  if (!items.length || !(items[0].value ?? 0)) return <NoRows />;
  const first = items[0].value ?? 1;
  const by = data.by ?? widget.by ?? "";
  const table = widget.table;
  const pct = (a: number | null, b: number | null) => (b ? `${Math.round(((a ?? 0) / b) * 100)}%` : "–");
  return (
    <div>
      <ol className="-mx-2">
        {items.map((item, i) => {
          const row = (
            <>
              <span className="truncate text-sm text-ink-2 group-hover:text-ink" dir="auto">
                {item.label}
              </span>
              <BarLine value={item.value} max={first} unit={data.unit} className="h-5 bg-accent" />
            </>
          );
          const title = `${item.label}: ${formatValue(item.value, data.unit)} reached it${item.now !== undefined ? `, ${formatValue(item.now, data.unit)} here now` : ""}`;
          return (
            <li key={item.label}>
              {i > 0 && (
                <p className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] gap-3 px-2 text-xs text-ink-3 sm:grid-cols-[minmax(0,11rem)_minmax(0,1fr)]">
                  <span />
                  <span>
                    <ArrowDown className="mr-0.5 inline size-3" aria-hidden />
                    {pct(item.value, items[i - 1].value)} moved on
                  </span>
                </p>
              )}
              {table && item.filter !== undefined ? (
                <Link href={tableHref(table, { ...widget.where, [by]: item.filter })} title={`${title}. Open the rows here now`} className={cx("group transition-colors hover:bg-surface-2", BAR_ROW)}>
                  {row}
                </Link>
              ) : (
                <div className={BAR_ROW} title={title}>
                  {row}
                </div>
              )}
            </li>
          );
        })}
      </ol>
      <p className="mt-2 text-sm text-ink-3">
        {pct(items[items.length - 1].value, first)} of {formatValue(first, data.unit)} made it to {items[items.length - 1].label}
        {(data.outside ?? []).length > 0 && (
          <>
            {" · not in the funnel: "}
            {(data.outside ?? []).map((o, i) => (
              <span key={o.label}>
                {i > 0 && ", "}
                {table ? (
                  <Link href={tableHref(table, { ...widget.where, [by]: o.filter })} className="hover:text-ink hover:underline">
                    {o.label} {formatValue(o.value, data.unit)}
                  </Link>
                ) : (
                  `${o.label} ${formatValue(o.value, data.unit)}`
                )}
              </span>
            ))}
          </>
        )}
      </p>
    </div>
  );
}

/**
 * Pace: the running total through this period (accent) against the same point in the one before
 * (gray, dashed), with the goal as a hairline. One axis; hovering a day or week shows both totals.
 */
function Pace({ widget, data }: { widget: Shown; data: DashboardWidgetData }) {
  const points = data.points ?? [];
  const every = data.every ?? "week";
  const [active, setActive] = useState<number | null>(null);
  if (points.length < 2) return <NoRows />;
  const words = PERIOD_WORDS[widget.period ?? "year"];
  const reached = points.reduce((last, p, i) => (p.value !== null ? i : last), -1);
  const top = niceMax(Math.max(...points.map((p) => Math.max(p.value ?? 0, p.previous ?? 0)), data.goal ?? 0));
  const n = points.length - 1;
  const x = (i: number) => ((i + 0.5) / points.length) * 100; // the middle of its hover column
  const y = (v: number) => 100 - (Math.max(v, 0) / top) * 100;
  const line = (values: (number | null | undefined)[]) =>
    values.flatMap((v, i) => (v === null || v === undefined ? [] : [`${x(i)},${y(v)}`])).join(" ");
  const shown = active ?? Math.max(reached, 0);
  const now = points[shown];
  const labelled = new Set([0, Math.floor(n / 2), n]);
  const when = (start: string) => (every === "week" ? `the week of ${bucketLabel(start, "day")}` : bucketTitle(start, "day"));
  return (
    <div>
      <p className="mb-1 flex flex-wrap items-baseline gap-x-2 text-sm text-ink-3">
        <span className="text-2xl font-semibold text-ink">{formatValue(now.value ?? null, data.unit, true)}</span>
        <span>
          by {when(now.start)} · {formatValue(now.previous ?? null, data.unit, true)} at this point {words[1]}
        </span>
      </p>
      <Legend
        keys={[
          { label: capital(words[0]), className: "border-accent", line: "solid" },
          { label: capital(words[1]), className: "border-chart-previous", line: "dashed" },
          ...(data.goal ? [{ label: `Goal ${formatValue(data.goal, data.unit, true)}`, className: "border-ink-3", line: "solid" as const }] : []),
        ]}
      />
      <div className="flex gap-2">
        <div className="flex h-40 flex-col justify-between text-right text-xs text-ink-3 tabular-nums" aria-hidden>
          <span className="-translate-y-1/2">{formatValue(top, data.unit, true)}</span>
          <span className="translate-y-1/2">0</span>
        </div>
        <div className="min-w-0 flex-1">
          <div className="relative h-40 border-t border-b border-line" onMouseLeave={() => setActive(null)}>
            {data.goal ? <div className="absolute inset-x-0 border-t border-ink-3/60" style={{ top: `${y(data.goal)}%` }} aria-hidden /> : null}
            <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 size-full overflow-visible" aria-hidden>
              <polyline points={line(points.map((p) => p.previous))} fill="none" className="stroke-chart-previous" strokeWidth={2} strokeDasharray="5 4" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
              <polyline points={line(points.map((p) => p.value))} fill="none" className="stroke-accent" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
            </svg>
            {active !== null && <div className="absolute inset-y-0 border-l border-line" style={{ left: `${x(active)}%` }} aria-hidden />}
            {now.value !== null && (
              <span
                className="absolute size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-accent ring-2 ring-surface"
                style={{ left: `${x(shown)}%`, top: `${y(now.value)}%` }}
                aria-hidden
              />
            )}
            <div className="absolute inset-0 flex">
              {points.map((p, i) => (
                <button
                  key={p.start}
                  type="button"
                  onMouseEnter={() => setActive(i)}
                  onFocus={() => setActive(i)}
                  onBlur={() => setActive(null)}
                  aria-label={`${when(p.start)}: ${p.value === null ? "still to come" : formatValue(p.value, data.unit)}, ${words[1]} ${formatValue(p.previous ?? null, data.unit)}`}
                  className="h-full min-w-0 flex-1 outline-none focus-visible:bg-accent-soft/40"
                />
              ))}
            </div>
          </div>
          <div className="relative mt-1.5 h-4 text-xs whitespace-nowrap text-ink-3" aria-hidden>
            {[...labelled].map((i) => (
              <span
                key={i}
                className={cx("absolute", i === 0 ? "left-0" : i === n ? "right-0" : "-translate-x-1/2")}
                style={i === 0 || i === n ? undefined : { left: `${x(i)}%` }}
              >
                {bucketLabel(points[i].start, every)}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function Trend({ widget, data }: { widget: Shown; data: DashboardWidgetData }) {
  const points = data.points ?? [];
  const every = widget.every ?? "week";
  const [active, setActive] = useState<number | null>(null);
  if (!points.length) return <NoRows />;
  const top = niceMax(Math.max(...points.map((p) => p.value ?? 0)));
  const last = points.length - 1;
  const shown = active ?? last;
  const labelled = new Set([0, Math.floor(last / 2), last]);
  return (
    <div>
      <p className="mb-3 flex items-baseline gap-2 text-sm text-ink-3">
        <span className="text-2xl font-semibold text-ink">{formatValue(points[shown].value, data.unit, true)}</span>
        <span>{bucketTitle(points[shown].start, every)}</span>
      </p>
      <div className="flex gap-2">
        <div className="flex h-40 flex-col justify-between py-0 text-right text-xs text-ink-3 tabular-nums" aria-hidden>
          <span className="-translate-y-1/2">{formatValue(top, data.unit, true)}</span>
          <span className="translate-y-1/2">0</span>
        </div>
        <div className="min-w-0 flex-1">
          <div className="relative flex h-40 items-end gap-0.5 border-t border-b border-line" onMouseLeave={() => setActive(null)}>
            {points.map((p, i) => (
              <button
                key={p.start}
                type="button"
                onMouseEnter={() => setActive(i)}
                onFocus={() => setActive(i)}
                onBlur={() => setActive(null)}
                aria-label={`${bucketTitle(p.start, every)}: ${formatValue(p.value, data.unit)}`}
                className="group flex h-full min-w-0 flex-1 items-end justify-center outline-none"
              >
                <span
                  className={cx(
                    "w-full max-w-6 rounded-t-[4px] bg-accent transition-opacity",
                    active !== null && active !== i ? "opacity-40" : "",
                    "group-focus-visible:ring-2 group-focus-visible:ring-accent group-focus-visible:ring-offset-2 group-focus-visible:ring-offset-surface",
                  )}
                  style={{ height: `${Math.max((p.value ?? 0) / top, 0) * 100}%`, minHeight: p.value ? 2 : 0 }}
                />
              </button>
            ))}
          </div>
          <div className="mt-1.5 flex gap-0.5 text-xs text-ink-3" aria-hidden>
            {points.map((p, i) => (
              <span key={p.start} className={cx("min-w-0 flex-1 text-center whitespace-nowrap", i === last ? "text-right" : i === 0 ? "text-left" : "")}>
                {labelled.has(i) ? bucketLabel(p.start, every) : ""}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function cell(value: CellValue | undefined, type: string, unit: string | undefined, related: Record<string, string>): string {
  if (value === null || value === undefined || value === "") return "";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "boolean") return value ? "Yes" : "";
  if (typeof value === "number") return formatValue(value, unit);
  if (type === "relation") return related[value] ?? "";
  if (type === "date") return bucketTitle(value, "day");
  if (type === "link") return value.replace(/^https?:\/\/(www\.)?/, "");
  return value;
}

function Rows({ widget, data }: { widget: Shown & { table: string }; data: DashboardWidgetData }) {
  const rows = data.rows ?? [];
  const columns = data.columns ?? [];
  if (!rows.length) return <NoRows />;
  return (
    <div className="-mx-2 overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-ink-3">
            {columns.map((c) => (
              <th key={c.name} scope="col" className={cx("px-2 pb-2 font-medium", c.type === "number" && "text-right")}>
                {c.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {rows.map((r) => (
            <tr key={r.id} className="hover:bg-surface-2">
              {columns.map((c, i) => (
                <td key={c.name} className={cx("max-w-64 truncate px-2 py-2", c.type === "number" ? "text-right tabular-nums" : "", i === 0 ? "text-ink" : "text-ink-2")} dir="auto">
                  {i === 0 ? (
                    <Link href={tableHref(widget.table, {}, r.id)} className="hover:underline">
                      {cell(r.cells[c.name], c.type, c.unit, data.related ?? {}) || "(no name)"}
                    </Link>
                  ) : (
                    cell(r.cells[c.name], c.type, c.unit, data.related ?? {})
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {data.total !== undefined && data.total > rows.length && (
        <Link href={tableHref(widget.table, widget.where)} className="mt-2 inline-block px-2 text-sm text-ink-3 hover:text-ink">
          {rows.length} of {data.total.toLocaleString("en-US")} · see all
        </Link>
      )}
    </div>
  );
}

function NoRows() {
  return <p className="py-4 text-sm text-ink-3">No rows to count yet.</p>;
}
