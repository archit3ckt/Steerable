import { Suspense } from "react";
import Link from "next/link";
import { ArrowRight, PartyPopper } from "lucide-react";
import type { DashboardHost } from "../host";
import { Chat } from "../chat";
import { OnboardingKickoff } from "../onboarding-kickoff";
import { Card, CooAvatar, Skeleton } from "../ui";

export function GettingStartedPage({ host }: { host: DashboardHost }) {
  return (
    <div className="mx-auto max-w-3xl">
      <Suspense fallback={<Skeleton className="h-[70vh]" />}>
        <Interview host={host} />
      </Suspense>
    </div>
  );
}

async function Interview({ host }: { host: DashboardHost }) {
  const backend = await host.backend();
  const [{ company }, status, messages] = await Promise.all([backend.overview(), backend.onboarding(), backend.chat()]);
  const coo = company.cooName;

  return (
    <>
      <header className="mb-8 flex items-start gap-4">
        <CooAvatar name={coo} size="lg" />
        <div>
          <h1 className="font-display text-4xl leading-tight tracking-tight sm:text-5xl">Meet {coo}</h1>
          <p className="mt-2 max-w-xl text-ink-2">
            {coo} will learn how {company.name} works, one question at a time, then suggest the first thing to take off
            your plate. It takes about 10 minutes. You can stop anytime and pick up later in Chat.
          </p>
        </div>
      </header>

      {status.done && (
        <Card className="mb-8 flex flex-col items-start gap-4 p-6 sm:flex-row sm:items-center">
          <div className="grid size-11 shrink-0 place-items-center rounded-full bg-accent-soft text-accent">
            <PartyPopper className="size-5" />
          </div>
          <div className="flex-1">
            <p className="font-display text-2xl tracking-tight">You&apos;re all set</p>
            <p className="text-ink-2">
              {coo} has what it needs. Its first idea for you is waiting in Decisions.
            </p>
          </div>
          <Link
            href="/decisions"
            className="group inline-flex items-center gap-2 rounded-full bg-accent px-5 py-2.5 font-medium text-accent-ink transition-colors hover:bg-accent-hover"
          >
            See it <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" />
          </Link>
        </Card>
      )}

      {!status.started && <OnboardingKickoff start={host.actions.startOnboarding} />}
      <Chat sendMessage={host.actions.sendMessage} activityUrl={host.chatActivityUrl} filesUrl={host.chatFilesUrl} pageUrl={host.chatPageUrl} messages={messages} cooName={coo} suggestions={[]} expectingReply={!status.done && messages.length === 0} />
    </>
  );
}
