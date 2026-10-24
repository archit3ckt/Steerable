"use client";

import { Check, LayoutDashboard, Loader2, Pin, Plus } from "lucide-react";
import Link from "next/link";
import { createContext, useContext, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import type { DashboardWidgetSpec, MessageChart as Chart } from "./backend/types";
import { WidgetBody } from "./dashboard-charts";
import { tableHref } from "./dashboard-format";
import type { DashboardActions } from "./host";
import { cx, inputClass } from "./ui";

type Pinning = Pick<DashboardActions, "createDashboard" | "saveDashboardWidget">;
const Charts = createContext<{ url?: string; pin?: Pinning }>({});

/**
 * Lets the ```chart blocks under it count themselves through the host's chartsUrl, and, with the
 * dashboard actions, be pinned to a dashboard.
 */
export function ChartsProvider({ url, pin, children }: { url?: string; pin?: Pinning; children: ReactNode }) {
  return <Charts.Provider value={{ url, pin }}>{children}</Charts.Provider>;
}

// One count per block for a minute, so the chat's re-renders and pages don't ask again.
const counted = new Map<string, { at: number; got: Promise<Chart | { error: string }> }>();

function count(url: string, block: string): Promise<Chart | { error: string }> {
  const key = `${url}\n${block}`;
  const hit = counted.get(key);
  if (hit && Date.now() - hit.at < 60_000) return hit.got;
  const got = fetch(`${url}?w=${encodeURIComponent(block)}`, { cache: "no-store" })
    .then(async (r) => {
      const body = await r.json().catch(() => null);
      return body && (r.ok || body.error) ? body : { error: "This chart couldn't be counted right now." };
    })
    .catch(() => ({ error: "This chart couldn't be counted right now." }));
  counted.set(key, { at: Date.now(), got });
  return got;
}

/**
 * A ```chart block in a message: one chart, counted from the library when it's shown (so it's today's
 * numbers, not the day it was written), or a routine's own figures. Over a table, it names the table
 * and can be pinned to a dashboard.
 */
export function MessageChart({ block }: { block: string }) {
  const { url, pin } = useContext(Charts);
  const [chart, setChart] = useState<Chart | { error: string } | null>(null);
  useEffect(() => {
    if (!url) return;
    let live = true;
    count(url, block).then((got) => live && setChart(got));
    return () => {
      live = false;
    };
  }, [url, block]);

  if (!url) return <p className="my-2 text-sm text-ink-3">A chart: open it in the chat to see it.</p>;
  if (!chart)
    return (
      <div className="my-2 flex h-40 items-center justify-center gap-2 rounded-xl border border-line text-sm text-ink-3 first:mt-0 last:mb-0" role="status">
        <Loader2 className="size-4 animate-spin" aria-hidden /> Counting…
      </div>
    );
  if ("error" in chart)
    return <p className="my-2 rounded-xl border border-line px-3 py-2.5 text-sm text-ink-3 first:mt-0 last:mb-0">This chart can&apos;t be shown: {chart.error}</p>;
  return (
    <figure className="my-2 rounded-xl border border-line bg-surface p-4 first:mt-0 last:mb-0">
      <figcaption className="mb-3 flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
        <span>
          <span className="block font-semibold text-ink" dir="auto">
            {chart.title}
          </span>
          {chart.table && chart.tableName && (
            <Link href={tableHref(chart.table, chart.where)} className="text-sm text-ink-3 hover:text-ink hover:underline">
              From {chart.tableName}, as of now
            </Link>
          )}
        </span>
        {chart.table && pin && chart.dashboards && <PinButton chart={chart} pin={pin} />}
      </figcaption>
      <WidgetBody widget={chart} />
    </figure>
  );
}

function spec(chart: Chart): DashboardWidgetSpec {
  const { tableName, data, dashboards, ...rest } = chart;
  void tableName;
  void data;
  void dashboards;
  return { ...rest, table: chart.table ?? "" };
}

function PinButton({ chart, pin }: { chart: Chart; pin: Pinning }) {
  const [open, setOpen] = useState(false);
  const [naming, setNaming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pinned, setPinned] = useState<{ id: string; name: string } | null>(null);
  const dashboards = chart.dashboards ?? [];
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    const escape = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  async function pinTo(id: string, name: string) {
    setBusy(true);
    setError(null);
    const done = await pin.saveDashboardWidget(id, null, spec(chart));
    setBusy(false);
    if (done.error) return setError(done.error);
    setPinned({ id, name });
    setOpen(false);
  }

  async function pinToNew(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const name = String(new FormData(e.currentTarget).get("name") ?? "").trim();
    if (!name) return;
    setBusy(true);
    setError(null);
    const made = await pin.createDashboard(name);
    if (made.error || !made.id) {
      setBusy(false);
      return setError(made.error ?? "The dashboard couldn't be made.");
    }
    await pinTo(made.id, name);
  }

  if (pinned)
    return (
      <Link href={`/library/dashboards/${pinned.id}`} className="inline-flex items-center gap-1 text-sm text-ink-2 hover:text-ink hover:underline">
        <Check className="size-3.5" aria-hidden /> On {pinned.name}
      </Link>
    );
  return (
    <div ref={box} className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-sm text-ink-2 hover:bg-surface-2 hover:text-ink"
      >
        <Pin className="size-3.5" aria-hidden /> Pin to a dashboard
      </button>
      {open && (
        <div className="absolute right-0 z-20 mt-1 w-64 rounded-xl border border-line bg-surface p-1.5 shadow-lg">
          {dashboards.map((d) => (
            <button
              key={d.id}
              type="button"
              disabled={busy}
              onClick={() => pinTo(d.id, d.name)}
              className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-sm text-ink hover:bg-surface-2 disabled:opacity-60"
            >
              <LayoutDashboard className="size-4 shrink-0 text-ink-3" aria-hidden />
              <span className="truncate" dir="auto">
                {d.name}
              </span>
            </button>
          ))}
          {naming || !dashboards.length ? (
            <form onSubmit={pinToNew} className={cx("flex gap-1.5 p-1", dashboards.length > 0 && "mt-1 border-t border-line pt-2")}>
              <input name="name" required maxLength={80} placeholder="New dashboard's name" aria-label="New dashboard's name" autoFocus className={cx(inputClass, "min-w-0 flex-1 py-1 text-sm")} />
              <button type="submit" disabled={busy} className="rounded-lg bg-accent px-2.5 text-sm text-bg hover:bg-accent-hover disabled:opacity-60">
                {busy ? <Loader2 className="size-4 animate-spin" aria-label="Pinning" /> : "Pin"}
              </button>
            </form>
          ) : (
            <button
              type="button"
              onClick={() => setNaming(true)}
              className="mt-1 flex w-full items-center gap-2 rounded-lg border-t border-line px-2.5 py-1.5 text-left text-sm text-ink-2 hover:bg-surface-2 hover:text-ink"
            >
              <Plus className="size-4 shrink-0" aria-hidden /> A new dashboard
            </button>
          )}
          {error && (
            <p className="px-2.5 py-1.5 text-sm text-rose" role="alert">
              {error}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
