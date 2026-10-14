import { AgentError } from "./agent";
import type {
  CellValue,
  FileContent,
  LibraryColumn,
  LibraryComment,
  LibraryPage,
  LibraryQuery,
  LibraryRow,
  LibraryRowDetail,
  LibraryTableSummary,
  LibraryView,
  LibraryViewConfig,
} from "./types";

/** The sample company's library, in memory: what library.py keeps in library.db for a real one. */
type Table = {
  id: string;
  name: string;
  description: string;
  updated: string;
  columns: LibraryColumn[];
  rows: LibraryRowDetail[];
  views: LibraryView[];
  comments: Record<string, LibraryComment[]>;
};

const allRows = (): LibraryView => ({ id: `v_${Math.random().toString(36).slice(2, 8)}`, name: "All rows", type: "grid", config: {} });

const col = (name: string, type: LibraryColumn["type"], options: LibraryColumn["options"] = {}): LibraryColumn => ({
  id: `c_${name.toLowerCase().replace(/\W+/g, "_")}`,
  name,
  type,
  options,
});

export function sampleLibrary(now: number): Table[] {
  const day = 86_400_000;
  const at = (days: number) => new Date(now - days * day).toISOString();
  const row = (id: string, days: number, cells: Record<string, CellValue>, who: "you" | "coo" | "autopilot" = "autopilot"): LibraryRowDetail => ({
    id,
    key: null,
    created: at(days),
    updated: at(days),
    archived: false,
    cells,
    history: [{ who, what: "Added it", at: at(days) }],
    comments: [],
    files: {},
  });
  return [
    {
      id: "t_cafes",
      name: "Cafes",
      description: "Cafes that buy from you wholesale",
      updated: at(2),
      columns: [col("Name", "text"), col("Contact", "person"), col("Website", "link"), col("Status", "status", { labels: ["Active", "Quiet", "Lost"] }), col("Monthly order", "number", { unit: "$" })],
      views: [allRows()],
      comments: {},
      rows: [
        row("r_luna", 40, { Name: "Café Luna", Contact: "Dana", Website: "https://cafeluna.example", Status: "Active", "Monthly order": 640 }),
        row("r_bean", 35, { Name: "The Bean Room", Contact: "Omar", Website: null, Status: "Quiet", "Monthly order": 210 }),
        row("r_leaf", 20, { Name: "Green Leaf", Contact: "Priya", Website: "https://greenleaf.example", Status: "Active", "Monthly order": 480 }, "coo"),
      ],
    },
    {
      id: "t_leads",
      name: "Leads",
      description: "Shops and offices that might buy plants",
      updated: at(1),
      columns: [
        col("Name", "text"),
        col("Status", "status", { labels: ["New", "Contacted", "Won", "Lost"] }),
        col("Value", "number", { unit: "$" }),
        col("Next step", "date"),
        col("Asked for a sample", "checkbox"),
        col("Notes", "longtext"),
        col("Cafe", "relation", { table: "Cafes" }),
        col("Tags", "tags"),
      ],
      views: [
        allRows(),
        { id: "v_pipeline", name: "Pipeline", type: "kanban", config: { by: "Status" } },
        { id: "v_followups", name: "Follow-ups", type: "calendar", config: { by: "Next step" } },
      ],
      comments: {},
      rows: [
        row("r_a", 6, { Name: "Northside Bakery", Status: "New", Value: 800, "Next step": at(-2).slice(0, 10), "Asked for a sample": false, Notes: null, Cafe: null }),
        row("r_b", 5, { Name: "Harbor Dental", Status: "Contacted", Value: 1200, "Next step": at(-1).slice(0, 10), "Asked for a sample": true, Notes: "Wants low-light plants for the waiting room.", Cafe: null }),
        row("r_c", 3, { Name: "Luna's second shop", Status: "Won", Value: 950, "Next step": null, "Asked for a sample": true, Notes: null, Cafe: "r_luna" }, "coo"),
        row("r_d", 1, { Name: "Riverside Gym", Status: "Lost", Value: 400, "Next step": null, "Asked for a sample": false, Notes: "Went with a cheaper supplier.", Cafe: null }),
      ],
    },
  ];
}

function check(column: LibraryColumn, value: CellValue): CellValue {
  if (value === null || value === "") return null;
  if (column.type === "number") {
    const n = Number(String(value).replace(/[,$]/g, ""));
    if (Number.isNaN(n)) throw new AgentError(`${column.name} takes a number, not “${value}”.`, 400);
    return n;
  }
  if (column.type === "status") {
    const label = column.options.labels?.find((l) => l.toLowerCase() === String(value).toLowerCase());
    if (!label) throw new AgentError(`${column.name} is one of ${column.options.labels?.join(", ")}, not “${value}”.`, 400);
    return label;
  }
  if (column.type === "checkbox") return value === true || value === "true";
  if (column.type === "tags") {
    const list = (Array.isArray(value) ? value : String(value).split(",")).map((x) => x.trim()).filter(Boolean);
    return list.length ? [...new Set(list)] : null;
  }
  if (column.type === "files") throw new AgentError("The sample company doesn't keep files.", 400);
  if (column.type === "link" && !/^https?:\/\/\S+$/.test(String(value))) throw new AgentError(`${column.name} takes a web address starting with https://, not “${value}”.`, 400);
  if (column.type === "date" && !/^\d{4}-\d{2}-\d{2}$/.test(String(value))) throw new AgentError(`${column.name} takes a date as YYYY-MM-DD, not “${value}”.`, 400);
  return String(value);
}

export function libraryOps(tables: () => Table[]) {
  const find = (ref: string) => tables().find((t) => t.id === ref || t.name.toLowerCase() === ref.toLowerCase());
  const plain = (row: LibraryRowDetail): LibraryRow => {
    const copy: Partial<LibraryRowDetail> = { ...row };
    delete copy.history;
    delete copy.comments;
    delete copy.files;
    return copy as LibraryRow;
  };
  return {
    async library(): Promise<LibraryTableSummary[]> {
      return [...tables()]
        .sort((a, b) => b.updated.localeCompare(a.updated))
        .map((t) => ({ id: t.id, name: t.name, description: t.description, updated: t.updated, rows: t.rows.filter((r) => !r.archived).length, columns: t.columns.map((c) => c.name) }));
    },
    async libraryTable(tableId: string, query: LibraryQuery = {}): Promise<LibraryPage | null> {
      const t = find(tableId);
      if (!t) return null;
      let rows = t.rows.filter((r) => r.archived === Boolean(query.archived));
      for (const word of (query.q ?? "").toLowerCase().split(/\s+/).filter(Boolean)) {
        rows = rows.filter((r) => Object.values(r.cells).some((v) => typeof v === "string" && v.toLowerCase().includes(word)));
      }
      for (const [name, value] of Object.entries(query.where ?? {})) {
        rows = rows.filter((r) => {
          const cell = r.cells[name];
          if (Array.isArray(cell)) return cell.some((x) => x.toLowerCase() === value.toLowerCase());
          if (typeof cell === "boolean") return cell === ["yes", "true", "1"].includes(value.toLowerCase());
          return String(cell ?? "").toLowerCase() === value.toLowerCase();
        });
      }
      if (query.between) {
        const [name, from, to] = query.between;
        rows = rows.filter((r) => typeof r.cells[name] === "string" && (r.cells[name] as string) >= from && (r.cells[name] as string) <= to);
      }
      const sortCol = t.columns.find((c) => c.name.toLowerCase() === query.sort?.toLowerCase());
      rows = [...rows].sort((a, b) => b.created.localeCompare(a.created));
      if (sortCol) {
        const rank = (v: CellValue) => (sortCol.type === "status" ? (sortCol.options.labels ?? []).indexOf(String(v)) : v);
        rows.sort((a, b) => {
          const x = a.cells[sortCol.name], y = b.cells[sortCol.name];
          if (x == null || y == null) return x == null ? (y == null ? 0 : 1) : -1;
          const [p, q] = [rank(x), rank(y)];
          const diff = typeof p === "number" && typeof q === "number" ? p - q : String(p).localeCompare(String(q));
          return query.dir === "desc" ? -diff : diff;
        });
      }
      const groupCol = t.columns.find((c) => c.name.toLowerCase() === query.group?.toLowerCase());
      const groups: { value: CellValue; count: number }[] = [];
      if (groupCol) {
        const rank = (v: CellValue) => (v == null ? Infinity : groupCol.type === "status" ? (groupCol.options.labels ?? []).indexOf(String(v)) : 0);
        rows.sort((a, b) => rank(a.cells[groupCol.name]) - rank(b.cells[groupCol.name]) || String(a.cells[groupCol.name] ?? "").localeCompare(String(b.cells[groupCol.name] ?? "")));
        for (const r of rows) {
          const v = r.cells[groupCol.name] ?? null;
          const last = groups[groups.length - 1];
          if (last && last.value === v) last.count++;
          else groups.push({ value: v, count: 1 });
        }
      }
      const sums: Record<string, number> = {};
      for (const c of t.columns.filter((c) => c.type === "number")) sums[c.name] = rows.reduce((s, r) => s + (Number(r.cells[c.name]) || 0), 0);
      const related: Record<string, string> = {};
      for (const other of tables()) for (const r of other.rows) related[r.id] = String(Object.values(r.cells)[0] ?? "");
      const offset = query.offset ?? 0;
      return {
        table: { id: t.id, name: t.name, description: t.description },
        columns: t.columns,
        views: t.views,
        total: rows.length,
        rows: rows.slice(offset, offset + (query.limit ?? 100)).map(plain),
        sums,
        related,
        groups,
        files: {},
      };
    },
    async libraryRow(tableId: string, rowId: string): Promise<LibraryRowDetail | null> {
      const t = find(tableId);
      const row = t?.rows.find((r) => r.id === rowId);
      return t && row ? { ...row, comments: t.comments[rowId] ?? [], files: {} } : null;
    },
    async saveLibraryView(tableId: string, viewId: string | null, view: { name?: string; type?: LibraryView["type"]; config?: LibraryViewConfig }): Promise<LibraryView> {
      const t = find(tableId);
      if (!t) throw new AgentError("There's no such table.", 404);
      const existing = t.views.find((v) => v.id === viewId);
      const type = existing?.type ?? view.type ?? "grid";
      const config = { ...(existing?.config ?? {}), ...(view.config ?? {}) };
      const want = type === "kanban" ? "status" : type === "calendar" ? "date" : null;
      if (want && !t.columns.some((c) => c.name === config.by && c.type === want)) {
        const by = t.columns.find((c) => c.type === want);
        if (!by) throw new AgentError(`A ${type === "kanban" ? "board" : "calendar"} needs a ${want} column, and ${t.name} has none.`, 400);
        config.by = by.name;
      }
      if (existing) return Object.assign(existing, { name: view.name?.trim() || existing.name, config });
      const made: LibraryView = { id: `v_${Math.random().toString(36).slice(2, 8)}`, name: view.name?.trim() || { grid: "Grid", kanban: "Board", calendar: "Calendar" }[type], type, config };
      t.views.push(made);
      return made;
    },
    async deleteLibraryView(tableId: string, viewId: string) {
      const t = find(tableId);
      if (!t || t.views.length <= 1) throw new AgentError("A table keeps at least one view.", 400);
      t.views = t.views.filter((v) => v.id !== viewId);
    },
    async commentLibraryRow(tableId: string, rowId: string, text: string, ask: boolean): Promise<LibraryComment> {
      const t = find(tableId);
      if (!t?.rows.some((r) => r.id === rowId)) throw new AgentError("There's no such row.", 404);
      const now = new Date().toISOString();
      const made: LibraryComment = { id: `m_${Math.random().toString(36).slice(2, 8)}`, who: "you", text, at: now, ask, status: ask ? "answered" : null };
      const list = (t.comments[rowId] ??= []);
      list.push(made);
      if (ask) list.push({ id: `m_${Math.random().toString(36).slice(2, 8)}`, who: "coo", text: "This is the sample company, so I can't act on it, but in yours I would.", at: now, ask: false, status: null });
      return made;
    },
    async exportLibraryTable(tableId: string, query: LibraryQuery): Promise<FileContent> {
      const page = await this.libraryTable(tableId, { ...query, limit: 100_000 });
      if (!page) throw new AgentError("There's no such table.", 404);
      const quote = (v: CellValue | undefined) => `"${String(Array.isArray(v) ? v.join(", ") : (v ?? "")).replace(/"/g, '""')}"`;
      const lines = [page.columns.map((c) => quote(c.name)).join(","), ...page.rows.map((r) => page.columns.map((c) => quote(r.cells[c.name])).join(","))];
      return { data: new TextEncoder().encode("\ufeff" + lines.join("\n")).buffer as ArrayBuffer, contentType: "text/csv; charset=utf-8", disposition: `attachment; filename="${page.table.name}.csv"` };
    },
    async importLibrary(name: string, data: ArrayBuffer, options: { into?: string; title?: string } = {}) {
      if (!/\.csv$/i.test(name)) throw new AgentError("The sample company imports .csv files only.", 400);
      const [head, ...lines] = new TextDecoder().decode(data).replace(/^\ufeff/, "").split(/\r?\n/).filter((l) => l.trim());
      if (!head) throw new AgentError("That file is empty.", 400);
      const names = head.split(",").map((h, i) => h.trim() || `Column ${i + 1}`);
      const target = options.into ? find(options.into) : undefined;
      const t: Table = target ?? {
        id: `t_${Math.random().toString(36).slice(2, 8)}`,
        name: options.title || name.replace(/\.csv$/i, ""),
        description: `Imported from ${name}`,
        updated: new Date().toISOString(),
        columns: names.map((n) => col(n, "text")),
        rows: [],
        views: [allRows()],
        comments: {},
      };
      if (!target) tables().push(t);
      for (const line of lines) {
        const values = line.split(",");
        const cells: Record<string, CellValue> = {};
        names.forEach((n, i) => t.columns.some((c) => c.name === n) && values[i]?.trim() && (cells[n] = values[i].trim()));
        await this.saveLibraryRow(t.id, null, cells);
      }
      return { table: { id: t.id, name: t.name }, added: lines.length, skipped: 0 };
    },
    async saveLibraryRow(tableId: string, rowId: string | null, cells: Record<string, CellValue>): Promise<LibraryRow> {
      const t = find(tableId);
      if (!t) throw new AgentError("There's no such table.", 404);
      const values: Record<string, CellValue> = {};
      for (const [name, value] of Object.entries(cells)) {
        const column = t.columns.find((c) => c.name.toLowerCase() === name.toLowerCase());
        if (!column) throw new AgentError(`${t.name} has no column ${name}.`, 400);
        values[column.name] = check(column, value);
      }
      const now = new Date().toISOString();
      t.updated = now;
      if (!rowId) {
        const status = t.columns.find((c) => c.type === "status");
        if (status && values[status.name] == null) values[status.name] = status.options.labels?.[0] ?? null;
        const row: LibraryRowDetail = { id: `r_${Math.random().toString(36).slice(2, 10)}`, key: null, created: now, updated: now, archived: false, cells: values, history: [{ who: "you", what: "Added it", at: now }], comments: [], files: {} };
        t.rows.push(row);
        return plain(row);
      }
      const row = t.rows.find((r) => r.id === rowId);
      if (!row) throw new AgentError(`${t.name} has no row ${rowId}.`, 404);
      const changes = Object.entries(values).filter(([k, v]) => row.cells[k] !== v);
      if (changes.length) {
        Object.assign(row.cells, values);
        row.updated = now;
        row.history.unshift({ who: "you", what: changes.map(([k, v]) => (v === null ? `Cleared ${k}` : `Set ${k} to ${v}`)).join("; "), at: now });
      }
      return plain(row);
    },
    async setLibraryRowArchived(tableId: string, rowId: string, archived: boolean) {
      const row = find(tableId)?.rows.find((r) => r.id === rowId);
      if (!row) throw new AgentError("There's no such row.", 404);
      row.archived = archived;
      row.history.unshift({ who: "you", what: archived ? "Archived it" : "Brought it back", at: new Date().toISOString() });
    },
  };
}
