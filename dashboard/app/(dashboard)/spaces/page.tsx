import type { Metadata } from "next";
import { Suspense } from "react";
import { Card, PageHeader, Skeleton } from "../../../src/ui";
import { currentSpace, now, spaces } from "../../../local/host";
import { spacesAvailable } from "../../../local/spaces";
import { NewSpaceForm, SpaceRow } from "./parts";

export const metadata: Metadata = { title: "Spaces" };

export default function Page() {
  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader
        title="Spaces"
        subtitle="Separate spaces for your businesses or projects: each has its own business manager, memory, chat, routines and connections, kept apart from the others. Switch between them from the menu next to the business name."
      />
      <Suspense fallback={<Skeleton className="h-96 rounded-3xl" />}>
        <Spaces />
      </Suspense>
    </div>
  );
}

async function Spaces() {
  await now();
  const [all, current] = [spaces(), await currentSpace()];
  return (
    <div className="space-y-8">
      <Card className="divide-y divide-line p-0">
        {all.map((s) => (
          <SpaceRow key={s.id} id={s.id} name={s.name} cooName={s.cooName} current={s.id === current.id} first={s.id === "main"} />
        ))}
      </Card>
      <Card className="p-6">
        <h2 className="mb-1 font-medium">New space</h2>
        {spacesAvailable() ? (
          <NewSpaceForm />
        ) : (
          <p className="text-ink-2">
            New spaces need the spaces service, which comes with the latest Steerable. Update it: run get.sh again in the folder it&apos;s
            installed in.
          </p>
        )}
      </Card>
    </div>
  );
}
