import { Suspense } from "react";
import type { DashboardHost } from "../host";
import type { Todo } from "../backend/types";
import { ago, until } from "../format";
import { RoutineCard, TodoItem } from "../work-bits";
import { Card, CooAvatar, PageHeader, SectionHeader, Skeleton } from "../ui";

export function WorkPage({ host }: { host: DashboardHost }) {
  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader title="Work" subtitle="What runs on its own, and who's doing what next." />
      <Suspense fallback={<Skeleton className="h-80" />}>
        <Routines host={host} />
      </Suspense>
      <div className="mt-12 grid gap-8 md:grid-cols-2">
        <Suspense fallback={<Skeleton className="h-64" />}>
          <Todos host={host} />
        </Suspense>
      </div>
    </div>
  );
}

async function Routines({ host }: { host: DashboardHost }) {
  const routines = await (await host.backend()).routines();
  const now = await host.now();
  const running = routines.filter((r) => r.status === "running");
  const hours = running.reduce((s, r) => s + r.hoursSavedPerWeek, 0);

  if (routines.length === 0) {
    return (
      <section>
        <SectionHeader title="On autopilot" />
        <Card className="p-5 text-sm text-ink-2">No routines yet. Once you approve one, it runs here on its own.</Card>
      </section>
    );
  }

  return (
    <section>
      <SectionHeader
        title="On autopilot"
        action={
          <p className="text-sm text-ink-2">
            Saves you ~{hours}h a week
          </p>
        }
      />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {routines.map((r) => (
          <RoutineCard
            setPaused={host.actions.setRoutinePaused}
            key={r.id}
            routine={r}
            lastRunAgo={r.lastRun && ago(r.lastRun.at, now)}
           run={host.actions.runRoutine} />
        ))}
      </div>
    </section>
  );
}

async function Todos({ host }: { host: DashboardHost }) {
  const backend = await host.backend();
  const [{ company }, todos] = await Promise.all([backend.overview(), backend.todos()]);
  const now = await host.now();
  const sorted = (owner: Todo["owner"]) =>
    todos
      .filter((t) => t.owner === owner)
      .sort((a, b) => Number(a.done) - Number(b.done) || (a.due ?? "~").localeCompare(b.due ?? "~"));

  const lists = [
    { title: "Your list", items: sorted("you"), avatar: null },
    { title: `${company.cooName}'s list`, items: sorted("coo"), avatar: <CooAvatar name={company.cooName} size="sm" /> },
  ];

  return lists.map(({ title, items, avatar }) => (
    <section key={title}>
      <SectionHeader title={title} action={avatar} />
      <Card className="p-2">
        {items.length === 0 ? (
          <p className="px-3 py-3 text-sm text-ink-3">Nothing on this list right now.</p>
        ) : (
          <ul>
            {items.map((t) => (
              <TodoItem key={t.id} toggle={host.actions.toggleTodo} todo={t} dueLabel={t.due && until(t.due, now)} />
            ))}
          </ul>
        )}
      </Card>
    </section>
  ));
}
