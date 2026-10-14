import { Suspense } from "react";
import type { DashboardHost } from "../host";
import { Timeline } from "../timeline";
import { History } from "lucide-react";
import { Card, Empty, PageHeader, Skeleton } from "../ui";

export function TimelinePage({ host }: { host: DashboardHost }) {
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title="Timeline" subtitle="Everything that happened in your business, in plain words. Nothing happens out of sight." />
      <Suspense fallback={<Skeleton className="h-[40rem]" />}>
        <Events host={host} />
      </Suspense>
    </div>
  );
}

async function Events({ host }: { host: DashboardHost }) {
  const backend = await host.backend();
  const [{ company }, events, now] = await Promise.all([backend.overview(), backend.timeline(), host.now()]);
  if (events.length === 0) {
    return (
      <Empty icon={<History className="size-5" />} title="Nothing here yet">
        Every email {company.cooName} sends, every routine that runs and every decision you make will show up here.
      </Empty>
    );
  }
  return (
    <Card className="p-6 sm:p-8">
      <Timeline events={events} cooName={company.cooName} now={now} changesUrl={host.runChangesUrl} />
    </Card>
  );
}
