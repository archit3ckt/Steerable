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
  MessageChart,
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
      name: "Cafes at a glance",
      description: "Cafes and new leads, for the Monday check-in",
      createdAt: at,
      updatedAt: at,
      updatedBy: "coo",
      widgets: [
        { id: "w00000001", type: "number", title: "Open leads", table: "t_leads", where: { Status: "New" }, measure: "count" },
        { id: "w00000002", type: "number", title: "Plants we look after", table: "t_cafes", where: { Status: "Active" }, measure: "sum", column: "Plants" },
        { id: "w00000003", type: "progress", title: "Active cafes, goal 12", table: "t_cafes", where: { Status: "Active" }, measure: "count", goal: 12 },
        { id: "w00000004", type: "bars", title: "Leads by status", table: "t_leads", by: "Status", measure: "count", limit: 8 },
        { id: "w00000005", type: "trend", title: "Leads added per week", table: "t_leads", date: "added", every: "week", last: 8, measure: "count", wide: true },
        { id: "w00000006", type: "list", title: "Cafes with the most plants", table: "t_cafes", sort: "Plants", dir: "desc", limit: 5, show: ["Name", "Status", "Plants"], wide: true },
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

/** The first and last day of this period (back 1: the one before), like dashboards.py's _bounds. */
function bounds(period: string, today: Date, back = 0): [string, string] {
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  const y = today.getUTCFullYear();
  if (period === "week") {
    const start = bucket("week", today);
    start.setUTCDate(start.getUTCDate() - 7 * back);
    const end = new Date(start);
    end.setUTCDate(end.getUTCDate() + 6);
    return [iso(start), iso(end)];
  }
  if (period === "year") return [`${y - back}-01-01`, `${y - back}-12-31`];
  const months = period === "quarter" ? 3 : 1;
  const first = Math.floor(today.getUTCMonth() / months) * months - back * months;
  return [iso(new Date(Date.UTC(y, first, 1))), iso(new Date(Date.UTC(y, first + months, 0)))];
}

function compute(t: Table, w: DashboardWidgetSpec): DashboardWidgetData {
  const rows = rowsOf(t, w.where);
  const inside = (list: Table["rows"], [from, to]: [string, string]) =>
    list.filter((r) => {
      const d = dayOf(r, w);
      return d !== null && d >= from && d <= to;
    });
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
  if (w.type === "candles") {
    const every = (w.every ?? "day") as "day" | "week" | "month";
    const end = bucket(every, new Date());
    const from = step(every, end, -((w.last ?? 90) - 1)).toISOString().slice(0, 10);
    const unitOf = t.columns.find((c) => c.name === w.column)?.options.unit;
    const byPeriod = new Map<string, NonNullable<DashboardWidgetData["candles"]>[number]>();
    const dated = rows
      .map((r) => ({ r, day: dayOf(r, w), v: r.cells[w.column ?? ""] }))
      .filter((x): x is { r: Table["rows"][number]; day: string; v: number } => x.day !== null && x.day >= from && typeof x.v === "number")
      .sort((a, b) => a.day.localeCompare(b.day) || a.r.created.localeCompare(b.r.created));
    for (const { r, day, v } of dated) {
      const key = bucket(every, new Date(`${day}T00:00:00Z`)).toISOString().slice(0, 10);
      const c = byPeriod.get(key) ?? { start: key, open: v, high: v, low: v, close: v, ...(w.volume ? { volume: 0 } : {}) };
      c.high = Math.max(c.high, v);
      c.low = Math.min(c.low, v);
      c.close = v;
      if (w.volume) c.volume = (c.volume ?? 0) + (w.volume === "rows" ? 1 : Number(r.cells[w.volume] ?? 0));
      byPeriod.set(key, c);
    }
    return { ...(unitOf ? { unit: unitOf } : {}), candles: [...byPeriod.values()] };
  }
  if (w.type === "funnel") {
    const stages = w.stages ?? t.columns.find((c) => c.name === w.by)?.options.labels ?? [];
    const here = stages.map((st) => measure(rows.filter((r) => r.cells[w.by ?? ""] === st), w) ?? 0);
    out.by = w.by;
    out.items = stages.map((st, i) => ({ label: st, value: here.slice(i).reduce((a, b) => a + b, 0), now: here[i], filter: st }));
    const others = new Map<string, Table["rows"]>();
    for (const r of rows) {
      const v = String(r.cells[w.by ?? ""] ?? "");
      if (!stages.includes(v)) others.set(v, [...(others.get(v) ?? []), r]);
    }
    out.outside = [...others].map(([k, list]) => ({ label: k || `No ${(w.by ?? "").toLowerCase()}`, value: measure(list, w), filter: k }));
    return out;
  }
  if (w.type === "pace") {
    const period = w.period ?? "year";
    const step = period === "week" || period === "month" ? 1 : 7;
    const today = new Date();
    const [from, to] = bounds(period, today);
    const [wasFrom, wasTo] = bounds(period, today, 1);
    const index = (day: string, start: string) => Math.floor((Date.parse(day) - Date.parse(start)) / 86_400_000 / step);
    const steps = index(to, from) + 1;
    const sums = (start: string, end: string) => {
      const by = new Array<number>(steps).fill(0);
      for (const r of inside(rows, [start, end])) {
        const i = index(dayOf(r, w)!, start);
        if (i < steps) by[i] += measure([r], w) ?? 0;
      }
      return by;
    };
    const now = sums(from, to);
    const was = sums(wasFrom, wasTo);
    let total = 0;
    let wasTotal = 0;
    const todayIso = today.toISOString().slice(0, 10);
    out.points = now.map((v, i) => {
      const start = new Date(Date.parse(from) + i * step * 86_400_000).toISOString().slice(0, 10);
      total += v;
      wasTotal += was[i];
      return { start, value: start <= todayIso ? total : null, previous: wasTotal };
    });
    out.every = step === 1 ? "day" : "week";
    if (w.goal) out.goal = w.goal;
    return out;
  }
  if (w.type === "bars") {
    const col = t.columns.find((c) => c.name === w.by);
    const groups = new Map<string, Table["rows"]>();
    const previous = new Map<string, Table["rows"]>();
    const key = (r: Table["rows"][number]) => {
      const v = r.cells[w.by ?? ""];
      return Array.isArray(v) ? v : [v === null || v === undefined ? "" : String(v)];
    };
    for (const r of w.period ? inside(rows, bounds(w.period, new Date())) : rows) for (const k of key(r)) groups.set(k, [...(groups.get(k) ?? []), r]);
    if (w.period) {
      for (const r of inside(rows, bounds(w.period, new Date(), 1))) for (const k of key(r)) previous.set(k, [...(previous.get(k) ?? []), r]);
      for (const k of previous.keys()) if (!groups.has(k)) groups.set(k, []);
    }
    const labels = col?.options.labels ?? [];
    const keys = [...groups.keys()].sort((a, b) => (labels.length ? labels.indexOf(a) - labels.indexOf(b) : groups.get(b)!.length - groups.get(a)!.length));
    out.by = w.by;
    out.items = keys.slice(0, w.limit ?? 8).map((k) => ({
      label: k || `No ${(w.by ?? "").toLowerCase()}`,
      value: measure(groups.get(k)!, w),
      filter: k,
      ...(w.period ? { previous: measure(previous.get(k) ?? [], w) } : {}),
    }));
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
    async chart(block: string): Promise<MessageChart | { error: string }> {
      let spec: Record<string, unknown>;
      try {
        spec = JSON.parse(block);
      } catch {
        return { error: "This chart's description isn't valid JSON." };
      }
      if (!spec || typeof spec !== "object") return { error: "A chart is a description like {\"type\": \"bars\", \"table\": \"Leads\", \"by\": \"Status\"}." };
      const type = spec.type as DashboardWidgetSpec["type"];
      if (!["number", "bars", "trend", "progress", "funnel", "pace", "candles"].includes(type))
        return { error: "A chart in a message is a number, bars, trend, progress, funnel, pace or candles." };
      if (typeof spec.table !== "string") {
        // A routine's own figures, as dashboards.py checks them.
        const title = typeof spec.title === "string" ? spec.title.trim() : "";
        if (!title) return { error: "A chart with its own figures needs a title saying what they are." };
        const data: DashboardWidgetData = typeof spec.unit === "string" ? { unit: spec.unit } : {};
        if (type === "bars" || type === "funnel")
          data.items = ((spec.items as { label: string; value: number; previous?: number }[]) ?? [])
            .slice(0, 20)
            .map((i) => ({ label: String(i.label), value: i.value, ...(spec.period && i.previous !== undefined ? { previous: i.previous } : {}) }));
        else if (type === "trend") data.points = ((spec.points as { start: string; value: number }[]) ?? []).slice(-36);
        else if (type === "candles") data.candles = ((spec.candles as NonNullable<DashboardWidgetData["candles"]>) ?? []).slice(-365);
        else if (type === "pace") {
          data.points = ((spec.points as { start: string; value: number | null; previous: number }[]) ?? []).slice(0, 60);
          data.every = spec.period === "week" || spec.period === "month" ? "day" : "week";
          if (typeof spec.goal === "number") data.goal = spec.goal;
        }
        else {
          data.value = spec.value as number;
          if (spec.previous !== undefined) data.previous = spec.previous as number;
          if (type === "progress") data.goal = spec.goal as number;
        }
        return { type, title, ...(spec.every ? { every: spec.every as "week" } : {}), ...(spec.period ? { period: spec.period as "month" } : {}), data };
      }
      const t = table(spec.table);
      if (!t) return { error: `There's no table called ${spec.table}.` };
      const w = clean(spec as DashboardWidgetSpec, "");
      const { id, ...rest } = w;
      void id;
      return { ...rest, tableName: t.name, data: compute(t, w), dashboards: stored().map((d) => ({ id: d.id, name: d.name })) };
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
