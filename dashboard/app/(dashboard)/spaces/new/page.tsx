import type { Metadata } from "next";
import { Suspense } from "react";
import { Card, PageHeader, Skeleton } from "../../../../src/ui";
import { CopyButton } from "../../../../src/copy-button";
import { now, spaces } from "../../../../local/host";

export const metadata: Metadata = { title: "New space" };

const command = 'sh get.sh --add-space "Your project"';
const importing = 'sh get.sh --add-space "Your project" --import company.tar.gz';

/**
 * A new space is a new engine next to the others (its own folder, memory, chat, routines and
 * connections). The dashboard can't start containers (it would need control of Docker), so the
 * installer does it, in one line.
 */
export default function Page() {
  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader
        title="New space"
        subtitle="A separate space for another business or project: its own COO, memory, chat, routines and connections, kept apart from your others. Switch between them from the menu next to the business name."
      />
      <Suspense fallback={<Skeleton className="h-64 rounded-3xl" />}>
        <Steps />
      </Suspense>
    </div>
  );
}

async function Steps() {
  await now();
  const count = spaces().length;
  return (
    <div className="space-y-6">
      <Card className="p-6">
        <p className="text-ink-2">
          Run this in the folder Steerable is installed in (where <code className="rounded bg-surface-2 px-1">docker-compose.yml</code> is,
          usually <code className="rounded bg-surface-2 px-1">~/steerable-docker</code>). It starts the new space&apos;s COO and adds it
          to this dashboard. You have {count === 1 ? "1 space" : `${count} spaces`} now.
        </p>
        <div className="mt-4 flex items-center gap-2 rounded-xl bg-surface-2 px-4 py-3 font-mono text-sm">
          <span className="min-w-0 flex-1 overflow-x-auto whitespace-nowrap">{command}</span>
          <CopyButton text={command} />
        </div>
        <p className="mt-4 text-sm text-ink-3">
          Add <code>--coo Name</code> to name its COO. It uses the same AI as your first space (your API key, or a Claude sign-in it asks for
          on its Connections page). Each space runs its own COO, so give your server about 150 MB of memory per space.
        </p>
      </Card>
      <Card className="p-6">
        <h2 className="font-medium">Bring a company you already have</h2>
        <p className="mt-2 text-ink-2">
          From another Steerable (yours, on another machine, or Steerable Cloud): download it there (the download button), then:
        </p>
        <div className="mt-4 flex items-center gap-2 rounded-xl bg-surface-2 px-4 py-3 font-mono text-sm">
          <span className="min-w-0 flex-1 overflow-x-auto whitespace-nowrap">{importing}</span>
          <CopyButton text={importing} />
        </div>
      </Card>
    </div>
  );
}
