import { BadgeCheck, CircleCheck, Flag, Info, Sparkles, Wrench } from "lucide-react";
import type { Actor, TimelineEvent, TimelineKind } from "./backend/types";
import { clock, dayLabel } from "./format";
import { RunChanges } from "./run-changes";
import { Pill, cx } from "./ui";

const KIND: Record<TimelineKind, { Icon: typeof Flag; dot: string; label: string }> = {
  done: { Icon: CircleCheck, dot: "bg-accent-soft text-accent", label: "Done" },
  fixed: { Icon: Wrench, dot: "bg-sky-soft text-sky", label: "Fixed" },
  decided: { Icon: BadgeCheck, dot: "bg-ink text-bg", label: "Your decision" },
  learned: { Icon: Sparkles, dot: "bg-violet-soft text-violet", label: "Learned" },
  milestone: { Icon: Flag, dot: "bg-amber-soft text-amber", label: "Milestone" },
  "heads-up": { Icon: Info, dot: "bg-surface-2 text-ink-2", label: "Heads-up" },
};

function actorName(actor: Actor, cooName: string) {
  return actor === "coo" ? cooName : actor === "you" ? "You" : "Autopilot";
}

export function Timeline({
  events,
  cooName,
  now,
  compact = false,
  changesUrl,
}: {
  events: TimelineEvent[];
  cooName: string;
  now: number;
  /** Smaller headings, no details: for side panels. */
  compact?: boolean;
  /** The host's runChangesUrl: events that changed the library open a table of what changed. */
  changesUrl?: string;
}) {
  const days = new Map<string, TimelineEvent[]>();
  for (const e of events) {
    const label = dayLabel(e.at, now);
    days.set(label, [...(days.get(label) ?? []), e]);
  }

  return (
    <div className={compact ? "space-y-6" : "space-y-10"}>
      {[...days].map(([day, items]) => (
        <section key={day}>
          <h3 className={compact ? "mb-3 text-xs font-medium text-ink-3 uppercase" : "mb-4 font-display text-2xl"}>{day}</h3>
          <ol className="relative">
            {items.map((e, i) => {
              const k = KIND[e.kind];
              const last = i === items.length - 1;
              return (
                <li key={e.id} className="relative flex gap-4 pb-6 last:pb-0">
                  {!last && <span aria-hidden className="absolute top-9 bottom-0 left-[17px] w-px bg-line" />}
                  <span className={cx("relative z-10 grid size-9 shrink-0 place-items-center rounded-full", k.dot)}>
                    <k.Icon className="size-4" aria-label={k.label} />
                  </span>
                  <div className="min-w-0 flex-1 pt-1.5">
                    <p className={cx("font-medium", compact && "text-sm leading-snug")}>{e.title}</p>
                    {e.detail && !compact && <p className="mt-1 leading-relaxed text-ink-2">{e.detail}</p>}
                    {e.changes && !compact && <RunChanges run={e.run} changes={e.changes} url={changesUrl} />}
                    <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-ink-3">
                      <span>{actorName(e.actor, cooName)}</span>
                      <span aria-hidden>·</span>
                      <time dateTime={e.at}>{clock(e.at)}</time>
                      {e.goal && !compact && <Pill className="ml-1">{e.goal}</Pill>}
                    </div>
                  </div>
                </li>
              );
            })}
          </ol>
        </section>
      ))}
    </div>
  );
}
