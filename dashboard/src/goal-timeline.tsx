"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Goal, Project, ProjectStatus } from "./backend/types";
import { metric } from "./format";
import { PACE } from "./goal-bits";
import { Card, cx, Pill } from "./ui";

/**
 * Goals and their projects on a calendar (a Gantt chart): each project a bar from when it started
 * to when it finished, or to today while it's going, with its target date marked; each goal a
 * thin bar from when it was set to its target date, filled as far as it has got. A line marks
 * today. Zoom between weeks, months and quarters; it opens scrolled to today.
 */

const DAY = 24 * 60 * 60_000;
type Zoom = "weeks" | "months" | "quarters";
const PX_PER_DAY: Record<Zoom, number> = { weeks: 30, months: 9, quarters: 3.5 };

const BAR: Record<ProjectStatus, string> = {
  done: "bg-accent",
  "in-progress": "bg-sky",
  "waiting-on-you": "bg-amber",
  blocked: "bg-rose",
  planned: "border border-dashed border-ink-3/60 bg-surface-2",
};
const STATUS_LABEL: Record<ProjectStatus, string> = {
  done: "Done",
  "in-progress": "In progress",
  "waiting-on-you": "Waiting on you",
  blocked: "Stuck",
  planned: "Planned",
};

// UTC throughout, so the server and the browser draw the same calendar.
const day = (t: number) => new Intl.DateTimeFormat("en", { month: "short", day: "numeric", timeZone: "UTC" }).format(t);
const utc = (y: number, m: number, d = 1) => Date.UTC(y, m, d);
const parse = (iso?: string) => (iso ? Date.parse(iso) : null);

/** Where a project's bar starts and ends, and whether it's past its date. */
function span(p: Project, fallbackStart: number, now: number) {
  const start = parse(p.startedAt) ?? fallbackStart;
  const due = parse(p.due);
  const end = parse(p.finishedAt) ?? (p.status === "planned" ? (due ?? start + 14 * DAY) : now);
  return { start, end: Math.max(end, start + DAY / 2), due, late: due !== null && p.status !== "done" && due < now };
}

export function GoalTimeline({ goals, now, ownerNames }: { goals: Goal[]; now: number; ownerNames: Record<Project["owner"], string> }) {
  const [zoom, setZoom] = useState<Zoom>("months");
  const scroller = useRef<HTMLDivElement>(null);
  const gutter = useRef<HTMLDivElement>(null);

  const times = [now];
  for (const g of goals) {
    const gs = parse(g.startedAt) ?? now - 30 * DAY;
    times.push(gs, parse(g.due) ?? now);
    for (const p of g.projects) {
      const s = span(p, gs, now);
      times.push(s.start, s.end, s.due ?? s.end);
    }
  }
  const first = new Date(Math.min(...times) - 7 * DAY);
  const from = utc(first.getUTCFullYear(), first.getUTCMonth());
  const to = Math.max(...times) + 30 * DAY;
  const px = PX_PER_DAY[zoom];
  const width = Math.ceil(((to - from) / DAY) * px);
  const x = (t: number) => ((t - from) / DAY) * px;
  const today = x(now);

  // Ticks: the first of each month, and Mondays too when zoomed in to weeks.
  const ticks: { t: number; label: string; major: boolean }[] = [];
  for (let m = new Date(from); m.getTime() < to; m = new Date(utc(m.getUTCFullYear(), m.getUTCMonth() + 1))) {
    const label = new Intl.DateTimeFormat("en", { month: "short", timeZone: "UTC", ...(m.getUTCMonth() === 0 ? { year: "numeric" } : {}) }).format(m);
    ticks.push({ t: m.getTime(), label, major: true });
    if (zoom === "weeks") {
      for (let d = new Date(m); d.getUTCMonth() === m.getUTCMonth(); d = new Date(d.getTime() + DAY)) {
        if (d.getUTCDay() === 1 && d.getUTCDate() > 3) ticks.push({ t: d.getTime(), label: String(d.getUTCDate()), major: false });
      }
    }
  }

  // Open at today, and keep today in view when zooming.
  useEffect(() => {
    const el = scroller.current;
    // Today a third of the way across what's visible past the labels, so what's ahead shows.
    if (el) el.scrollLeft = Math.max(0, today - (el.clientWidth - (gutter.current?.offsetWidth ?? 0)) * 0.35);
  }, [today]);

  const grid = (
    <>
      {ticks.map((t) => (
        <div key={t.t} className={cx("absolute inset-y-0 w-px", t.major ? "bg-line" : "bg-line/50")} style={{ left: x(t.t) }} />
      ))}
      <div className="absolute inset-y-0 z-[1] w-0.5 bg-rose/70" style={{ left: today }} />
    </>
  );
  const row = (key: string, label: ReactNode, plot: ReactNode, goalRow = false) => (
    <div key={key} className={cx("flex", goalRow && "border-t border-line")}>
      <div className={cx("sticky left-0 z-[2] w-40 shrink-0 border-r border-line bg-surface px-3 sm:w-64 sm:px-4", goalRow ? "py-3" : "py-2")}>{label}</div>
      <div className="relative shrink-0" style={{ width }}>
        {grid}
        {plot}
      </div>
    </div>
  );

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3 sm:px-6">
        <div className="flex flex-wrap items-center gap-3 text-xs text-ink-3">
          {(["done", "in-progress", "waiting-on-you", "blocked", "planned"] as ProjectStatus[]).map((s) => (
            <span key={s} className="inline-flex items-center gap-1.5">
              <span className={cx("inline-block h-2.5 w-4 rounded-sm", BAR[s])} />
              {STATUS_LABEL[s]}
            </span>
          ))}
        </div>
        <div className="inline-flex gap-1 rounded-full bg-surface-2 p-1 text-xs">
          {(["weeks", "months", "quarters"] as Zoom[]).map((z) => (
            <button
              key={z}
              type="button"
              onClick={() => setZoom(z)}
              aria-pressed={zoom === z}
              className={cx("rounded-full px-3 py-1 font-medium capitalize transition-colors", zoom === z ? "bg-surface text-ink shadow-card" : "text-ink-3 hover:text-ink")}
            >
              {z}
            </button>
          ))}
        </div>
      </div>

      <div ref={scroller} className="overflow-x-auto">
        <div className="min-w-max">
          {/* The calendar along the top, with today. */}
          <div className="flex">
            <div ref={gutter} className="sticky left-0 z-[2] w-40 shrink-0 border-r border-line bg-surface sm:w-64" />
            <div className="relative h-9 shrink-0 text-xs text-ink-3" style={{ width }}>
              {ticks.map((t) => (
                <span key={t.t} className={cx("absolute top-2.5 pl-1.5 whitespace-nowrap", t.major && "font-medium text-ink-2")} style={{ left: x(t.t) }}>
                  {t.label}
                </span>
              ))}
              <span className="absolute top-1 z-[3] -translate-x-1/2 rounded bg-rose px-1.5 py-0.5 text-[10px] font-medium text-bg" style={{ left: today }}>
                Today
              </span>
            </div>
          </div>

          {goals.map((g) => {
            const pace = PACE[g.pace];
            const gStart = parse(g.startedAt) ?? now - 30 * DAY;
            const gEnd = parse(g.due);
            const { current, target, unit } = g.metric;
            const progress = target > 0 ? Math.min(1, Math.max(0, current / target)) : 0;
            const used = gEnd ? Math.min(1, Math.max(0, (now - gStart) / (gEnd - gStart || 1))) : null;
            return [
              row(
                g.id,
                <div className="min-w-0">
                  <p className="truncate font-medium" title={g.title}>
                    {g.title}
                  </p>
                  <div className="mt-1 flex items-center gap-2">
                    <Pill tone={pace.tone}>{pace.label}</Pill>
                    <span className="truncate text-xs text-ink-3 tabular-nums">{Math.round(progress * 100)}%</span>
                  </div>
                </div>,
                <div
                  className={cx("absolute top-1/2 h-3 -translate-y-1/2 overflow-hidden rounded-full bg-surface-2 ring-1 ring-line", !gEnd && "rounded-r-none")}
                  style={{ left: x(gStart), width: Math.max(8, x(gEnd ?? to) - x(gStart)) }}
                  title={`${g.title}: ${metric(current, unit)} of ${metric(target, unit)} (${Math.round(progress * 100)}%)${
                    used !== null ? `, ${Math.round(used * 100)}% of the time used, ${day(gStart)} to ${day(gEnd!)}` : `, since ${day(gStart)}, no target date`
                  }`}
                >
                  <div className={cx("h-full", pace.bar === "amber" ? "bg-amber" : "bg-accent")} style={{ width: `${progress * 100}%` }} />
                </div>,
                true,
              ),
              ...g.projects.map((p) => {
                const s = span(p, gStart, now);
                const left = x(s.start);
                return row(
                  `${g.id}-${p.id}`,
                  <div className="min-w-0 pl-3">
                    <p className="truncate text-sm" title={p.title}>
                      {p.title}
                    </p>
                    <p className="truncate text-xs text-ink-3">{ownerNames[p.owner]}</p>
                  </div>,
                  <>
                    {/* While it's going and its date is ahead, the rest of the way shows faintly. */}
                    {s.due !== null && s.due > s.end && p.status !== "done" && (
                      <div className="absolute top-1/2 h-1 -translate-y-1/2 rounded-full bg-line" style={{ left: x(s.end), width: x(s.due) - x(s.end) }} />
                    )}
                    <div
                      className={cx("absolute top-1/2 h-5 -translate-y-1/2 rounded-md", BAR[p.status])}
                      style={{ left, width: Math.max(10, x(s.end) - left) }}
                      title={`${p.title}: ${STATUS_LABEL[p.status]}. Started ${day(s.start)}${p.finishedAt ? `, finished ${day(s.end)}` : ""}${
                        s.due !== null ? `, due ${day(s.due)}` : ""
                      }. Done when: ${p.doneWhen}`}
                    />
                    {s.due !== null && (
                      <div
                        className={cx("absolute top-1/2 z-[2] size-2.5 -translate-x-1/2 -translate-y-1/2 rotate-45", s.late ? "bg-rose" : "bg-ink-2")}
                        style={{ left: x(s.due) }}
                        title={`${s.late ? "Past its date" : "Due"}: ${day(s.due)}`}
                      />
                    )}
                  </>,
                );
              }),
            ];
          })}
        </div>
      </div>
      <p className="border-t border-line px-4 py-3 text-xs text-ink-3 sm:px-6">
        Bars run from when work started to when it finished, or to today while it&apos;s going. ◆ marks a target date (red once it&apos;s passed).
        Goal bars fill as far as you&apos;ve got.
      </p>
    </Card>
  );
}
