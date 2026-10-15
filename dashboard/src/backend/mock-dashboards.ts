import { AgentError } from "./agent";
import type { sampleLibrary } from "./mock-library";
import type {
  CellValue,
  DashboardAsk,
  DashboardDetail,
  DashboardSummary,
  DashboardWidget,
  DashboardWidgetData,
  DashboardWidgetSpec,
} from "./types";

/** The sample company's dashboards, in memory, counted over its sample library like dashboards.py would. */
type Table = ReturnType<typeof sampleLibrary>[number];
type Stored = Omit<DashboardSummary, "widgets" | "titles"> & { widgets: (DashboardWidgetSpec & { id: string; title: string })[] };

const newId = (prefix: string) => `${prefix}${Math.random().toString(16).slice(2, 10).padEnd(8, "0")}`;

export function sampleDashboards(now: number): Stored[] {
  const at = new Date(now - 3 * 86_400_000).toISOString();
  return [
    {
      id: "db5a1e5c0d",
      name: "Sales at a glance",
      description: "Leads and cafes, for the Monday check-in",
      createdAt: at,
      updatedAt: at,
      updatedBy: "coo",
      widgets: [
        { id: "w00000001", type: "number", title: "Open leads", table: "t_leads", where: { Status: "New" }, measure: "count" },
        { id: "w00000002", type: "number", title: "Won so far", table: "t_leads", where: { Status: "Won" }, measure: "sum", column: "Value" },
        { id: "w00000003", type: "progress", title: "Active cafes, goal 12", table: "t_cafes", where: { Status: "Active" }, measure: "count", goal: 12 },
        { id: "w00000004", type: "bars", title: "Leads by status", table: "t_leads", by: "Status", measure: "count", limit: 8 },
        { id: "w00000005", type: "trend", title: "Leads added per week", table: "t_leads", date: "added", every: "week", last: 8, measure: "count", wide: true },
        { id: "w00000006", type: "list", title: "Biggest cafes", table: "t_cafes", sort: "Monthly order", dir: "desc", limit: 5, show: ["Name", "Status", "Monthly order"], wide: true },
      ],
    },
  ];
}

function rowsOf(t: Table, where: Record<string, string> = {}) {
  return t.rows.filter(
    (r) =>
      !r.archived &&
      Object.entries(where).every(([col, want]) => {
        const v = r.cells[col];
        if (want === "") return v === null || v === undefined || (Array.isArray(v) && v.length === 0);
        if (Array.isArray(v)) return v.some((x) => x.toLowerCase() === want.toLowerCase());
        if (typeof v === "boolean") return v === ["1", "true", "yes"].includes(want.toLowerCase());
        return String(v ?? "").toLowerCase() === want.toLowerCase();
      }),
  );
}

function measure(rows: Table["rows"], w: DashboardWidgetSpec): number | null {
  if (!w.measure || w.measure === "count") return rows.length;
  const nums = rows.map((r) => r.cells[w.column ?? ""]).filter((v): v is number => typeof v === "number");
  if (w.measure === "sum") return nums.reduce((a, b) => a + b, 0);
  if (!nums.length) return null;
  if (w.measure === "average") return nums.reduce((a, b) => a + b, 0) / nums.length;
  return w.measure === "min" ? Math.min(...nums) : Math.max(...nums);
}

const dayOf = (r: Table["rows"][number], w: DashboardWidgetSpec) =>
  w.date === "added" || !w.date ? r.created.slice(0, 10) : typeof r.cells[w.date] === "string" ? (r.cells[w.date] as string) : null;

function bucket(every: string, day: Date): Date {
  const d = new Date(Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate()));
  if (every === "week") d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7));
  if (every === "month") d.setUTCDate(1);
  return d;
}

function step(every: string, day: Date, n: number): Date {
  const d = new Date(day);
  if (every === "day") d.setUTCDate(d.getUTCDate() + n);
  else if (every === "week") d.setUTCDate(d.getUTCDate() + 7 * n);
  else d.setUTCMonth(d.getUTCMonth() + n);
  return d;
}

function compute(t: Table, w: DashboardWidgetSpec): DashboardWidgetData {
  const rows = rowsOf(t, w.where);
  const unit = w.measure && w.measure !== "count" ? t.columns.find((c) => c.name === w.column)?.options.unit : undefined;
  const out: DashboardWidgetData = unit ? { unit } : {};
  if (w.type === "number" || w.type === "progress") {
    out.value = measure(rows, w);
    if (w.type === "progress") out.goal = w.goal;
    return out;
  }
  if (w.type === "trend") {
    const every = w.every ?? "week";
    const last = w.last ?? 8;
    const end = bucket(every, new Date());
    const start = step(every, end, -(last - 1));
    out.points = Array.from({ length: last }, (_, i) => {
      const from = step(every, start, i);
      const to = step(every, from, 1);
      const inside = rows.filter((r) => {
        const d = dayOf(r, w);
        return d !== null && d >= from.toISOString().slice(0, 10) && d < to.toISOString().slice(0, 10);
      });
      return { start: from.toISOString().slice(0, 10), value: measure(inside, w) };
    });
    return out;
  }
  if (w.type === "bars") {
    const col = t.columns.find((c) => c.name === w.by);
    const groups = new Map<string, Table["rows"]>();
    for (const r of rows) {
      const v = r.cells[w.by ?? ""];
      for (const key of Array.isArray(v) ? v : [v === null || v === undefined ? "" : String(v)]) groups.set(key, [...(groups.get(key) ?? []), r]);
    }
    const labels = col?.options.labels ?? [];
    const keys = [...groups.keys()].sort((a, b) => (labels.length ? labels.indexOf(a) - labels.indexOf(b) : groups.get(b)!.length - groups.get(a)!.length));
    out.by = w.by;
    out.items = keys.slice(0, w.limit ?? 8).map((k) => ({ label: k || `No ${(w.by ?? "").toLowerCase()}`, value: measure(groups.get(k)!, w), filter: k }));
    if (keys.length > (w.limit ?? 8)) out.more = keys.length - (w.limit ?? 8);
    return out;
  }
  const show = w.show ?? t.columns.slice(0, 3).map((c) => c.name);
  const sorted = [...rows].sort((a, b) => {
    if (!w.sort) return b.created.localeCompare(a.created);
    const x = a.cells[w.sort] as CellValue;
    const y = b.cells[w.sort] as CellValue;
    const order = typeof x === "number" && typeof y === "number" ? x - y : String(x ?? "").localeCompare(String(y ?? ""));
    return w.dir === "asc" ? order : -order;
  });
  out.columns = show.map((name) => {
    const c = t.columns.find((col) => col.name === name);
    return { name, type: c?.type ?? "text", ...(c?.options.unit ? { unit: c.options.unit } : {}) };
  });
  out.rows = sorted.slice(0, w.limit ?? 5).map((r) => ({ id: r.id, cells: Object.fromEntries(show.map((n) => [n, r.cells[n] ?? null])) }));
  out.total = rows.length;
  out.related = {};
  return out;
}

export function dashboardOps(library: () => Table[], stored: () => Stored[], asks: () => DashboardAsk[]) {
  const find = (id: string) => {
    const d = stored().find((x) => x.id === id);
    if (!d) throw new AgentError("There's no such dashboard.", 404);
    return d;
  };
  const table = (ref: string) => library().find((t) => t.id === ref || t.name.toLowerCase() === ref.toLowerCase());
  const summary = (d: Stored): DashboardSummary => ({ ...d, widgets: d.widgets.length, titles: d.widgets.map((w) => w.title).slice(0, 6) });
  const clean = (spec: DashboardWidgetSpec, id: string) => {
    const t = table(spec.table);
    if (!t) throw new AgentError(`There's no table called ${spec.table}.`, 400);
    return { ...spec, id, table: t.id, title: spec.title?.trim() || `${t.name}${spec.by ? ` by ${spec.by}` : ""}` };
  };
  const touch = (d: Stored) => {
    d.updatedAt = new Date().toISOString();
    d.updatedBy = "you";
  };
  return {
    async dashboards(): Promise<DashboardSummary[]> {
      return [...stored()].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)).map(summary);
    },
    async dashboard(dashboardId: string): Promise<DashboardDetail | null> {
      const d = stored().find((x) => x.id === dashboardId);
      if (!d) return null;
      const widgets: DashboardWidget[] = d.widgets.map((w) => {
        const t = table(w.table);
        return t ? { ...w, tableName: t.name, data: compute(t, w) } : { ...w, tableName: null, error: "Its table is gone. Change it or remove it." };
      });
      const sources = library().map((t) => ({
        id: t.id,
        name: t.name,
        columns: t.columns.map((c) => ({ name: c.name, type: c.type, ...(c.options.labels ? { labels: c.options.labels } : {}), ...(c.options.unit ? { unit: c.options.unit } : {}) })),
      }));
      return { ...summary(d), widgets, sources, asks: asks().filter((a) => a.dashboardId === d.id) };
    },
    async dashboardAsks(): Promise<DashboardAsk[]> {
      return asks().filter((a) => !a.dashboardId);
    },
    async createDashboard(name: string) {
      const clean = name.trim().replace(/\s+/g, " ");
      if (!clean || clean.length > 80) throw new AgentError("Give the dashboard a name, up to 80 characters.", 400);
      if (stored().some((d) => d.name.toLowerCase() === clean.toLowerCase())) throw new AgentError(`There's already a dashboard called ${clean}.`, 400);
      const now = new Date().toISOString();
      const d: Stored = { id: newId("db"), name: clean, description: "", createdAt: now, updatedAt: now, updatedBy: "you", widgets: [] };
      stored().push(d);
      return { id: d.id };
    },
    async saveDashboard(dashboardId: string, change: { name?: string; description?: string }) {
      const d = find(dashboardId);
      if (change.name !== undefined) {
        if (!change.name.trim()) throw new AgentError("Give the dashboard a name, up to 80 characters.", 400);
        d.name = change.name.trim().slice(0, 80);
      }
      if (change.description !== undefined) d.description = change.description.trim().slice(0, 300);
      touch(d);
    },
    async removeDashboard(dashboardId: string) {
      const list = stored();
      list.splice(list.indexOf(find(dashboardId)), 1);
    },
    async saveDashboardWidget(dashboardId: string, widgetId: string | null, widget: DashboardWidgetSpec) {
      const d = find(dashboardId);
      if (widgetId) {
        const at = d.widgets.findIndex((w) => w.id === widgetId);
        if (at < 0) throw new AgentError("That chart isn't on this dashboard any more.", 400);
        d.widgets[at] = clean(widget, widgetId);
      } else {
        d.widgets.push(clean(widget, newId("w")));
      }
      touch(d);
      return { id: widgetId ?? d.widgets[d.widgets.length - 1].id };
    },
    async changeDashboardWidget(dashboardId: string, widgetId: string, action: "remove" | "up" | "down") {
      const d = find(dashboardId);
      const at = d.widgets.findIndex((w) => w.id === widgetId);
      if (at < 0) throw new AgentError("That chart isn't on this dashboard any more.", 400);
      if (action === "remove") d.widgets.splice(at, 1);
      else {
        const to = action === "up" ? at - 1 : at + 1;
        if (to >= 0 && to < d.widgets.length) [d.widgets[at], d.widgets[to]] = [d.widgets[to], d.widgets[at]];
      }
      touch(d);
    },
    async askForDashboard(text: string, dashboardId?: string): Promise<DashboardAsk> {
      const made: DashboardAsk = {
        id: newId("da"),
        dashboardId: dashboardId ?? null,
        text,
        status: "answered",
        reply: "This is the sample company, so I can't make dashboards here, but in yours I would. Try **Add a chart** to build one yourself.",
        made: null,
        at: new Date().toISOString(),
      };
      asks().unshift(made);
      return made;
    },
  };
}
