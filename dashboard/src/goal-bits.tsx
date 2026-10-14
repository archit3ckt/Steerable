import type { Goal } from "./backend/types";
import { metric } from "./format";
import { Pill, Progress, type Tone } from "./ui";

export const PACE: Record<Goal["pace"], { label: string; tone: Tone; bar: "accent" | "amber" }> = {
  ahead: { label: "Ahead", tone: "accent", bar: "accent" },
  "on-track": { label: "On track", tone: "sky", bar: "accent" },
  behind: { label: "Behind", tone: "amber", bar: "amber" },
};

export function GoalMini({ goal }: { goal: Goal }) {
  const pace = PACE[goal.pace];
  const { current, target, unit } = goal.metric;
  return (
    <div>
      <div className="mb-2 flex items-center justify-between gap-3">
        <p className="truncate font-medium">{goal.title}</p>
        <Pill tone={pace.tone}>{pace.label}</Pill>
      </div>
      <Progress value={target > 0 ? current / target : 0} tone={pace.bar} />
      <p className="mt-1.5 text-xs text-ink-3 tabular-nums">
        {metric(current, unit)} of {metric(target, unit)}
      </p>
    </div>
  );
}
