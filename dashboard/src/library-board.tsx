"use client";

import { Plus } from "lucide-react";
import { useState } from "react";
import type { CellValue, LibraryRow } from "./backend/types";
import { CellView, number, rowTitle, statusTone } from "./library-cells";
import type { ViewContext } from "./library-workspace";
import { Pill, cx } from "./ui";

type Lane = { value: string | null; total: number; rows: LibraryRow[] };

/**
 * The board view (kanban), after Teable's: a column for each label of a status column (and one for
 * rows without it), cards with the row's title and a few fields, dragged between columns to change
 * the status, and a quick add at the foot of each column.
 */
export function BoardView({ ctx, by, lanes: initial }: { ctx: ViewContext; by: string; lanes: Lane[] }) {
  const col = ctx.columns.find((c) => c.name === by)!;
  const labels = col.options.labels ?? [];
  const [lanes, setLanes] = useState(initial);
  const [seen, setSeen] = useState(initial);
  const [dragging, setDragging] = useState<string | null>(null);
  const [over, setOver] = useState<string | null | undefined>(undefined);
  if (seen !== initial) {
    setSeen(initial);
    setLanes(initial);
  }
  const fields = ctx.shown.slice(1).filter((c) => c.name !== by).slice(0, 4);
  const empty = lanes.find((l) => l.value === null);
  const shownLanes = lanes.filter((l) => l.value !== null || (empty && empty.total > 0));

  async function move(rowId: string, to: string | null) {
    const from = lanes.find((l) => l.rows.some((r) => r.id === rowId));
    if (!from || from.value === to) return;
    const row = from.rows.find((r) => r.id === rowId)!;
    const moved = { ...row, cells: { ...row.cells, [by]: to as CellValue } };
    setLanes((all) =>
      all.map((l) =>
        l === from ? { ...l, total: l.total - 1, rows: l.rows.filter((r) => r.id !== rowId) } : l.value === to ? { ...l, total: l.total + 1, rows: [moved, ...l.rows] } : l,
      ),
    );
    if (!(await ctx.saveCell(rowId, col, to))) setLanes(seen); // put it back
  }

  return (
    <div className="flex gap-3 overflow-x-auto pb-3" style={{ minHeight: "calc(100vh - 20rem)" }}>
      {shownLanes.map((lane) => {
        const key = lane.value ?? "";
        return (
          <section
            key={key}
            aria-label={lane.value ?? `No ${by.toLowerCase()}`}
            onDragOver={(e) => {
              if (!dragging || ctx.readOnly) return;
              e.preventDefault();
              setOver(lane.value);
            }}
            onDragLeave={() => setOver(undefined)}
            onDrop={(e) => {
              e.preventDefault();
              setOver(undefined);
              const id = e.dataTransfer.getData("text/plain");
              if (id) move(id, lane.value);
            }}
            className={cx("flex w-72 shrink-0 flex-col rounded-2xl bg-surface-2/60 p-2 transition-colors", over === lane.value && dragging && "bg-accent-soft/60 ring-2 ring-accent/40")}
          >
            <header className="mb-2 flex items-center gap-2 px-1.5 pt-1">
              {lane.value ? <Pill tone={statusTone(lane.value, labels)}>{lane.value}</Pill> : <span className="text-sm text-ink-3">No {by.toLowerCase()}</span>}
              <span className="text-xs text-ink-3 tabular-nums">{number(lane.total)}</span>
            </header>
            <ol className="flex-1 space-y-2 overflow-y-auto" style={{ maxHeight: "calc(100vh - 22rem)" }}>
              {lane.rows.map((r) => (
                <li
                  key={r.id}
                  draggable={!ctx.readOnly}
                  onDragStart={(e) => {
                    e.dataTransfer.setData("text/plain", r.id);
                    e.dataTransfer.effectAllowed = "move";
                    setDragging(r.id);
                  }}
                  onDragEnd={() => setDragging(null)}
                  className={cx("rounded-xl border border-line bg-surface shadow-sm transition-opacity", dragging === r.id && "opacity-50")}
                >
                  <button type="button" onClick={() => ctx.openRow(r.id)} className="block w-full cursor-grab px-3 py-2.5 text-left active:cursor-grabbing">
                    <p className="text-sm font-medium break-words text-ink" dir="auto">
                      {rowTitle(ctx.columns, r.cells) || <span className="text-ink-3">Untitled</span>}
                    </p>
                    {fields.some((c) => r.cells[c.name] !== null && r.cells[c.name] !== undefined && r.cells[c.name] !== "") && (
                      <dl className="mt-1.5 space-y-1">
                        {fields.map((c) => {
                          const v = r.cells[c.name];
                          if (v === null || v === undefined || v === "" || (Array.isArray(v) && !v.length)) return null;
                          return (
                            <div key={c.id} className="flex min-w-0 items-center gap-2 text-xs text-ink-2">
                              <dt className="sr-only">{c.name}</dt>
                              <dd className="min-w-0 truncate" dir="auto">
                                <CellView col={c} value={v} related={ctx.related} files={ctx.files} filesUrl={ctx.filesUrl} />
                              </dd>
                            </div>
                          );
                        })}
                      </dl>
                    )}
                  </button>
                </li>
              ))}
              {lane.total > lane.rows.length && (
                <li className="px-2 py-1 text-xs text-ink-3">
                  {number(lane.total - lane.rows.length)} more. Search or filter to narrow them down.
                </li>
              )}
            </ol>
            {!ctx.readOnly && (
              <button
                type="button"
                onClick={() => ctx.addRow(lane.value ? { [by]: lane.value } : {})}
                className="mt-2 flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm text-ink-3 hover:bg-surface hover:text-ink"
              >
                <Plus className="size-4" aria-hidden /> Add a row
              </button>
            )}
          </section>
        );
      })}
    </div>
  );
}
