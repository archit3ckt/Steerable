"use client";

import { useOptimistic, useState, useTransition } from "react";
import Link from "next/link";
import { Check, Loader2, Play } from "lucide-react";
import { Poll } from "./poll";
import type { Routine, RoutineStage, Todo } from "./backend/types";
import type { DashboardActions } from "./host";
import { Pill, cx } from "./ui";

/** The routine's on/off switch, or why it can't be switched right now. */
export function RoutineSwitch({
  routine: r,
  setPaused,
}: {
  routine: Routine;
  setPaused: DashboardActions["setRoutinePaused"];
}) {
  const [status, setStatus] = useOptimistic(r.status);
  const [, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const running = status === "running";

  function toggle() {
    setError(null);
    startTransition(async () => {
      setStatus(running ? "paused" : "running");
      const result = await setPaused(r.id, running);
      if (result.error) setError(result.error);
    });
  }

  return (
    <div className="flex flex-col items-end">
      {status === "needs-approval" ? (
        <Link href="/decisions">
          <Pill tone="sky">Waiting for your OK</Pill>
        </Link>
      ) : status === "setting-up" && r.stage === "ready" ? (
        <Link href="/decisions">
          <Pill tone="accent">Ready for you to look at</Pill>
        </Link>
      ) : status === "setting-up" ? (
        <Pill tone="sky">Being set up</Pill>
      ) : status === "paused" && r.pausedBy === "coo" ? (
        <Link href="/decisions">
          <Pill tone="amber">Paused to fix a problem</Pill>
        </Link>
      ) : (
        <button
          type="button"
          role="switch"
          aria-checked={running}
          aria-label={running ? `Pause ${r.name}` : `Resume ${r.name}`}
          onClick={toggle}
          className={cx(
            "relative h-6 w-11 shrink-0 rounded-full transition-colors",
            running ? "bg-accent" : "bg-ink-3/30",
          )}
        >
          <span
            className={cx(
              "absolute top-0.5 left-0.5 size-5 rounded-full bg-white shadow transition-transform",
              running && "translate-x-5",
            )}
          />
        </button>
      )}
      {error && (
        <p role="alert" className="mt-2 text-sm text-rose">
          {error}
        </p>
      )}
    </div>
  );
}

/** "Run now" for a routine that's switched on: one run, as its schedule would; the schedule stays. */
export function RunNow({
  routine: r,
  run,
  compact = false,
}: {
  routine: Routine;
  run: DashboardActions["runRoutine"];
  compact?: boolean;
}) {
  const [pending, startTransition] = useTransition();
  const [started, setStarted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (r.status !== "running") return null;

  function go() {
    setError(null);
    startTransition(async () => {
      const result = await run(r.id);
      if (result.error) return setError(result.error);
      setStarted(true);
      setTimeout(() => setStarted(false), 30_000);
    });
  }

  return (
    <span className="inline-flex flex-col items-end">
      {started && <Poll seconds={3} />}
      <button
        type="button"
        onClick={go}
        disabled={pending || started}
        title={`Run ${r.name} once now. Its schedule stays as it is.`}
        className={cx(
          "inline-flex items-center gap-1.5 rounded-full border border-line font-medium text-ink-2 transition-colors hover:border-accent hover:text-ink disabled:opacity-70",
          compact ? "px-2.5 py-1 text-xs" : "px-3.5 py-1.5 text-sm",
        )}
      >
        {pending ? (
          <Loader2 className="size-3.5 animate-spin" />
        ) : started ? (
          <Check className="size-3.5" />
        ) : (
          <Play className="size-3.5" />
        )}
        {pending ? "Starting…" : started ? "Started" : "Run now"}
      </button>
      {error && (
        <span role="alert" className="mt-1 text-xs text-rose">
          {error}
        </span>
      )}
    </span>
  );
}

export function RoutineCard({
  routine: r,
  lastRunAgo,
  setPaused,
  run,
}: {
  routine: Routine;
  lastRunAgo?: string;
  setPaused: DashboardActions["setRoutinePaused"];
  run?: DashboardActions["runRoutine"];
}) {
  return (
    <div className="relative flex h-full flex-col rounded-2xl border border-line bg-surface p-5 shadow-card transition-shadow hover:shadow-lift">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          {/* The whole card opens the routine's page; the switch sits above that link. */}
          <Link
            href={`/work/${encodeURIComponent(r.id)}`}
            title={r.name}
            className="font-medium after:absolute after:inset-0 after:rounded-2xl hover:underline"
          >
            <span className="line-clamp-2">{r.name}</span>
          </Link>
          <p className="text-sm text-ink-3">
            {r.schedule}
            {r.stage === "watched" && (
              <span className="text-sky"> · Under watch</span>
            )}
            {r.stage === "trusted" && <span> · On its own</span>}
          </p>
        </div>
        <div className="relative z-[1]">
          <RoutineSwitch routine={r} setPaused={setPaused} />
        </div>
      </div>

      <p className="mt-3 flex-1 text-sm leading-relaxed text-ink-2">
        {r.description}
      </p>

      <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-line pt-3 text-xs text-ink-3">
        {r.lastRun ? (
          <span className="flex items-center gap-1.5">
            <span
              className={cx(
                "size-1.5 rounded-full",
                r.lastRun.ok ? "bg-accent" : "bg-amber",
              )}
            />
            {r.lastRun.summary} · {lastRunAgo}
          </span>
        ) : (
          <span>Hasn&apos;t run yet</span>
        )}
        {run && (
          <span className="relative z-[1] ml-auto">
            <RunNow routine={r} run={run} compact />
          </span>
        )}
      </div>
    </div>
  );
}

export function TodoItem({
  todo,
  dueLabel,
  toggle,
}: {
  todo: Todo;
  dueLabel?: string;
  toggle: DashboardActions["toggleTodo"];
}) {
  const [done, setDone] = useOptimistic(todo.done);
  const [, startTransition] = useTransition();

  return (
    <li>
      <button
        type="button"
        role="checkbox"
        aria-checked={done}
        onClick={() =>
          startTransition(async () => {
            setDone(!done);
            await toggle(todo.id);
          })
        }
        className="group flex w-full items-start gap-3 rounded-xl px-3 py-3 text-left transition-colors hover:bg-surface-2/60"
      >
        <span
          className={cx(
            "mt-0.5 grid size-5 shrink-0 place-items-center rounded-md border-2 transition-colors",
            done
              ? "border-accent bg-accent text-accent-ink"
              : "border-ink-3/40 group-hover:border-accent",
          )}
        >
          {done && <Check className="size-3.5" strokeWidth={3} />}
        </span>
        <span className="min-w-0 flex-1">
          <span
            className={cx(
              "block leading-snug",
              done && "text-ink-3 line-through",
            )}
          >
            {todo.title}
          </span>
          {(dueLabel || todo.goal) && !done && (
            <span className="mt-1 flex flex-wrap gap-2 text-xs text-ink-3">
              {dueLabel && (
                <span className={dueLabel === "overdue" ? "text-rose" : ""}>
                  Due {dueLabel}
                </span>
              )}
              {todo.goal && <span>· {todo.goal}</span>}
            </span>
          )}
        </span>
      </button>
    </li>
  );
}

/** Watching a routine (anything it can't undo is checked first), or letting it run on its own. */
export function WatchToggle({
  routine: r,
  watch,
}: {
  routine: Routine;
  watch: DashboardActions["watchRoutine"];
}) {
  const [watching, setWatching] = useOptimistic(Boolean(r.watching));
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  if (r.status !== "running" && r.status !== "paused") return null;

  function toggle() {
    setError(null);
    startTransition(async () => {
      setWatching(!watching);
      const result = await watch(r.id, !watching);
      if (result.error) setError(result.error);
    });
  }

  return (
    <div>
      <button
        type="button"
        onClick={toggle}
        disabled={pending}
        className="inline-flex min-h-10 items-center gap-2 rounded-full border border-line bg-surface px-4 text-sm font-medium shadow-card transition-colors hover:bg-surface-2 disabled:opacity-60"
      >
        {pending && <Loader2 className="size-4 animate-spin" />}
        {watching ? "Let it run on its own" : "Watch its next runs"}
      </button>
      {error && (
        <p role="alert" className="mt-2 text-sm text-rose">
          {error}
        </p>
      )}
    </div>
  );
}

const STAGES: { id: RoutineStage; label: string; hint: string }[] = [
  { id: "proposed", label: "Proposed", hint: "Waiting for your OK" },
  { id: "building", label: "Being set up", hint: "Built and tested" },
  { id: "ready", label: "Practice run", hint: "You look before it's on" },
  { id: "watched", label: "Under watch", hint: "Checked before it acts" },
  { id: "trusted", label: "On its own", hint: "Runs without checks" },
];

/** Where a routine is on its way to running on its own, as five steps with the current one marked. */
export function StageSteps({
  stage,
  paused,
}: {
  stage: RoutineStage;
  paused?: boolean;
}) {
  const at = STAGES.findIndex((s) => s.id === stage);
  return (
    <div>
      <ol className="grid grid-cols-5 gap-1.5" aria-label="How far along it is">
        {STAGES.map((s, i) => {
          const done = i < at;
          const now = i === at;
          return (
            <li
              key={s.id}
              aria-current={now ? "step" : undefined}
              className="min-w-0"
            >
              <span
                className={cx(
                  "block h-1.5 rounded-full",
                  done
                    ? "bg-accent/60"
                    : now
                      ? paused
                        ? "bg-amber"
                        : "bg-accent"
                      : "bg-line",
                )}
              />
              <span
                className={cx(
                  "mt-2 hidden truncate text-xs font-medium sm:block",
                  now ? "text-ink" : done ? "text-ink-2" : "text-ink-3",
                )}
              >
                {done && <Check className="mr-0.5 inline size-3" aria-hidden />}
                {s.label}
                {now && paused ? " (paused)" : ""}
              </span>
              <span className="hidden truncate text-xs text-ink-3 sm:block">
                {s.hint}
              </span>
            </li>
          );
        })}
      </ol>
      <p className="mt-2 text-xs text-ink-2 sm:hidden">
        <span className="font-medium text-ink">
          Step {at + 1} of {STAGES.length}: {STAGES[at].label}
          {paused ? " (paused)" : ""}
        </span>{" "}
        · {STAGES[at].hint}
      </p>
    </div>
  );
}
