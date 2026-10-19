import { Archive, Brain, Check, Clock, Download, Hand, PenLine, Send, type LucideIcon } from "lucide-react";
import type { FlowStep } from "./backend/types";
import { KeepInView } from "./keep-in-view";
import { cx } from "./ui";

/** Each kind of step: its icon, its colors (the same in the flow chart and the code view), its name. */
export const KIND: Record<FlowStep["kind"], { Icon: LucideIcon; tone: string; line: string; name: string }> = {
  trigger: { Icon: Clock, tone: "bg-violet-soft text-violet", line: "bg-violet-soft/60 border-violet", name: "When" },
  read: { Icon: Download, tone: "bg-sky-soft text-sky", line: "bg-sky-soft/60 border-sky", name: "Reads" },
  think: { Icon: Brain, tone: "bg-amber-soft text-amber", line: "bg-amber-soft/60 border-amber", name: "Works out" },
  write: { Icon: PenLine, tone: "bg-accent-soft text-accent", line: "bg-accent-soft/60 border-accent", name: "Writes" },
  ask: { Icon: Hand, tone: "bg-rose-soft text-rose", line: "bg-rose-soft/60 border-rose", name: "Asks you" },
  send: { Icon: Send, tone: "bg-accent-soft text-accent", line: "bg-accent-soft/60 border-accent", name: "Sends" },
  save: { Icon: Archive, tone: "bg-surface-2 text-ink-2", line: "bg-surface-2 border-ink-3", name: "Keeps" },
};

/**
 * A routine's steps as a flow chart, in the style of n8n's canvas: nodes joined left to right
 * on a dotted board (top to bottom on a phone). Read-only: the COO writes the steps.
 * While it runs, `current` is the step it's on: highlighted, with the ones before it ticked.
 */
export function FlowChart({
  steps,
  current = null,
  numbered = false,
  onSelect,
}: {
  steps: FlowStep[];
  current?: number | null;
  /** Number the steps (they match the numbers in the code view). */
  numbered?: boolean;
  /** Clicking a step (its code, in the code view). */
  onSelect?: (step: number) => void;
}) {
  return (
    <div className="overflow-x-auto rounded-2xl border border-line bg-surface-2/50 [background-image:radial-gradient(var(--line)_1px,transparent_1px)] [background-size:18px_18px]">
      <ol className="flex flex-col items-stretch gap-0 p-6 sm:w-max sm:flex-row sm:items-center sm:p-10">
        {steps.map((s, n) => {
          const { Icon, tone, name } = KIND[s.kind];
          const now = current === n;
          const done = current !== null && n < current;
          return (
            <li key={n} className="flex flex-col items-center sm:flex-row">
              {n > 0 && (
                <span aria-hidden className="flex items-center justify-center text-ink-3 sm:mx-1">
                  <span className="h-6 w-px bg-ink-3/50 sm:h-px sm:w-10" />
                  <span className="hidden size-0 border-y-[5px] border-l-[7px] border-y-transparent border-l-ink-3/60 sm:block" />
                </span>
              )}
              <div
                onClick={onSelect ? () => onSelect(n) : undefined}
                role={onSelect ? "button" : undefined}
                tabIndex={onSelect ? 0 : undefined}
                onKeyDown={onSelect ? (e) => (e.key === "Enter" || e.key === " ") && onSelect(n) : undefined}
                className={cx(
                  "relative w-full rounded-2xl border bg-surface p-4 shadow-card transition-shadow sm:w-48",
                  onSelect && "cursor-pointer hover:shadow-lift",
                  s.kind === "trigger" ? "border-violet/40 sm:rounded-l-[2rem]" : "border-line",
                  now && "border-accent ring-4 ring-accent/20",
                  current !== null && !now && !done && "opacity-60",
                )}
                title={s.detail}
                aria-current={now ? "step" : undefined}
              >
                {now && <KeepInView />}
                {now && (
                  <span className="absolute -top-2.5 right-3 inline-flex items-center gap-1.5 rounded-full bg-accent px-2 py-0.5 text-[11px] font-medium text-accent-ink">
                    <span className="size-1.5 animate-pulse rounded-full bg-accent-ink" aria-hidden /> Now
                  </span>
                )}
                {done && (
                  <span className="absolute -top-2 right-3 grid size-5 place-items-center rounded-full bg-accent-soft text-accent" aria-label="Done">
                    <Check className="size-3" />
                  </span>
                )}
                <div className="flex items-center gap-3 sm:flex-col sm:items-start">
                  <span className={cx("grid size-10 shrink-0 place-items-center rounded-xl", tone)}>
                    <Icon className="size-5" />
                  </span>
                  <div className="min-w-0">
                    <p className="text-[11px] font-medium tracking-wide text-ink-3 uppercase">
                      {numbered && <span className="mr-1 tabular-nums">{n + 1} ·</span>}
                      {name}
                    </p>
                    <p className="text-sm leading-snug font-medium">{s.label}</p>
                    {s.service && <p className="mt-1 text-xs text-ink-3">{s.service}</p>}
                  </div>
                </div>
                {s.detail && <p className="mt-2 text-xs leading-relaxed text-ink-3">{s.detail}</p>}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
