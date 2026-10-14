import { Suspense } from "react";
import { PartyPopper } from "lucide-react";
import type { DashboardHost } from "../host";
import { ago } from "../format";
import { DecisionList } from "../decision-card";
import { Empty, PageHeader, Skeleton } from "../ui";

export function DecisionsPage({ host }: { host: DashboardHost }) {
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title="Decisions"
        subtitle="The few things only you should decide. Each one comes with a recommendation, so going with it takes one tap."
      />
      <Suspense fallback={<Skeleton className="h-[32rem] rounded-3xl" />}>
        <Decisions host={host} />
      </Suspense>
    </div>
  );
}

async function Decisions({ host }: { host: DashboardHost }) {
  const backend = await host.backend();
  const [{ company }, decisions] = await Promise.all([backend.overview(), backend.decisions()]);
  const now = await host.now();

  if (decisions.length === 0) {
    return (
      <Empty icon={<PartyPopper className="size-5" />} title="Nothing to decide">
        {company.cooName} is running things. When something needs you, it shows up here and in your morning brief.
      </Empty>
    );
  }
  return (
    <DecisionList
          decide={host.actions.decide}
          connections={host.connections}
          tracesUrl={host.tracesUrl}
      decisions={decisions}
      cooName={company.cooName}
      ages={Object.fromEntries(decisions.map((d) => [d.id, ago(d.createdAt, now)]))}
    />
  );
}
