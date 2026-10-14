"use client";

import { ChevronLeft, ChevronRight, Plus } from "lucide-react";
import { useState } from "react";
import type { LibraryRow } from "./backend/types";
import { MONTHS, number, rowTitle, statusTone } from "./library-cells";
import type { ViewContext } from "./library-workspace";
import { cx } from "./ui";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const DOT = { accent: "bg-accent", rose: "bg-rose", amber: "bg-amber", sky: "bg-sky", violet: "bg-violet", neutral: "bg-ink-3" } as const;

/** YYYY-MM-DD plus n days, in UTC so time zones don't shift it. */
function addDays(day: string, n: number): string {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

function shiftMonth(month: string, n: number): string {
  const [y, m] = month.split("-").map(Number);
  const d = new Date(Date.UTC(y, m - 1 + n, 1));
  return d.toISOString().slice(0, 7);
}

/**
 * The calendar view, after Teable's: a month of six weeks with each row on its date (from a date
 * column), dragged to another day to change the date, and a quick add on any day.
 */
export function CalendarView({
  ctx,
  by,
  month,
  start,
  today,
  rows: initial,
  undated,
}: {
  ctx: ViewContext;
  by: string;
  /** YYYY-MM */
  month: string;
  /** The Monday the grid starts on, YYYY-MM-DD. */
  start: string;
  today: string;
  rows: LibraryRow[];
  undated: number;
}) {
  const col = ctx.columns.find((c) => c.name === by)!;
  const status = ctx.columns.find((c) => c.type === "status");
  const [rows, setRows] = useState(initial);
  const [seen, setSeen] = useState(initial);
  const [dragging, setDragging] = useState<string | null>(null);
  const [over, setOver] = useState<string | null>(null);
  if (seen !== initial) {
    setSeen(initial);
    setRows(initial);
  }
  const days = Array.from({ length: 42 }, (_, i) => addDays(start, i));
  const byDay = new Map<string, LibraryRow[]>();
  for (const r of rows) {
    const day = String(r.cells[by] ?? "").slice(0, 10);
    byDay.set(day, [...(byDay.get(day) ?? []), r]);
  }
  const [y, m] = month.split("-").map(Number);

  async function moveTo(rowId: string, day: string) {
    const row = rows.find((r) => r.id === rowId);
    if (!row || String(row.cells[by] ?? "").slice(0, 10) === day) return;
    setRows((all) => all.map((r) => (r.id === rowId ? { ...r, cells: { ...r.cells, [by]: day } } : r)));
    if (!(await ctx.saveCell(rowId, col, day))) setRows(seen);
  }

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 className="mr-2 font-display text-2xl">
          {MONTHS[m - 1]} {y}
        </h2>
        <button type="button" onClick={() => ctx.go({ month: shiftMonth(month, -1) })} className="rounded-lg border border-line p-1.5 text-ink-2 hover:text-ink" aria-label="Previous month">
          <ChevronLeft className="size-4" />
        </button>
        <button type="button" onClick={() => ctx.go({ month: "" })} className="rounded-lg border border-line px-2.5 py-1 text-sm text-ink-2 hover:text-ink">
          Today
        </button>
        <button type="button" onClick={() => ctx.go({ month: shiftMonth(month, 1) })} className="rounded-lg border border-line p-1.5 text-ink-2 hover:text-ink" aria-label="Next month">
          <ChevronRight className="size-4" />
        </button>
        {undated > 0 && <span className="ml-auto text-sm text-ink-3">{number(undated)} {undated === 1 ? "row has" : "rows have"} no {by.toLowerCase()} yet</span>}
      </div>
      <div className="overflow-x-auto rounded-2xl border border-line bg-surface">
        <div className="grid min-w-[42rem] grid-cols-7">
          {WEEKDAYS.map((d) => (
            <div key={d} className="border-b border-line bg-surface-2 px-2 py-1.5 text-xs font-medium text-ink-3">
              {d}
            </div>
          ))}
          {days.map((day, i) => {
            const inMonth = day.slice(0, 7) === month;
            const items = byDay.get(day) ?? [];
            return (
              <div
                key={day}
                onDragOver={(e) => {
                  if (!dragging) return;
                  e.preventDefault();
                  setOver(day);
                }}
                onDragLeave={() => setOver(null)}
                onDrop={(e) => {
                  e.preventDefault();
                  setOver(null);
                  const id = e.dataTransfer.getData("text/plain");
                  if (id) moveTo(id, day);
                }}
                className={cx(
                  "group relative min-h-28 border-line p-1.5",
                  i % 7 !== 6 && "border-r",
                  i < 35 && "border-b",
                  !inMonth && "bg-surface-2/40",
                  over === day && "bg-accent-soft/60",
                )}
              >
                <div className="mb-1 flex items-center justify-between">
                  <span className={cx("grid size-6 place-items-center rounded-full text-xs", day === today ? "bg-accent font-semibold text-bg" : inMonth ? "text-ink-2" : "text-ink-3/60")}>
                    {Number(day.slice(8))}
                  </span>
                  <button
                    type="button"
                    onClick={() => ctx.addRow({ [by]: day })}
                    className="rounded p-0.5 text-ink-3 opacity-0 group-hover:opacity-100 hover:bg-surface-2 hover:text-ink focus:opacity-100"
                    aria-label={`Add a row on ${day}`}
                  >
                    <Plus className="size-3.5" />
                  </button>
                </div>
                <ul className="max-h-32 space-y-1 overflow-y-auto">
                  {items.map((r) => {
                    const label = status ? r.cells[status.name] : null;
                    const tone = typeof label === "string" ? statusTone(label, status?.options.labels ?? []) : "neutral";
                    return (
                      <li key={r.id}>
                        <button
                          type="button"
                          draggable
                          onDragStart={(e) => {
                            e.dataTransfer.setData("text/plain", r.id);
                            e.dataTransfer.effectAllowed = "move";
                            setDragging(r.id);
                          }}
                          onDragEnd={() => setDragging(null)}
                          onClick={() => ctx.openRow(r.id)}
                          title={typeof label === "string" ? label : undefined}
                          className={cx(
                            "flex w-full cursor-grab items-center gap-1.5 truncate rounded-md border border-line bg-bg px-1.5 py-1 text-left text-xs text-ink hover:border-accent active:cursor-grabbing",
                            dragging === r.id && "opacity-50",
                          )}
                          dir="auto"
                        >
                          <span className={cx("size-1.5 shrink-0 rounded-full", DOT[tone])} aria-hidden />
                          <span className="truncate">{rowTitle(ctx.columns, r.cells) || "Untitled"}</span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
