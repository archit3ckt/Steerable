"use client";

import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Maximize2 } from "lucide-react";
import { Fragment, useState } from "react";
import type { CellValue, LibraryColumn, LibraryPage } from "./backend/types";
import { CellEditor, CellView, ICONS, MIN_REM, STRETCHES, display, number } from "./library-cells";
import type { ViewContext } from "./library-workspace";
import { cx } from "./ui";

/**
 * The grid view, after Teable's: the row number and first column pinned while scrolling sideways,
 * text columns sharing the spare width, cells edited in place, rows grouped under a header with
 * their count, number sums at the foot, and pages of rows.
 */
export function GridView({ ctx, page, openId }: { ctx: ViewContext; page: LibraryPage; openId?: string }) {
  const { shown, config, nav, pageSize, readOnly } = ctx;
  const [editing, setEditing] = useState<{ row: string; col: string } | null>(null);
  const [overlay, setOverlay] = useState<Record<string, Record<string, CellValue>>>({});
  const [seen, setSeen] = useState(page);
  if (seen !== page) {
    // fresh rows from the server replace the values shown while saving
    setSeen(page);
    setOverlay({});
  }

  async function saveCell(rowId: string, col: LibraryColumn, value: CellValue) {
    setEditing(null);
    setOverlay((o) => ({ ...o, [rowId]: { ...o[rowId], [col.name]: value } }));
    if (!(await ctx.saveCell(rowId, col, value))) {
      setOverlay((o) => {
        const rest = { ...o[rowId] };
        delete rest[col.name];
        return { ...o, [rowId]: rest };
      });
    }
  }

  function sortBy(col: LibraryColumn) {
    if (config.sort !== col.name) return ctx.setConfig({ ...config, sort: col.name, dir: "asc" });
    if (config.dir !== "desc") return ctx.setConfig({ ...config, dir: "desc" });
    ctx.setConfig({ ...config, sort: undefined, dir: undefined });
  }

  const groupCol = config.group ? ctx.columns.find((c) => c.name === config.group) : undefined;
  const groupCount = (value: CellValue) => page.groups.find((g) => (g.value ?? null) === (value ?? null) || (groupCol?.type === "checkbox" && Boolean(g.value) === Boolean(value)))?.count;
  const hasSums = Object.keys(page.sums).length > 0;
  const from = page.total ? nav.offset + 1 : 0;
  const to = Math.min(nav.offset + page.rows.length, page.total);
  const width = 3.5 + shown.reduce((sum, c) => sum + MIN_REM[c.type], 0);

  return (
    <>
      <div className="overflow-auto rounded-2xl border border-line bg-surface" style={{ maxHeight: "calc(100vh - 18rem)" }}>
        {/* Fixed layout: compact columns keep their width, text columns share the rest of the screen,
            and the table only scrolls sideways once every column is at its narrowest. */}
        <table className="table-fixed border-separate border-spacing-0 text-sm" style={{ width: `max(100%, ${width}rem)` }}>
          <caption className="sr-only">Rows</caption>
          <colgroup>
            <col style={{ width: "3.5rem" }} />
            {shown.map((c) => (
              <col key={c.id} style={STRETCHES.has(c.type) ? undefined : { width: `${MIN_REM[c.type]}rem` }} />
            ))}
          </colgroup>
          <thead>
            <tr>
              <th scope="col" className="sticky top-0 left-0 z-20 border-r border-b border-line bg-surface-2 px-2 py-2 text-right text-xs font-normal text-ink-3">
                <span className="sr-only">Row</span>#
              </th>
              {shown.map((c, i) => {
                const Icon = ICONS[c.type];
                const sorted = config.sort === c.name;
                return (
                  <th
                    key={c.id}
                    scope="col"
                    aria-sort={sorted ? (config.dir === "desc" ? "descending" : "ascending") : undefined}
                    style={{ left: i === 0 ? "3.5rem" : undefined }}
                    className={cx("sticky top-0 border-b border-line bg-surface-2 p-0 text-left font-medium text-ink-2", i === 0 ? "z-20 border-r" : "z-10 border-r border-r-line/60")}
                  >
                    <button type="button" onClick={() => sortBy(c)} disabled={c.type === "files"} className="flex w-full items-center gap-1.5 px-3 py-2 text-left hover:text-ink" title={`Sort by ${c.name}`}>
                      <Icon className="size-3.5 shrink-0 text-ink-3" aria-hidden />
                      <span className="truncate">{c.name}</span>
                      {sorted && (config.dir === "desc" ? <ArrowDown className="ml-auto size-3.5 text-accent" aria-hidden /> : <ArrowUp className="ml-auto size-3.5 text-accent" aria-hidden />)}
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {page.rows.map((r, index) => {
              const cells = { ...r.cells, ...overlay[r.id] };
              const groupValue = groupCol ? (r.cells[groupCol.name] ?? null) : undefined;
              const prev = index > 0 && groupCol ? (page.rows[index - 1].cells[groupCol.name] ?? null) : undefined;
              const newGroup = groupCol && (index === 0 || JSON.stringify(prev) !== JSON.stringify(groupValue));
              return (
                <Fragment key={r.id}>
                  {newGroup && groupCol && (
                    <tr>
                      <td colSpan={shown.length + 1} className="sticky left-0 border-b border-line bg-surface-2/70 px-3 py-2 text-sm">
                        <span className="inline-flex items-center gap-2">
                          {groupValue === null || groupValue === "" ? (
                            <span className="text-ink-3">No {groupCol.name.toLowerCase()}</span>
                          ) : (
                            <CellView col={groupCol} value={groupValue} related={ctx.related} />
                          )}
                          {groupCol.type === "checkbox" && <span className="text-ink-2">{groupValue ? "Yes" : "No"}</span>}
                          <span className="text-xs text-ink-3">{number(groupCount(groupValue ?? null) ?? 0)}</span>
                        </span>
                      </td>
                    </tr>
                  )}
                  <tr className={cx("group", openId === r.id && "[&>td]:bg-accent-soft/40")}>
                    <td className="sticky left-0 z-10 border-r border-b border-line bg-surface px-2 py-1.5 text-right text-xs text-ink-3 group-hover:bg-surface-2">
                      <span className="group-hover:hidden">{nav.offset + index + 1}</span>
                      <button type="button" onClick={() => ctx.openRow(r.id)} className="hidden w-full justify-end text-ink-2 hover:text-accent group-hover:flex" aria-label={`Open row ${nav.offset + index + 1}`}>
                        <Maximize2 className="size-3.5" />
                      </button>
                    </td>
                    {shown.map((c, i) => {
                      const isEditing = editing?.row === r.id && editing.col === c.id;
                      const value = cells[c.name];
                      const editable = !["relation", "files"].includes(c.type) && !readOnly;
                      return (
                        <td
                          key={c.id}
                          dir="auto"
                          tabIndex={editable ? 0 : undefined}
                          onClick={() => {
                            if (!editable) return c.type === "files" && !readOnly ? ctx.openRow(r.id) : undefined;
                            if (isEditing) return;
                            if (c.type === "checkbox") return saveCell(r.id, c, !value);
                            setEditing({ row: r.id, col: c.id });
                          }}
                          onKeyDown={(e) => {
                            if (!editable || isEditing || (e.key !== "Enter" && e.key !== " ")) return;
                            e.preventDefault();
                            if (c.type === "checkbox") saveCell(r.id, c, !value);
                            else setEditing({ row: r.id, col: c.id });
                          }}
                          style={{ left: i === 0 ? "3.5rem" : undefined }}
                          className={cx(
                            "border-b border-line px-3 py-1.5 text-start align-middle group-hover:bg-surface-2",
                            i === 0 ? "sticky z-10 border-r bg-surface font-medium text-ink" : "border-r border-r-line/60 text-ink-2",
                            c.type === "number" && "text-right tabular-nums",
                            editable && "cursor-cell focus:outline-2 focus:-outline-offset-2 focus:outline-accent",
                            isEditing ? "relative z-20 p-0.5" : "truncate",
                          )}
                          title={!isEditing && typeof value === "string" && value.length > 30 ? value : undefined}
                        >
                          {isEditing ? (
                            <CellEditor col={c} value={value} onSave={(v) => saveCell(r.id, c, v)} onCancel={() => setEditing(null)} className={c.type === "longtext" ? "absolute top-0 left-0 z-30 w-[24rem] shadow-lg" : undefined} />
                          ) : (
                            <CellView col={c} value={value} related={ctx.related} files={ctx.files} filesUrl={ctx.filesUrl} />
                          )}
                        </td>
                      );
                    })}
                  </tr>
                </Fragment>
              );
            })}
            {page.rows.length === 0 && (
              <tr>
                <td colSpan={shown.length + 1} className="px-4 py-10 text-center text-sm text-ink-3">
                  {nav.q || Object.keys(config.where ?? {}).length ? "No rows match." : nav.archived ? "Nothing archived." : "No rows yet."}
                </td>
              </tr>
            )}
          </tbody>
          {hasSums && page.rows.length > 0 && (
            <tfoot>
              <tr>
                <td className="sticky bottom-0 left-0 z-20 border-t border-r border-line bg-surface-2" />
                {shown.map((c, i) => (
                  <td
                    key={c.id}
                    style={{ left: i === 0 ? "3.5rem" : undefined }}
                    className={cx("sticky bottom-0 border-t border-line bg-surface-2 px-3 py-1.5 text-xs text-ink-3", i === 0 && "z-20 border-r", c.type === "number" && "text-right tabular-nums")}
                  >
                    {c.name in page.sums ? (
                      <>
                        <span className="mr-1">Sum</span>
                        <span className="text-ink-2">{display(c, page.sums[c.name])}</span>
                      </>
                    ) : i === 0 ? (
                      `${number(page.total)} ${page.total === 1 ? "row" : "rows"}`
                    ) : null}
                  </td>
                ))}
              </tr>
            </tfoot>
          )}
        </table>
      </div>

      {page.total > pageSize && (
        <div className="mt-3 flex items-center justify-end gap-2 text-sm text-ink-3">
          <span>
            {number(from)}–{number(to)} of {number(page.total)}
          </span>
          <button type="button" disabled={nav.offset === 0} onClick={() => ctx.go({ offset: Math.max(0, nav.offset - pageSize) })} className="rounded-lg border border-line p-1.5 hover:text-ink disabled:opacity-40" aria-label="Previous page">
            <ChevronLeft className="size-4" />
          </button>
          <button type="button" disabled={to >= page.total} onClick={() => ctx.go({ offset: nav.offset + pageSize })} className="rounded-lg border border-line p-1.5 hover:text-ink disabled:opacity-40" aria-label="Next page">
            <ChevronRight className="size-4" />
          </button>
        </div>
      )}
    </>
  );
}
