"use client";

import { ChevronDown, Loader2, Table2 } from "lucide-react";
import { useState } from "react";
import type { CellValue, RunChanges as RunChangesData, TableChanges } from "./backend/types";
import { cx } from "./ui";

type Page = NonNullable<RunChangesData["table"]>;

const WORDS: [keyof TableChanges, string][] = [
  ["added", "new"],
  ["changed", "updated"],
  ["archived", "archived"],
  ["restored", "brought back"],
];

function countWords(t: TableChanges) {
  return WORDS.filter(([k]) => t[k]).map(([k, word]) => `${(t[k] as number).toLocaleString()} ${word}`).join(", ");
}

function total(t: TableChanges) {
  return (t.added ?? 0) + (t.changed ?? 0) + (t.archived ?? 0) + (t.restored ?? 0);
}

const MARK = {
  added: { sign: "+", label: "New", row: "bg-accent-soft/50", sign_: "text-accent" },
  changed: { sign: "~", label: "Updated", row: "", sign_: "text-amber" },
  archived: { sign: "−", label: "Archived", row: "text-ink-3 line-through", sign_: "text-rose" },
  restored: { sign: "↺", label: "Brought back", row: "", sign_: "text-sky" },
} as const;

function show(value: CellValue | undefined, type: string): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return value.toLocaleString();
  if (Array.isArray(value)) return value.join(", ");
  if (type === "link") return value.replace(/^https?:\/\/(www\.)?/, "").slice(0, 60);
  return value.length > 80 ? `${value.slice(0, 79)}…` : value;
}

/**
 * What a routine run or chat turn changed in the library: counts per table, and with the host's
 * runChangesUrl, a table of the rows themselves (new, updated cells from → to, archived), loaded a
 * page at a time so a run that touched thousands of rows stays quick.
 */
export function RunChanges({ run, changes, url }: { run?: string; changes: TableChanges[]; url?: string }) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(changes[0]?.tableId);
  const [pages, setPages] = useState<Record<string, Page>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!changes.length) return null;
  const summary = changes.map((t) => `${countWords(t)} in ${t.table}`).join(" · ");
  const canOpen = Boolean(run && url);

  async function load(tableId: string, after?: number) {
    if (!run || !url) return;
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ run, table: tableId, limit: after ? "100" : "50" });
      if (after) params.set("after", String(after));
      const res = await fetch(`${url}?${params}`, { cache: "no-store" });
      const data = (await res.json()) as RunChangesData & { error?: string };
      if (!res.ok || !data.table) throw new Error(data.error ?? "These changes couldn't be loaded.");
      const page = data.table;
      setPages((all) => ({
        ...all,
        [tableId]: after && all[tableId] ? { ...page, rows: [...all[tableId].rows, ...page.rows] } : page,
      }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "These changes couldn't be loaded.");
    } finally {
      setLoading(false);
    }
  }

  function toggle() {
    const next = !open;
    setOpen(next);
    if (next && active && !pages[active]) void load(active);
  }

  function pick(tableId: string) {
    setActive(tableId);
    if (!pages[tableId]) void load(tableId);
  }

  if (!canOpen) {
    return (
      <p className="mt-1 flex items-center gap-1.5 text-xs text-ink-3">
        <Table2 className="size-3.5 shrink-0" aria-hidden /> {summary}
      </p>
    );
  }

  const page = active ? pages[active] : undefined;
  const count = changes.find((t) => t.tableId === active);
  return (
    <div className="mt-1 min-w-0">
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        className="flex items-center gap-1.5 rounded text-left text-xs text-ink-2 hover:text-ink"
      >
        <Table2 className="size-3.5 shrink-0" aria-hidden />
        <span>{summary}</span>
        <ChevronDown className={cx("size-3.5 shrink-0 transition-transform", open && "rotate-180")} aria-hidden />
      </button>
      {open && (
        <div className="mt-3">
          {changes.length > 1 && (
            <div className="mb-2 flex flex-wrap gap-1.5" role="tablist" aria-label="Tables">
              {changes.map((t) => (
                <button
                  key={t.tableId}
                  type="button"
                  role="tab"
                  aria-selected={t.tableId === active}
                  onClick={() => pick(t.tableId)}
                  className={cx(
                    "rounded-full border px-2.5 py-1 text-xs",
                    t.tableId === active ? "border-accent bg-accent-soft text-ink" : "border-line text-ink-2 hover:text-ink",
                  )}
                >
                  {t.table} <span className="text-ink-3">{total(t).toLocaleString()}</span>
                </button>
              ))}
            </div>
          )}
          {error && (
            <p role="alert" className="text-xs text-rose">
              {error}
            </p>
          )}
          {!page && loading && (
            <p className="flex items-center gap-2 text-xs text-ink-3">
              <Loader2 className="size-3.5 animate-spin" aria-hidden /> Loading what changed…
            </p>
          )}
          {page && !page.details && (
            <p className="mb-2 text-xs text-ink-3">Only the last 90 days keep what each value was before, so older runs show their rows as they are now.</p>
          )}
          {page && (
            <>
              <div className="max-h-[28rem] overflow-auto rounded-xl border border-line">
                <table className="w-full min-w-max border-collapse text-left text-xs">
                  <caption className="sr-only">What changed in {page.name}</caption>
                  <thead className="sticky top-0 z-[1] bg-surface-2 text-ink-2">
                    <tr>
                      <th scope="col" className="w-8 px-2 py-2 font-medium">
                        <span className="sr-only">Change</span>
                      </th>
                      {page.columns.map((c) => (
                        <th key={c.name} scope="col" className="px-3 py-2 font-medium whitespace-nowrap">
                          {c.name}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {page.rows.map((r) => {
                      const m = MARK[r.change];
                      return (
                        <tr key={r.id} className={m.row}>
                          <td className={cx("px-2 py-2 text-center font-semibold no-underline", m.sign_)} title={m.label}>
                            <span aria-hidden>{m.sign}</span>
                            <span className="sr-only">{m.label}</span>
                          </td>
                          {page.columns.map((c) => {
                            const cell = r.cells[c.name];
                            const changed = cell && "before" in cell;
                            const full = typeof cell?.value === "string" ? cell.value : undefined;
                            return (
                              <td key={c.name} dir="auto" className="max-w-[18rem] px-3 py-2 text-start align-top" title={full && full.length > 80 ? full : undefined}>
                                {changed ? (
                                  <span className="inline-flex flex-wrap items-baseline gap-x-1.5">
                                    <span className="text-rose line-through">
                                      <span className="sr-only">was </span>
                                      {show(cell.before, c.type)}
                                    </span>
                                    <span aria-hidden className="text-ink-3">
                                      →
                                    </span>
                                    <span className="font-medium text-ink">
                                      <span className="sr-only">now </span>
                                      {show(cell.value, c.type)}
                                    </span>
                                  </span>
                                ) : c.type === "link" && typeof cell?.value === "string" && /^https?:\/\//.test(cell.value) ? (
                                  <a href={cell.value} target="_blank" rel="noopener noreferrer" className="text-ink-2 underline decoration-line underline-offset-2 hover:text-ink">
                                    {show(cell.value, c.type)}
                                  </a>
                                ) : (
                                  <span className={r.change === "changed" ? "text-ink-3" : undefined}>{show(cell?.value, c.type)}</span>
                                )}
                              </td>
                            );
                          })}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <div className="mt-2 flex items-center gap-3 text-xs text-ink-3">
                <span>
                  {page.rows.length.toLocaleString()} of {(count ? total(count) : page.rows.length).toLocaleString()} rows
                </span>
                {page.next !== null && (
                  <button
                    type="button"
                    disabled={loading}
                    onClick={() => active && load(active, page.next ?? undefined)}
                    className="inline-flex items-center gap-1.5 rounded-full border border-line px-2.5 py-1 text-ink-2 hover:border-accent hover:text-ink disabled:opacity-70"
                  >
                    {loading && <Loader2 className="size-3 animate-spin" aria-hidden />}
                    Show more
                  </button>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
