import { Suspense } from "react";
import type { DashboardHost } from "../host";
import type { ProjectStatus } from "../backend/types";
import { metric, until } from "../format";
import { PACE } from "../goal-bits";
import { GoalTimeline } from "../goal-timeline";
import { GoalsViews } from "../goals-views";
import { Target } from "lucide-react";
import { Card, Empty, PageHeader, Pill, Progress, Skeleton, type Tone } from "../ui";

const STATUS: Record<ProjectStatus, { label: string; tone: Tone }> = {
  planned: { label: "Planned", tone: "neutral" },
  "in-progress": { label: "In progress", tone: "sky" },
  "waiting-on-you": { label: "Waiting on you", tone: "amber" },
  blocked: { label: "Stuck", tone: "rose" },
  done: { label: "Done", tone: "accent" },
};

export function GoalsPage({ host }: { host: DashboardHost }) {
  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader title="Goals" subtitle="What you're aiming for, and the projects moving you there." />
      <Suspense fallback={<Skeleton className="h-[36rem]" />}>
        <Goals host={host} />
      </Suspense>
    </div>
  );
}

async function Goals({ host }: { host: DashboardHost }) {
  const backend = await host.backend();
  const [{ company }, goals] = await Promise.all([backend.overview(), backend.goals()]);
  const now = await host.now();
  const ownerName = { you: "You", coo: company.cooName, autopilot: "Autopilot" };

  if (goals.length === 0) {
    return (
      <Empty icon={<Target className="size-5" />} title="No goals yet">
        {company.cooName} sets them with you while getting to know the business, like &ldquo;40 cafe accounts by
        spring.&rdquo; You can also just ask in Chat.
      </Empty>
    );
  }

  const cards = (
    <div className="space-y-6">
      {goals.map((g) => {
        const pace = PACE[g.pace];
        const { current, target, unit, label } = g.metric;
        return (
          <Card key={g.id} className="animate-rise overflow-hidden">
            <div className="p-6 sm:p-8">
              <div className="flex flex-wrap items-center gap-2">
                <Pill tone={pace.tone}>{pace.label}</Pill>
                {g.due && <span className="text-xs text-ink-3">Target date {until(g.due, now)}</span>}
              </div>
              <h2 className="mt-3 font-display text-3xl tracking-tight sm:text-4xl">{g.title}</h2>
              <p className="mt-1 text-ink-2">{g.why}</p>

              <div className="mt-6 flex items-end justify-between gap-4">
                <div>
                  <p className="text-xs text-ink-3">{label}</p>
                  <p className="text-3xl font-semibold tracking-tight tabular-nums">
                    {metric(current, unit)}
                    <span className="text-lg font-normal text-ink-3"> / {metric(target, unit)}</span>
                  </p>
                </div>
                <p className="text-sm font-medium text-ink-2 tabular-nums">{target > 0 ? `${Math.round((current / target) * 100)}%` : ""}</p>
              </div>
              <div className="mt-3">
                <Progress value={target > 0 ? current / target : 0} tone={pace.bar} />
              </div>
            </div>

            <ul className="divide-y divide-line border-t border-line bg-surface-2/40">
              {g.projects.map((p) => (
                <li key={p.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-6 py-4 sm:px-8">
                  <div className="min-w-0 flex-1">
                    <p className="font-medium">{p.title}</p>
                    <p className="text-sm text-ink-3">Done when: {p.doneWhen}</p>
                  </div>
                  <span className="text-xs text-ink-3">{ownerName[p.owner]}</span>
                  <Pill tone={STATUS[p.status].tone}>{STATUS[p.status].label}</Pill>
                </li>
              ))}
            </ul>
          </Card>
        );
      })}
    </div>
  );
  return <GoalsViews cards={cards} timeline={<GoalTimeline goals={goals} now={now} ownerNames={ownerName} />} />;
}
