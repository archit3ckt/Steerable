"use client";

import {
  ChartCandlestick,
  ChartColumn,
  ChartBar,
  ChevronDown,
  ChevronUp,
  Ellipsis,
  Filter,
  Hash,
  ListOrdered,
  Loader2,
  Pencil,
  Plus,
  Sparkles,
  Target,
  Trash2,
  TrendingUp,
  TriangleAlert,
  X,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition, type ReactNode } from "react";
import type { DashboardAsk, DashboardDetail, DashboardSource, DashboardWidget, DashboardWidgetSpec, DashboardWidgetType } from "./backend/types";
import { WidgetBody } from "./dashboard-charts";
import { tableHref } from "./dashboard-format";
import type { DashboardActions } from "./host";
import { Menu, menuItem } from "./library-cells";
import { Markdown } from "./markdown";
import { Poll } from "./poll";
import { Card, cx } from "./ui";

export type DashboardEditActions = Pick<
  DashboardActions,
  "createDashboard" | "saveDashboard" | "removeDashboard" | "saveDashboardWidget" | "changeDashboardWidget" | "askForDashboard"
>;

const KINDS: { type: DashboardWidgetType; label: string; hint: string; Icon: typeof Hash }[] = [
  { type: "number", label: "A number", hint: "How many, or a total", Icon: Hash },
  { type: "bars", label: "Bars", hint: "Split by a column", Icon: ChartBar },
  { type: "trend", label: "Over time", hint: "Per day, week or month", Icon: ChartColumn },
  { type: "list", label: "Top rows", hint: "The biggest, or the latest", Icon: ListOrdered },
  { type: "progress", label: "Goal", hint: "Progress toward a number", Icon: Target },
  { type: "funnel", label: "Funnel", hint: "How many get through each stage", Icon: Filter },
  { type: "pace", label: "Pace", hint: "Running total vs last time", Icon: TrendingUp },
  { type: "candles", label: "Candles", hint: "A price or balance, trading-style", Icon: ChartCandlestick },
];

const field = "w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent";
const button = "inline-flex items-center gap-1.5 rounded-full border border-line px-4 py-2 text-sm text-ink-2 transition-colors hover:text-ink";
const primary = "inline-flex items-center gap-1.5 rounded-full bg-accent px-4 py-2 text-sm font-medium text-bg transition-colors hover:bg-accent-hover disabled:opacity-60";

/** The charts of a dashboard, each with its menu (change, move, remove), and the way to add one. */
export function DashboardBoard({ dashboard, actions }: { dashboard: DashboardDetail; actions: DashboardEditActions }) {
  const [editing, setEditing] = useState<DashboardWidget | "new" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const change = (w: DashboardWidget, action: "remove" | "up" | "down") =>
    start(async () => {
      setError(null);
      const result = await actions.changeDashboardWidget(dashboard.id, w.id, action);
      if (result.error) setError(result.error);
    });
  const widgets = dashboard.widgets;
  return (
    <div className={cx(pending && "opacity-70 transition-opacity")}>
      {error && (
        <p role="alert" className="mb-4 rounded-lg bg-rose-soft px-3 py-2 text-sm text-rose">
          {error}
        </p>
      )}
      {widgets.length === 0 ? (
        <Card className="flex flex-col items-center px-6 py-14 text-center">
          <p className="font-medium">No charts yet</p>
          <p className="mt-1 max-w-md text-sm text-ink-2">Add one yourself, or ask above in plain words and it&apos;s made for you.</p>
          <button type="button" onClick={() => setEditing("new")} className={cx(primary, "mt-5")}>
            <Plus className="size-4" aria-hidden /> Add a chart
          </button>
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {widgets.map((w, i) => (
            <Card
              key={w.id}
              className={cx(
                "flex min-w-0 flex-col p-5",
                w.wide ? "sm:col-span-2 lg:col-span-4" : ["bars", "list", "trend", "funnel", "pace", "candles"].includes(w.type) ? "sm:col-span-2" : "",
              )}
            >
              <div className="mb-3 flex items-start gap-2">
                <div className="min-w-0 flex-1">
                  <h3 className="font-medium text-ink" dir="auto">
                    {w.title}
                  </h3>
                  {w.tableName && (
                    <Link href={tableHref(w.table, w.where)} className="text-xs text-ink-3 hover:text-ink">
                      {w.tableName}
                      {w.where && Object.keys(w.where).length > 0 && ` · ${Object.entries(w.where).map(([k, v]) => `${k}: ${v || "empty"}`).join(", ")}`}
                    </Link>
                  )}
                </div>
                <Menu label={<span className="sr-only">Chart options</span>} icon={<Ellipsis className="size-4" aria-hidden />} align="right" className="-mt-1 -mr-2 px-1.5">
                  {(close) => (
                    <>
                      <button type="button" className={menuItem} onClick={() => (close(), setEditing(w))}>
                        <Pencil className="size-4 text-ink-3" aria-hidden /> Change it
                      </button>
                      {i > 0 && (
                        <button type="button" className={menuItem} onClick={() => (close(), change(w, "up"))}>
                          <ChevronUp className="size-4 text-ink-3" aria-hidden /> Move earlier
                        </button>
                      )}
                      {i < widgets.length - 1 && (
                        <button type="button" className={menuItem} onClick={() => (close(), change(w, "down"))}>
                          <ChevronDown className="size-4 text-ink-3" aria-hidden /> Move later
                        </button>
                      )}
                      <button
                        type="button"
                        className={cx(menuItem, "text-rose")}
                        onClick={() => {
                          close();
                          if (window.confirm(`Remove “${w.title}” from this dashboard? Your records stay as they are.`)) change(w, "remove");
                        }}
                      >
                        <Trash2 className="size-4" aria-hidden /> Remove
                      </button>
                    </>
                  )}
                </Menu>
              </div>
              {w.error ? (
                <div className="flex flex-1 flex-col items-start gap-2 text-sm">
                  <p className="flex items-start gap-2 text-rose">
                    <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden /> {w.error}
                  </p>
                  <button type="button" onClick={() => setEditing(w)} className="text-ink-2 underline underline-offset-4 hover:text-ink">
                    Change it
                  </button>
                </div>
              ) : (
                <div className="flex-1">
                  <WidgetBody widget={w} />
                </div>
              )}
            </Card>
          ))}
          <button
            type="button"
            onClick={() => setEditing("new")}
            className="flex min-h-32 items-center justify-center gap-2 rounded-2xl border border-dashed border-line text-sm text-ink-3 transition-colors hover:border-accent hover:text-ink"
          >
            <Plus className="size-4" aria-hidden /> Add a chart
          </button>
        </div>
      )}
      {editing && (
        <WidgetEditor
          key={editing === "new" ? "new" : editing.id}
          widget={editing === "new" ? null : editing}
          sources={dashboard.sources}
          used={widgets.map((w) => w.table)}
          onClose={() => setEditing(null)}
          save={(spec) => actions.saveDashboardWidget(dashboard.id, editing === "new" ? null : editing.id, spec)}
        />
      )}
    </div>
  );
}

type Draft = DashboardWidgetSpec & { filters: [string, string][] };

/** A new chart starts on the table the dashboard's charts count most (else the first one). */
function draftOf(widget: DashboardWidget | null, sources: DashboardSource[], used: string[]): Draft {
  if (widget) return { ...widget, filters: Object.entries(widget.where ?? {}) };
  const counts = new Map<string, number>();
  for (const t of used) counts.set(t, (counts.get(t) ?? 0) + 1);
  const likely = [...counts].sort((a, b) => b[1] - a[1]).find(([t]) => sources.some((s) => s.id === t))?.[0];
  return { type: "number", table: likely ?? sources[0]?.id ?? "", measure: "count", filters: [] };
}

/** A chart's settings, in a panel: what kind, which table, what it counts, filters, and its name. */
function WidgetEditor({
  widget,
  sources,
  used,
  onClose,
  save,
}: {
  widget: DashboardWidget | null;
  sources: DashboardSource[];
  used: string[];
  onClose: () => void;
  save: (spec: DashboardWidgetSpec) => Promise<{ error?: string }>;
}) {
  const [d, setD] = useState<Draft>(() => draftOf(widget, sources, used));
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const source = sources.find((s) => s.id === d.table || s.name === d.table) ?? sources[0];
  const columns = source?.columns ?? [];
  const numbers = columns.filter((c) => c.type === "number");
  const dates = columns.filter((c) => c.type === "date");
  const groupable = columns.filter((c) => ["status", "text", "person", "checkbox", "tags", "relation"].includes(c.type));
  const statuses = columns.filter((c) => c.type === "status" && (c.labels?.length ?? 0) >= 2);
  const stageColumn = statuses.find((c) => c.name === d.by) ?? statuses[0];
  const adds = d.type === "funnel" || d.type === "pace"; // running totals and funnels add up: count or sum only
  const set = (change: Partial<Draft>) => setD((old) => ({ ...old, ...change }));

  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, [onClose]);

  if (!sources.length) {
    return (
      <Panel title="Add a chart" onClose={onClose}>
        <p className="text-sm text-ink-2">Charts count the records in your library, and it has no tables yet.</p>
      </Panel>
    );
  }

  const measureValue = !d.measure || d.measure === "count" ? "count" : `${d.measure}:${d.column ?? ""}`;
  const submit = () =>
    start(async () => {
      setError(null);
      const spec: DashboardWidgetSpec = {
        type: d.type,
        title: d.title?.trim() || undefined,
        table: source.id,
        where: Object.fromEntries(d.filters.filter(([k]) => k)),
        wide: d.wide || undefined,
      };
      if (d.type === "candles")
        Object.assign(spec, {
          column: d.column ?? numbers[0]?.name,
          date: d.date || "added",
          every: d.every ?? "day",
          last: d.last,
          volume: d.volume || undefined,
          averages: d.averages?.length ? d.averages : undefined,
        });
      else if (d.type !== "list") {
        spec.measure = d.measure ?? "count";
        if (spec.measure !== "count") spec.column = d.column;
      }
      if (d.type === "number" || d.type === "progress" || d.type === "bars") {
        if (d.period) Object.assign(spec, { period: d.period, date: d.date || "added" });
      }
      if (d.type === "funnel") Object.assign(spec, { by: stageColumn?.name, stages: d.stages?.length ? d.stages : undefined });
      if (d.type === "pace") Object.assign(spec, { period: d.period ?? "year", date: d.date || "added", goal: d.goal || undefined });
      if (d.type === "progress") spec.goal = d.goal;
      if (d.type === "trend") Object.assign(spec, { date: d.date || "added", every: d.every ?? "week", last: d.last });
      if (d.type === "bars") Object.assign(spec, { by: d.by ?? groupable[0]?.name, limit: d.limit });
      if (d.type === "list") Object.assign(spec, { sort: d.sort || undefined, dir: d.dir, limit: d.limit, show: d.show?.length ? d.show : undefined });
      const result = await save(spec);
      if (result.error) setError(result.error);
      else onClose();
    });

  const label = (text: string, control: ReactNode, hint?: string) => (
    <label className="block">
      <span className="mb-1 block text-sm text-ink-2">{text}</span>
      {control}
      {hint && <span className="mt-1 block text-xs text-ink-3">{hint}</span>}
    </label>
  );

  return (
    <Panel title={widget ? "Change this chart" : "Add a chart"} onClose={onClose}>
      <form
        className="space-y-5"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <fieldset>
          <legend className="mb-2 text-sm text-ink-2">What kind</legend>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {KINDS.map((k) => (
              <button
                key={k.type}
                type="button"
                aria-pressed={d.type === k.type}
                onClick={() => set({ type: k.type })}
                className={cx(
                  "flex flex-col items-start gap-1 rounded-xl border p-3 text-left transition-colors",
                  d.type === k.type ? "border-accent bg-accent-soft" : "border-line hover:border-ink-3",
                )}
              >
                <k.Icon className={cx("size-4", d.type === k.type ? "text-accent" : "text-ink-3")} aria-hidden />
                <span className="text-sm font-medium">{k.label}</span>
                <span className="text-xs text-ink-3">{k.hint}</span>
              </button>
            ))}
          </div>
        </fieldset>

        <div className="grid gap-4 sm:grid-cols-2">
          {label(
            "From the table",
            <select
              className={field}
              value={source.id}
              onChange={(e) => set({ table: e.target.value, column: undefined, by: undefined, date: undefined, sort: undefined, show: undefined, filters: [] })}
            >
              {sources.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>,
          )}
          {d.type === "candles" &&
            label(
              "Following",
              <select className={field} value={d.column ?? numbers[0]?.name ?? ""} onChange={(e) => set({ column: e.target.value })}>
                {numbers.map((c) => (
                  <option key={c.name} value={c.name}>
                    {c.name}
                  </option>
                ))}
              </select>,
              numbers.length ? "Each candle opens at the period's first value and closes at its last." : "Candles follow a number column, and this table has none.",
            )}
          {d.type !== "list" &&
            d.type !== "candles" &&
            label(
              "Counting",
              <select
                className={field}
                value={measureValue}
                onChange={(e) => {
                  const [measure, column] = e.target.value.split(":");
                  set({ measure: measure as Draft["measure"], column: column || undefined });
                }}
              >
                <option value="count">How many rows</option>
                {numbers.flatMap((c) => [
                  <option key={`sum:${c.name}`} value={`sum:${c.name}`}>
                    Total {c.name}
                  </option>,
                  ...(adds ? [] : [
                  <option key={`average:${c.name}`} value={`average:${c.name}`}>
                    Average {c.name}
                  </option>,
                  <option key={`min:${c.name}`} value={`min:${c.name}`}>
                    Lowest {c.name}
                  </option>,
                  <option key={`max:${c.name}`} value={`max:${c.name}`}>
                    Highest {c.name}
                  </option>,
                  ]),
                ])}
              </select>,
            )}

          {d.type === "bars" &&
            label(
              "One bar per",
              <select className={field} value={d.by ?? groupable[0]?.name ?? ""} onChange={(e) => set({ by: e.target.value })}>
                {groupable.map((c) => (
                  <option key={c.name} value={c.name}>
                    {c.name}
                  </option>
                ))}
              </select>,
              groupable.length ? undefined : "This table has no column to split by (a status, text, person, checkbox or tags).",
            )}

          {d.type === "funnel" &&
            label(
              "Stages from",
              <select className={field} value={stageColumn?.name ?? ""} onChange={(e) => set({ by: e.target.value, stages: undefined })}>
                {statuses.map((c) => (
                  <option key={c.name} value={c.name}>
                    {c.name}
                  </option>
                ))}
              </select>,
              statuses.length ? undefined : "A funnel goes through the labels of a status column, and this table has none.",
            )}
          {d.type === "pace" &&
            label(
              "Running through",
              <select className={field} value={d.period ?? "year"} onChange={(e) => set({ period: e.target.value as Draft["period"] })}>
                <option value="week">This week, vs last week</option>
                <option value="month">This month, vs last month</option>
                <option value="quarter">This quarter, vs last quarter</option>
                <option value="year">This year, vs last year</option>
              </select>,
            )}
          {(d.type === "number" || d.type === "progress" || d.type === "bars") &&
            label(
              "Which rows",
              <select className={field} value={d.period ?? ""} onChange={(e) => set({ period: (e.target.value || undefined) as Draft["period"] })}>
                <option value="">All of them</option>
                <option value="week">This week</option>
                <option value="month">This month</option>
                <option value="quarter">This quarter</option>
                <option value="year">This year</option>
              </select>,
              d.type !== "progress" && d.period ? `${d.type === "bars" ? "Each bar" : "It"} also shows the one before, to compare.` : undefined,
            )}
          {(d.type === "trend" || d.type === "pace" || d.type === "candles" || ((d.type === "number" || d.type === "progress" || d.type === "bars") && d.period)) &&
            label(
              "By the date",
              <select className={field} value={d.date ?? "added"} onChange={(e) => set({ date: e.target.value })}>
                <option value="added">When each row was added</option>
                {dates.map((c) => (
                  <option key={c.name} value={c.name}>
                    {c.name}
                  </option>
                ))}
              </select>,
            )}
          {d.type === "trend" && (
            <>
              {label(
                "One bar per",
                <select className={field} value={d.every ?? "week"} onChange={(e) => set({ every: e.target.value as Draft["every"], last: undefined })}>
                  <option value="day">Day</option>
                  <option value="week">Week</option>
                  <option value="month">Month</option>
                </select>,
              )}
              {label(
                "How many",
                <input
                  type="number"
                  min={2}
                  max={36}
                  className={field}
                  value={d.last ?? { day: 14, week: 8, month: 6 }[d.every ?? "week"]}
                  onChange={(e) => set({ last: Number(e.target.value) || undefined })}
                />,
              )}
            </>
          )}
          {d.type === "candles" && (
            <>
              {label(
                "One candle per",
                <select className={field} value={d.every ?? "day"} onChange={(e) => set({ every: e.target.value as Draft["every"], last: undefined })}>
                  <option value="day">Day</option>
                  <option value="week">Week</option>
                  <option value="month">Month</option>
                </select>,
              )}
              {label(
                "How many",
                <input
                  type="number"
                  min={5}
                  max={365}
                  className={field}
                  value={d.last ?? { day: 90, week: 52, month: 24 }[d.every ?? "day"]}
                  onChange={(e) => set({ last: Number(e.target.value) || undefined })}
                />,
              )}
              {label(
                "Volume underneath",
                <select className={field} value={d.volume ?? ""} onChange={(e) => set({ volume: e.target.value || undefined })}>
                  <option value="">None</option>
                  <option value="rows">How many rows</option>
                  {numbers.map((c) => (
                    <option key={c.name} value={c.name}>
                      Total {c.name}
                    </option>
                  ))}
                </select>,
              )}
              {label(
                "Moving averages (optional)",
                <input
                  className={field}
                  placeholder="Like 7, 30"
                  defaultValue={d.averages?.join(", ") ?? ""}
                  onChange={(e) =>
                    set({
                      averages: e.target.value
                        .split(/[,\s]+/)
                        .map(Number)
                        .filter((n) => Number.isInteger(n) && n >= 2 && n <= 200)
                        .slice(0, 3),
                    })
                  }
                />,
                "How many candles each average spans, up to 3.",
              )}
            </>
          )}
          {d.type === "pace" &&
            label(
              "A goal (optional)",
              <input type="number" min={0} step="any" className={field} value={d.goal ?? ""} onChange={(e) => set({ goal: Number(e.target.value) || undefined })} />,
            )}
          {d.type === "progress" &&
            label(
              "The goal",
              <input type="number" min={0} step="any" required className={field} value={d.goal ?? ""} onChange={(e) => set({ goal: Number(e.target.value) || undefined })} />,
            )}
          {d.type === "list" && (
            <>
              {label(
                "In order of",
                <select className={field} value={d.sort ?? ""} onChange={(e) => set({ sort: e.target.value || undefined })}>
                  <option value="">Newest first</option>
                  {columns
                    .filter((c) => !["longtext", "files", "tags"].includes(c.type))
                    .map((c) => (
                      <option key={c.name} value={c.name}>
                        {c.name}
                      </option>
                    ))}
                </select>,
              )}
              {d.sort &&
                label(
                  "Which first",
                  <select className={field} value={d.dir ?? "desc"} onChange={(e) => set({ dir: e.target.value as Draft["dir"] })}>
                    <option value="desc">Highest or latest</option>
                    <option value="asc">Lowest or earliest</option>
                  </select>,
                )}
              {label(
                "How many rows",
                <input type="number" min={1} max={10} className={field} value={d.limit ?? 5} onChange={(e) => set({ limit: Number(e.target.value) || undefined })} />,
              )}
            </>
          )}
        </div>

        {d.type === "funnel" && stageColumn && (
          <fieldset>
            <legend className="mb-2 text-sm text-ink-2">Its stages, in order (leave out ones like Lost)</legend>
            <div className="flex flex-wrap gap-2">
              {(stageColumn.labels ?? []).map((l) => {
                const chosen = d.stages ?? stageColumn.labels ?? [];
                const on = chosen.includes(l);
                return (
                  <button
                    key={l}
                    type="button"
                    aria-pressed={on}
                    onClick={() => set({ stages: (stageColumn.labels ?? []).filter((x) => (x === l ? !on : chosen.includes(x))) })}
                    className={cx("rounded-full border px-3 py-1 text-sm", on ? "border-accent bg-accent-soft text-ink" : "border-line text-ink-2")}
                  >
                    {l}
                  </button>
                );
              })}
            </div>
          </fieldset>
        )}

        {d.type === "list" && (
          <fieldset>
            <legend className="mb-2 text-sm text-ink-2">Columns to show (up to 4)</legend>
            <div className="flex flex-wrap gap-2">
              {columns
                .filter((c) => !["longtext", "files"].includes(c.type))
                .map((c) => {
                  const chosen = d.show ?? columns.filter((x) => !["longtext", "files"].includes(x.type)).slice(0, 3).map((x) => x.name);
                  const on = chosen.includes(c.name);
                  return (
                    <button
                      key={c.name}
                      type="button"
                      aria-pressed={on}
                      disabled={!on && chosen.length >= 4}
                      onClick={() => set({ show: on ? chosen.filter((n) => n !== c.name) : [...chosen, c.name] })}
                      className={cx("rounded-full border px-3 py-1 text-sm disabled:opacity-40", on ? "border-accent bg-accent-soft text-ink" : "border-line text-ink-2")}
                    >
                      {c.name}
                    </button>
                  );
                })}
            </div>
          </fieldset>
        )}

        <fieldset>
          <legend className="mb-2 text-sm text-ink-2">Only rows where (optional)</legend>
          <div className="space-y-2">
            {d.filters.map(([k, v], i) => {
              const col = columns.find((c) => c.name === k);
              const setFilter = (next: [string, string]) => set({ filters: d.filters.map((f, j) => (j === i ? next : f)) });
              return (
                <div key={i} className="flex items-center gap-2">
                  <select className={cx(field, "w-auto min-w-0 flex-1")} value={k} onChange={(e) => setFilter([e.target.value, ""])}>
                    {columns
                      .filter((c) => !["longtext", "files"].includes(c.type))
                      .map((c) => (
                        <option key={c.name} value={c.name}>
                          {c.name}
                        </option>
                      ))}
                  </select>
                  <span className="text-sm text-ink-3">is</span>
                  {col?.labels?.length || col?.type === "checkbox" ? (
                    <select className={cx(field, "w-auto min-w-0 flex-1")} value={v} onChange={(e) => setFilter([k, e.target.value])}>
                      {(col.type === "checkbox" ? ["true", "false"] : col.labels ?? []).map((l) => (
                        <option key={l} value={l}>
                          {col.type === "checkbox" ? (l === "true" ? "Ticked" : "Not ticked") : l}
                        </option>
                      ))}
                      {col.type !== "checkbox" && <option value="">Empty</option>}
                    </select>
                  ) : (
                    <input className={cx(field, "w-auto min-w-0 flex-1")} value={v} placeholder="Empty" onChange={(e) => setFilter([k, e.target.value])} />
                  )}
                  <button type="button" onClick={() => set({ filters: d.filters.filter((_, j) => j !== i) })} className="p-1 text-ink-3 hover:text-ink" aria-label="Remove this filter">
                    <X className="size-4" />
                  </button>
                </div>
              );
            })}
            {d.filters.length < 5 && columns.length > 0 && (
              <button
                type="button"
                onClick={() => {
                  const first = columns.find((c) => c.type === "status") ?? columns[0];
                  set({ filters: [...d.filters, [first.name, first.labels?.[0] ?? (first.type === "checkbox" ? "true" : "")]] });
                }}
                className="inline-flex items-center gap-1 text-sm text-ink-2 hover:text-ink"
              >
                <Plus className="size-3.5" aria-hidden /> Add a filter
              </button>
            )}
          </div>
        </fieldset>

        <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
          {label("Name (optional)", <input className={field} maxLength={80} value={d.title ?? ""} placeholder="Named for you if you leave it" onChange={(e) => set({ title: e.target.value })} />)}
          <label className="flex items-center gap-2 pb-2 text-sm text-ink-2">
            <input type="checkbox" checked={Boolean(d.wide)} onChange={(e) => set({ wide: e.target.checked })} className="size-4 accent-[var(--accent)]" />
            The whole width
          </label>
        </div>

        {error && (
          <p role="alert" className="rounded-lg bg-rose-soft px-3 py-2 text-sm text-rose">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className={button}>
            Cancel
          </button>
          <button type="submit" disabled={pending} className={primary}>
            {pending && <Loader2 className="size-4 animate-spin" aria-hidden />}
            {widget ? "Save" : "Add it"}
          </button>
        </div>
      </form>
    </Panel>
  );
}

function Panel({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-ink/30 sm:items-center sm:p-6" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true" aria-label={title} className="max-h-[92dvh] w-full max-w-2xl overflow-y-auto rounded-t-2xl border border-line bg-surface p-5 shadow-lg sm:rounded-2xl sm:p-7">
        <div className="mb-5 flex items-center justify-between gap-4">
          <h2 className="font-display text-2xl">{title}</h2>
          <button type="button" onClick={onClose} className="rounded-full p-1.5 text-ink-3 hover:bg-surface-2 hover:text-ink" aria-label="Close">
            <X className="size-5" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

/**
 * Ask the COO in plain words: for a new dashboard (on the Library page) or a change to this one. It
 * works on it in the background, through the chat; requests and replies show here until they're a day old.
 */
export function AskForDashboard({
  dashboardId,
  asks,
  cooName,
  ask,
  placeholder,
}: {
  dashboardId?: string;
  asks: DashboardAsk[];
  cooName: string;
  ask: DashboardActions["askForDashboard"];
  placeholder: string;
}) {
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const working = asks.some((a) => a.status === "asked");
  const submit = () =>
    start(async () => {
      setError(null);
      const result = await ask(text, dashboardId);
      if (result.error) setError(result.error);
      else setText("");
    });
  return (
    <div>
      {working && <Poll seconds={4} />}
      <form
        className="flex flex-col gap-2 sm:flex-row"
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim()) submit();
        }}
      >
        <label className="min-w-0 flex-1">
          <span className="sr-only">What would you like to see?</span>
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            maxLength={2000}
            placeholder={placeholder}
            className="w-full rounded-full border border-line bg-surface px-4 py-2.5 text-sm outline-none placeholder:text-ink-3 focus:border-accent"
          />
        </label>
        <button type="submit" disabled={pending || !text.trim()} className={primary}>
          {pending ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Sparkles className="size-4" aria-hidden />}
          Ask {cooName}
        </button>
      </form>
      {error && (
        <p role="alert" className="mt-2 text-sm text-rose">
          {error}
        </p>
      )}
      {asks.length > 0 && (
        <ul className="mt-3 space-y-2">
          {asks.map((a) => (
            <li key={a.id} className="rounded-xl border border-line bg-surface px-4 py-3 text-sm">
              <p className="text-ink-3" dir="auto">
                You asked: <span className="text-ink-2">{a.text}</span>
              </p>
              {a.status === "asked" ? (
                <p className="mt-1.5 flex items-center gap-2 text-ink-2">
                  <Loader2 className="size-4 animate-spin text-accent" aria-hidden /> {cooName} is working on it. You can leave this page.
                </p>
              ) : (
                <div className={cx("mt-1.5", a.status === "failed" ? "text-rose" : "text-ink")} dir="auto">
                  <Markdown text={a.reply ?? ""} />
                  {a.made && a.made !== dashboardId && (
                    <Link href={`/library/dashboards/${a.made}`} className="mt-1 inline-block font-medium text-accent hover:underline">
                      Open the dashboard
                    </Link>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Start an empty dashboard by name, then add charts to it. */
export function NewDashboard({ create }: { create: DashboardActions["createDashboard"] }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)} className="text-sm text-ink-2 underline decoration-line underline-offset-4 hover:text-ink">
        or start an empty one
      </button>
    );
  }
  return (
    <form
      className="flex flex-wrap items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        start(async () => {
          setError(null);
          const result = await create(name);
          if (result.error) setError(result.error);
          else if (result.id) router.push(`/library/dashboards/${result.id}`);
        });
      }}
    >
      <input autoFocus value={name} onChange={(e) => setName(e.target.value)} maxLength={80} placeholder="Its name, like Sales" className={cx(field, "w-64")} />
      <button type="submit" disabled={pending || !name.trim()} className={primary}>
        {pending && <Loader2 className="size-4 animate-spin" aria-hidden />} Make it
      </button>
      <button type="button" onClick={() => setOpen(false)} className="text-sm text-ink-3 hover:text-ink">
        Cancel
      </button>
      {error && <p className="w-full text-sm text-rose">{error}</p>}
    </form>
  );
}

/** Rename a dashboard or change its description, and remove it. */
export function DashboardSettings({ dashboard, actions }: { dashboard: Pick<DashboardDetail, "id" | "name" | "description">; actions: DashboardEditActions }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(dashboard.name);
  const [description, setDescription] = useState(dashboard.description);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  return (
    <>
      <div className="flex items-center gap-1">
        <button type="button" onClick={() => setOpen(true)} className="rounded-full p-2 text-ink-3 hover:bg-surface-2 hover:text-ink" title="Rename">
          <Pencil className="size-4" aria-hidden />
          <span className="sr-only">Rename</span>
        </button>
        <button
          type="button"
          title="Remove"
          onClick={() => {
            if (!window.confirm(`Remove the dashboard “${dashboard.name}”? Your records stay as they are.`)) return;
            start(async () => {
              const result = await actions.removeDashboard(dashboard.id);
              if (result?.error) setError(result.error);
            });
          }}
          className="rounded-full p-2 text-ink-3 hover:bg-surface-2 hover:text-rose"
        >
          <Trash2 className="size-4" aria-hidden />
          <span className="sr-only">Remove</span>
        </button>
      </div>
      {error && !open && <p className="text-sm text-rose">{error}</p>}
      {open && (
        <Panel title="Rename the dashboard" onClose={() => setOpen(false)}>
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              start(async () => {
                setError(null);
                const result = await actions.saveDashboard(dashboard.id, { name, description });
                if (result.error) setError(result.error);
                else setOpen(false);
              });
            }}
          >
            <label className="block">
              <span className="mb-1 block text-sm text-ink-2">Name</span>
              <input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} required className={field} />
            </label>
            <label className="block">
              <span className="mb-1 block text-sm text-ink-2">What it&apos;s for (optional)</span>
              <input value={description} onChange={(e) => setDescription(e.target.value)} maxLength={300} className={field} />
            </label>
            {error && <p className="text-sm text-rose">{error}</p>}
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setOpen(false)} className={button}>
                Cancel
              </button>
              <button type="submit" disabled={pending} className={primary}>
                Save
              </button>
            </div>
          </form>
        </Panel>
      )}
    </>
  );
}
