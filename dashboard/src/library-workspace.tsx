"use client";

import {
  Archive,
  ArrowDown,
  ArrowUp,
  Calendar as CalendarIcon,
  Columns3,
  Download,
  EyeOff,
  Filter,
  Layers,
  Loader2,
  MoreHorizontal,
  Plus,
  Search,
  Table2,
  Upload,
  X,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, useTransition } from "react";
import type { CellValue, LibraryColumn, LibraryFileInfo, LibraryPage, LibraryRow, LibraryRowDetail, LibraryView, LibraryViewConfig } from "./backend/types";
import type { DashboardActions } from "./host";
import { BoardView } from "./library-board";
import { CalendarView } from "./library-calendar";
import { ICONS, Menu, menuItem, number } from "./library-cells";
import { GridView } from "./library-grid";
import { RowPanel } from "./library-panel";
import { cx } from "./ui";

/** Where the owner is in a table: the view, the search, the page, the open row, the calendar's month. In the address. */
/** `where`: filters from the address (?where.<column>=value, as a dashboard's chart links), on top of the view's own. */
export type LibraryNav = { view: string; q: string; offset: number; row: string; month: string; archived: boolean; where: Record<string, string> };

/** What the server read for the current view. */
export type LibraryBody =
  | { kind: "grid"; page: LibraryPage }
  | { kind: "kanban"; by: string; lanes: { value: string | null; total: number; rows: LibraryRow[] }[] }
  | { kind: "calendar"; by: string; month: string; start: string; today: string; rows: LibraryRow[]; undated: number };

export type LibraryActions = Pick<DashboardActions, "saveLibraryRow" | "setLibraryRowArchived" | "saveLibraryView" | "deleteLibraryView" | "commentLibraryRow">;

/** What every view gets: the columns it shows, how to save a cell, and how to open a row. */
export type ViewContext = {
  columns: LibraryColumn[];
  shown: LibraryColumn[];
  config: LibraryViewConfig;
  related: Record<string, string>;
  files: Record<string, LibraryFileInfo>;
  filesUrl?: string;
  saveCell: (rowId: string, col: LibraryColumn, value: CellValue) => Promise<boolean>;
  addRow: (cells: Record<string, CellValue>) => Promise<void>;
  openRow: (rowId: string) => void;
  setConfig: (config: LibraryViewConfig) => void;
  go: (changes: Partial<LibraryNav>) => void;
  nav: LibraryNav;
  pageSize: number;
  readOnly: boolean;
};

const VIEW_ICON = { grid: Table2, kanban: Columns3, calendar: CalendarIcon } as const;
const VIEW_WORD = { grid: "Grid", kanban: "Board", calendar: "Calendar" } as const;

/**
 * One library table, after Teable: views as tabs (a grid, a board by a status, a calendar by a
 * date), each keeping its own filters, sort, grouping and hidden fields; a toolbar; import and
 * export; and a side panel for a row with its comments and history. Everything the owner changes
 * in a view's settings is saved to the view (so the team sees it too); the search, page and open
 * row live in the address.
 */
export function LibraryWorkspace({
  table,
  columns,
  views,
  view,
  related,
  files,
  total,
  body,
  nav,
  basePath,
  detail,
  cooName,
  now,
  pageSize,
  filesUrl,
  libraryFilesUrl,
  actions,
}: {
  table: { id: string; name: string };
  columns: LibraryColumn[];
  views: LibraryView[];
  view: LibraryView;
  related: Record<string, string>;
  files: Record<string, LibraryFileInfo>;
  total: number;
  body: LibraryBody;
  nav: LibraryNav;
  basePath: string;
  detail: LibraryRowDetail | null;
  cooName: string;
  now: number;
  pageSize: number;
  filesUrl?: string;
  libraryFilesUrl?: string;
  actions: LibraryActions;
}) {
  const router = useRouter();
  const [navigating, startNav] = useTransition();
  const [saving, startSave] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [search, setSearch] = useState(nav.q);
  const [renaming, setRenaming] = useState(false);
  const config = view.config;
  const hidden = config.hidden ?? [];
  const shown = columns.filter((c, i) => i === 0 || !hidden.includes(c.name));
  const readOnly = nav.archived && view.type === "grid";

  const go = (changes: Partial<LibraryNav>) => {
    const next = { ...nav, ...changes };
    const params = new URLSearchParams();
    if (next.view && next.view !== views[0]?.id) params.set("view", next.view);
    if (next.q) params.set("q", next.q);
    if (next.archived) params.set("archived", "1");
    if (next.offset) params.set("offset", String(next.offset));
    if (next.month) params.set("month", next.month);
    if (next.row) params.set("row", next.row);
    for (const [k, v] of Object.entries(next.where)) params.set(`where.${k}`, v);
    const qs = params.toString();
    startNav(() => router.push(qs ? `${basePath}?${qs}` : basePath, { scroll: false }));
  };

  useEffect(() => {
    if (search === nav.q) return;
    const t = setTimeout(() => go({ q: search, offset: 0 }), 350);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  function setConfig(next: LibraryViewConfig) {
    setError(null);
    startSave(async () => {
      const result = await actions.saveLibraryView(table.id, view.id, { config: next });
      if (result.error) setError(result.error);
      else if (nav.offset) go({ offset: 0 });
    });
  }

  async function saveCell(rowId: string, col: LibraryColumn, value: CellValue) {
    setError(null);
    const result = await actions.saveLibraryRow(table.id, rowId, { [col.name]: value });
    if (result.error) setError(result.error);
    return !result.error;
  }

  async function addRow(cells: Record<string, CellValue> = {}) {
    setAdding(true);
    setError(null);
    const result = await actions.saveLibraryRow(table.id, null, cells);
    setAdding(false);
    if (result.error) return setError(result.error);
    if (result.id) go({ row: result.id });
  }

  async function addView(type: LibraryView["type"]) {
    setError(null);
    const result = await actions.saveLibraryView(table.id, null, { type });
    if (result.error) return setError(result.error);
    if (result.id) go({ view: result.id, offset: 0, row: "", month: "", archived: false });
  }

  async function removeView() {
    if (!window.confirm(`Remove the view “${view.name}”? The rows stay; it's only a way of looking at them.`)) return;
    const result = await actions.deleteLibraryView(table.id, view.id);
    if (result.error) return setError(result.error);
    go({ view: views.find((v) => v.id !== view.id)?.id ?? "", offset: 0, row: "", month: "" });
  }

  const statusCols = columns.filter((c) => c.type === "status");
  const dateCols = columns.filter((c) => c.type === "date");
  const filterable = columns.filter((c) => c.type === "status" || c.type === "checkbox" || (c.type === "tags" && c.options.labels?.length));
  const groupable = columns.filter((c) => !["longtext", "tags", "files"].includes(c.type));
  const where = config.where ?? {};
  const filters = Object.entries(where);

  const exportHref = (format: "csv" | "xlsx") => {
    const params = new URLSearchParams({ table: table.id, format });
    if (nav.q) params.set("q", nav.q);
    if (config.sort) params.set("sort", config.sort);
    if (config.dir) params.set("dir", config.dir);
    if (nav.archived) params.set("archived", "1");
    for (const [k, v] of Object.entries({ ...where, ...nav.where })) params.set(`where.${k}`, v);
    return `${libraryFilesUrl}?${params}`;
  };

  const importInput = useRef<HTMLInputElement>(null);
  const [importing, setImporting] = useState(false);
  async function importInto(file: File | undefined) {
    if (!file || !libraryFilesUrl) return;
    setImporting(true);
    setError(null);
    const res = await fetch(`${libraryFilesUrl}?name=${encodeURIComponent(file.name)}&into=${encodeURIComponent(table.id)}`, { method: "POST", body: file }).catch(() => null);
    const got = await res?.json().catch(() => null);
    setImporting(false);
    if (importInput.current) importInput.current.value = "";
    if (!res?.ok) return setError(got?.error ?? "That file couldn't be imported. Try again.");
    setNotice(`Added ${number(got.added)} ${got.added === 1 ? "row" : "rows"}${got.skipped ? `. ${number(got.skipped)} ${got.skipped === 1 ? "value didn't" : "values didn't"} fit its column and ${got.skipped === 1 ? "was" : "were"} left empty` : ""}.`);
    router.refresh();
  }

  const ctx: ViewContext = {
    columns,
    shown,
    config,
    related,
    files,
    filesUrl,
    saveCell,
    addRow: (cells) => addRow(cells),
    openRow: (row) => go({ row }),
    setConfig,
    go,
    nav,
    pageSize,
    readOnly,
  };

  return (
    <div className="min-w-0">
      {/* Views, as tabs */}
      <div className="mb-3 flex items-end gap-1 overflow-x-auto border-b border-line">
        {views.map((v) => {
          const Icon = VIEW_ICON[v.type];
          const active = v.id === view.id;
          return (
            <div key={v.id} className={cx("-mb-px flex shrink-0 items-center rounded-t-lg border border-b-0", active ? "border-line bg-bg" : "border-transparent")}>
              {active && renaming ? (
                <form
                  className="px-2 py-1"
                  onSubmit={async (e) => {
                    e.preventDefault();
                    const name = String(new FormData(e.currentTarget).get("name") ?? "").trim();
                    setRenaming(false);
                    if (name && name !== v.name) {
                      const result = await actions.saveLibraryView(table.id, v.id, { name });
                      if (result.error) setError(result.error);
                    }
                  }}
                >
                  <input name="name" defaultValue={v.name} autoFocus onBlur={(e) => e.currentTarget.form?.requestSubmit()} className="w-36 rounded border border-accent bg-surface px-1.5 py-0.5 text-sm outline-none" />
                </form>
              ) : (
                <button
                  type="button"
                  onClick={() => !active && go({ view: v.id, offset: 0, row: "", month: "", archived: false })}
                  onDoubleClick={() => active && setRenaming(true)}
                  aria-current={active ? "page" : undefined}
                  className={cx("flex items-center gap-1.5 px-3 py-2 text-sm whitespace-nowrap", active ? "font-medium text-ink" : "text-ink-3 hover:text-ink")}
                >
                  <Icon className={cx("size-4", active && "text-accent")} aria-hidden />
                  {v.name}
                </button>
              )}
              {active && !renaming && (
                <Menu label={<MoreHorizontal className="size-4" aria-label="View options" />} align="left" className="px-1.5 py-1">
                  {(close) => (
                    <div>
                      <button type="button" className={menuItem} onClick={() => (setRenaming(true), close())}>
                        Rename
                      </button>
                      {views.length > 1 && (
                        <button type="button" className={cx(menuItem, "text-rose")} onClick={() => (close(), removeView())}>
                          Remove this view
                        </button>
                      )}
                    </div>
                  )}
                </Menu>
              )}
            </div>
          );
        })}
        <Menu label="Add view" icon={<Plus className="size-4" aria-hidden />} className="mb-1 shrink-0 text-ink-3">
          {(close) => (
            <div>
              {(["grid", "kanban", "calendar"] as const).map((type) => {
                const Icon = VIEW_ICON[type];
                const missing = type === "kanban" ? !statusCols.length : type === "calendar" ? !dateCols.length : false;
                return (
                  <button key={type} type="button" disabled={missing} className={cx(menuItem, "disabled:opacity-50")} onClick={() => (close(), addView(type))}>
                    <Icon className="size-4 text-ink-3" aria-hidden />
                    <span className="flex-1">{VIEW_WORD[type]}</span>
                    {missing && <span className="text-xs text-ink-3">needs a {type === "kanban" ? "status" : "date"} column</span>}
                  </button>
                );
              })}
            </div>
          )}
        </Menu>
      </div>

      {/* Toolbar */}
      <div className="mb-3 flex flex-wrap items-center gap-1">
        {!readOnly && (
          <button
            type="button"
            onClick={() => addRow()}
            disabled={adding}
            className="mr-1 inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-bg hover:bg-accent-hover disabled:opacity-70"
          >
            {adding ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Plus className="size-4" aria-hidden />}
            Add row
          </button>
        )}
        <label className="relative mr-1">
          <span className="sr-only">Search {table.name}</span>
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-ink-3" aria-hidden />
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search"
            className="w-40 rounded-lg border border-line bg-surface py-1.5 pr-2 pl-8 text-sm outline-none focus:border-accent sm:w-52"
            dir="auto"
          />
        </label>
        {view.type !== "grid" && (view.type === "kanban" ? statusCols : dateCols).length > 1 && (
          <Menu label={`By ${config.by}`} icon={view.type === "kanban" ? <Columns3 className="size-4" aria-hidden /> : <CalendarIcon className="size-4" aria-hidden />}>
            {(close) => (
              <div>
                {(view.type === "kanban" ? statusCols : dateCols).map((c) => (
                  <button key={c.id} type="button" className={cx(menuItem, config.by === c.name && "font-medium text-accent")} onClick={() => (close(), setConfig({ ...config, by: c.name }))}>
                    {c.name}
                  </button>
                ))}
              </div>
            )}
          </Menu>
        )}
        {filterable.length > 0 && (
          <Menu label="Filter" icon={<Filter className="size-4" aria-hidden />} active={filters.length > 0}>
            {(close) => (
              <div className="space-y-3 p-1">
                {filterable
                  .filter((c) => !(view.type === "kanban" && c.name === config.by))
                  .map((c) => (
                    <label key={c.id} className="block text-xs text-ink-3">
                      {c.name}
                      <select
                        value={where[c.name] ?? "*"}
                        onChange={(e) => {
                          const next = { ...where };
                          if (e.target.value === "*") delete next[c.name];
                          else next[c.name] = e.target.value;
                          setConfig({ ...config, where: next });
                          close();
                        }}
                        className="mt-1 block w-full rounded-md border border-line bg-surface px-2 py-1.5 text-sm text-ink"
                      >
                        <option value="*">Any</option>
                        {c.type === "checkbox" ? (
                          <>
                            <option value="yes">Yes</option>
                            <option value="no">No</option>
                          </>
                        ) : (
                          <>
                            {(c.options.labels ?? []).map((l) => (
                              <option key={l} value={l}>
                                {c.type === "tags" ? `Has ${l}` : l}
                              </option>
                            ))}
                            {c.type === "status" && <option value="">Empty</option>}
                          </>
                        )}
                      </select>
                    </label>
                  ))}
              </div>
            )}
          </Menu>
        )}
        {view.type !== "calendar" && (
          <Menu label="Sort" icon={config.dir === "desc" && config.sort ? <ArrowDown className="size-4" aria-hidden /> : <ArrowUp className="size-4" aria-hidden />} active={Boolean(config.sort)}>
            {(close) => (
              <div className="max-h-72 overflow-auto">
                <button type="button" onClick={() => (close(), setConfig({ ...config, sort: undefined, dir: undefined }))} className={cx(menuItem, !config.sort && "font-medium text-accent")}>
                  Newest first
                </button>
                {columns
                  .filter((c) => c.type !== "files")
                  .map((c) =>
                    (["asc", "desc"] as const).map((dir) => (
                      <button key={c.id + dir} type="button" onClick={() => (close(), setConfig({ ...config, sort: c.name, dir }))} className={cx(menuItem, config.sort === c.name && config.dir === dir && "font-medium text-accent")}>
                        {dir === "asc" ? <ArrowUp className="size-3.5" aria-hidden /> : <ArrowDown className="size-3.5" aria-hidden />}
                        {c.name}
                        <span className="ml-auto text-xs text-ink-3">
                          {dir === "asc" ? (c.type === "number" || c.type === "date" ? "low → high" : c.type === "status" ? "in order" : "A → Z") : c.type === "number" || c.type === "date" ? "high → low" : c.type === "status" ? "reversed" : "Z → A"}
                        </span>
                      </button>
                    )),
                  )}
              </div>
            )}
          </Menu>
        )}
        {view.type === "grid" && (
          <Menu label={config.group ? `Grouped by ${config.group}` : "Group"} icon={<Layers className="size-4" aria-hidden />} active={Boolean(config.group)}>
            {(close) => (
              <div className="max-h-72 overflow-auto">
                <button type="button" onClick={() => (close(), setConfig({ ...config, group: undefined }))} className={cx(menuItem, !config.group && "font-medium text-accent")}>
                  No groups
                </button>
                {groupable.map((c) => {
                  const Icon = ICONS[c.type];
                  return (
                    <button key={c.id} type="button" onClick={() => (close(), setConfig({ ...config, group: c.name }))} className={cx(menuItem, config.group === c.name && "font-medium text-accent")}>
                      <Icon className="size-3.5 text-ink-3" aria-hidden />
                      {c.name}
                    </button>
                  );
                })}
              </div>
            )}
          </Menu>
        )}
        <Menu label={hidden.length ? `${hidden.length} hidden` : view.type === "grid" ? "Fields" : "Card fields"} icon={<EyeOff className="size-4" aria-hidden />} active={hidden.length > 0}>
          {() => (
            <div className="max-h-72 space-y-0.5 overflow-auto">
              {columns.map((c, i) => {
                const Icon = ICONS[c.type];
                return (
                  <label key={c.id} className={cx("flex items-center gap-2 rounded-md px-2 py-1.5 text-sm", i === 0 ? "text-ink-3" : "hover:bg-surface-2")}>
                    <input
                      type="checkbox"
                      checked={i === 0 || !hidden.includes(c.name)}
                      disabled={i === 0}
                      onChange={() => setConfig({ ...config, hidden: hidden.includes(c.name) ? hidden.filter((h) => h !== c.name) : [...hidden, c.name] })}
                      className="accent-[var(--accent)]"
                    />
                    <Icon className="size-3.5 text-ink-3" aria-hidden />
                    {c.name}
                  </label>
                );
              })}
            </div>
          )}
        </Menu>
        {view.type === "grid" && (
          <button
            type="button"
            onClick={() => go({ archived: !nav.archived, offset: 0, row: "" })}
            className={cx("inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm hover:bg-surface-2", nav.archived ? "text-accent" : "text-ink-2")}
            aria-pressed={nav.archived}
          >
            <Archive className="size-4" aria-hidden />
            Archived
          </button>
        )}
        {libraryFilesUrl && (
          <Menu label="Spreadsheet" icon={importing ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Download className="size-4" aria-hidden />}>
            {(close) => (
              <div>
                <a href={exportHref("xlsx")} onClick={close} className={menuItem}>
                  <Download className="size-4 text-ink-3" aria-hidden /> Download as Excel
                </a>
                <a href={exportHref("csv")} onClick={close} className={menuItem}>
                  <Download className="size-4 text-ink-3" aria-hidden /> Download as CSV
                </a>
                <button type="button" className={menuItem} onClick={() => (close(), importInput.current?.click())}>
                  <Upload className="size-4 text-ink-3" aria-hidden /> Add rows from a file…
                </button>
              </div>
            )}
          </Menu>
        )}
        <input ref={importInput} type="file" accept=".csv,.xlsx,.tsv" className="sr-only" onChange={(e) => importInto(e.target.files?.[0])} />
        <span className="ml-auto flex items-center gap-2 text-sm text-ink-3">
          {(navigating || saving) && <Loader2 className="size-4 animate-spin" aria-label="Loading" />}
          {number(total)} {nav.archived && view.type === "grid" ? "archived " : ""}
          {total === 1 ? "row" : "rows"}
        </span>
      </div>

      {filters.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-1.5">
          {filters.map(([k, v]) => (
            <button
              key={k}
              type="button"
              onClick={() => {
                const next = { ...where };
                delete next[k];
                setConfig({ ...config, where: next });
              }}
              className="inline-flex items-center gap-1 rounded-full bg-accent-soft px-2.5 py-1 text-xs text-ink"
            >
              {k}: {v === "" ? "Empty" : v} <X className="size-3" aria-label="Remove filter" />
            </button>
          ))}
        </div>
      )}

      {Object.keys(nav.where).length > 0 && (
        <p className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink-2">
          <span>
            Only rows where{" "}
            {Object.entries(nav.where).map(([k, v], i) => (
              <span key={k}>
                {i > 0 && " and "}
                <strong className="font-medium text-ink">{k}</strong> is <strong className="font-medium text-ink">{v === "" ? "empty" : v}</strong>
              </span>
            ))}
          </span>
          <button type="button" onClick={() => go({ where: {}, offset: 0 })} className="font-medium text-accent hover:underline">
            Show all
          </button>
        </p>
      )}

      {notice && (
        <p className="mb-3 flex items-start gap-2 rounded-lg bg-accent-soft px-3 py-2 text-sm text-ink">
          <span className="flex-1">{notice}</span>
          <button type="button" onClick={() => setNotice(null)} aria-label="Dismiss">
            <X className="size-4" />
          </button>
        </p>
      )}
      {error && (
        <p role="alert" className="mb-3 flex items-start gap-2 rounded-lg bg-rose-soft px-3 py-2 text-sm text-rose">
          <span className="flex-1">{error}</span>
          <button type="button" onClick={() => setError(null)} aria-label="Dismiss">
            <X className="size-4" />
          </button>
        </p>
      )}

      <div className={cx((navigating || saving) && "opacity-70 transition-opacity")}>
        {body.kind === "grid" && <GridView ctx={ctx} page={body.page} openId={detail?.id} />}
        {body.kind === "kanban" && <BoardView key={view.id} ctx={ctx} by={body.by} lanes={body.lanes} />}
        {body.kind === "calendar" && <CalendarView key={`${view.id}:${body.month}`} ctx={ctx} by={body.by} month={body.month} start={body.start} today={body.today} rows={body.rows} undated={body.undated} />}
      </div>

      {detail && (
        <RowPanel
          key={`${detail.id}:${detail.updated}`}
          detail={detail}
          columns={columns}
          related={related}
          cooName={cooName}
          now={now}
          filesUrl={filesUrl}
          onClose={() => go({ row: "" })}
          onSave={async (cells) => {
            const result = await actions.saveLibraryRow(table.id, detail.id, cells);
            return result.error ?? null;
          }}
          onArchive={async (archived) => {
            const result = await actions.setLibraryRowArchived(table.id, detail.id, archived);
            if (result.error) setError(result.error);
            else go({ row: "" });
          }}
          onComment={async (text, ask) => (await actions.commentLibraryRow(table.id, detail.id, text, ask)).error ?? null}
        />
      )}
    </div>
  );
}
