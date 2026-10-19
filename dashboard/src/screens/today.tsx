import { Suspense, type ReactNode } from "react";
import Link from "next/link";
import { ArrowRight, Clock, Inbox, PartyPopper, TrendingUp } from "lucide-react";
import type { DashboardHost } from "../host";
import { ago, greeting } from "../format";
import { DecisionList } from "../decision-card";
import { GoalMini } from "../goal-bits";
import { Timeline } from "../timeline";
import { Card, CooAvatar, Empty, SectionHeader, Skeleton } from "../ui";

/** `notice`: something the host wants under the greeting on phones (on large screens it has a sidebar). */
export function TodayPage({ host, notice }: { host: DashboardHost; notice?: ReactNode }) {
  return (
    <div className="mx-auto max-w-6xl">
      <Suspense>
        <GettingStartedNudge host={host} />
      </Suspense>
      <Suspense>
        <SettingUpNote host={host} />
      </Suspense>
      <Suspense fallback={<HeroSkeleton />}>
        <Hero host={host} notice={notice} />
      </Suspense>

      <div className="mt-12 grid gap-12 lg:grid-cols-[minmax(0,1fr)_300px] xl:grid-cols-[minmax(0,1fr)_320px]">
        <section aria-labelledby="needs-you">
          <Suspense fallback={<Skeleton className="h-96 rounded-3xl" />}>
            <NeedsYou host={host} />
          </Suspense>
        </section>

        <aside className="space-y-12">
          <section>
            <SectionHeader title="Goals" action={<SeeAll href="/goals" />} />
            <Suspense fallback={<Skeleton className="h-56" />}>
              <Goals host={host} />
            </Suspense>
          </section>
          <section>
            <SectionHeader title="Recently" action={<SeeAll href="/timeline" />} />
            <Suspense fallback={<Skeleton className="h-72" />}>
              <Recent host={host} />
            </Suspense>
          </section>
        </aside>
      </div>
    </div>
  );
}

/** Until onboarding is done, the first thing on Today is finishing it. */
async function GettingStartedNudge({ host }: { host: DashboardHost }) {
  const backend = await host.backend();
  const [{ company }, status] = await Promise.all([backend.overview(), backend.onboarding()]);
  if (status.done) return null;
  return (
    <Link
      href="/getting-started"
      className="group mb-8 flex animate-rise items-center gap-4 rounded-2xl border border-accent/20 bg-accent-soft p-4 pr-5 transition-shadow hover:shadow-lift"
    >
      <CooAvatar name={company.cooName} />
      <div className="min-w-0 flex-1">
        <p className="font-medium text-ink">Finish getting started with {company.cooName}</p>
        <p className="text-sm text-ink-2">
          A few questions about {company.name}, so {company.cooName} can start taking work off your plate.
        </p>
      </div>
      <ArrowRight className="size-5 shrink-0 text-accent transition-transform group-hover:translate-x-0.5" />
    </Link>
  );
}

/**
 * While new routines are being set up (built and tested, which takes a while), say so on Today: what,
 * that it can take up to an hour, and that there's nothing to do meanwhile. Otherwise the owner who
 * just approved one sees nothing happening anywhere. Not for one that's waiting on them (that's in
 * Needs you) or ready to look at.
 */
async function SettingUpNote({ host }: { host: DashboardHost }) {
  const backend = await host.backend();
  const [{ company }, routines, decisions] = await Promise.all([backend.overview(), backend.routines(), backend.decisions()]);
  const waiting = decisions.map((d) => d.title).join("\n");
  const names = routines
    .filter((r) => r.status === "setting-up" && r.stage === "building" && !waiting.includes(r.name))
    .map((r) => r.name);
  if (!names.length) return null;
  const what = names.length === 1 ? `\u201c${names[0]}\u201d` : `${names.length} new routines`;
  return (
    <Link
      href="/work"
      className="group mb-8 flex animate-rise items-center gap-4 rounded-2xl border border-line bg-surface p-4 pr-5 shadow-card transition-shadow hover:shadow-lift"
    >
      <span className="relative grid size-10 shrink-0 place-items-center rounded-full bg-sky-soft text-sky">
        <Clock className="size-5" />
        <span className="absolute -top-0.5 -right-0.5 size-2.5 animate-pulse rounded-full bg-sky" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="font-medium text-ink">
          {company.cooName} is setting up {what}
        </p>
        <p className="text-sm text-ink-2">
          {names.length > 1 && <>{names.join(", ")}. </>}
          Building and testing a new routine can take up to an hour. Nothing for you to do: come back later, and it&apos;ll be here
          for you to look at before it starts.
        </p>
      </div>
      <ArrowRight className="size-5 shrink-0 text-ink-3 transition-transform group-hover:translate-x-0.5" />
    </Link>
  );
}

function SeeAll({ href, label = "See all" }: { href: string; label?: string }) {
  return (
    <Link href={href} className="group inline-flex items-center gap-1 text-sm text-ink-2 hover:text-ink">
      {label}
      <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" />
    </Link>
  );
}

async function Hero({ host, notice }: { host: DashboardHost; notice?: ReactNode }) {
  const backend = await host.backend();
  const [{ company, brief, stats }, decisions] = await Promise.all([backend.overview(), backend.decisions()]);
  const now = new Date(await host.now());
  const today = now.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });

  const tiles = [
    { Icon: Inbox, label: "Waiting on you", value: String(decisions.length), unit: decisions.length === 1 ? "decision" : "decisions", href: "/decisions" },
    { Icon: TrendingUp, label: "Done this week", value: String(stats.doneThisWeek), unit: "things", href: "/timeline" },
    { Icon: Clock, label: "Time given back", value: `${stats.hoursSavedThisWeek}h`, unit: "this week", href: "/work" },
  ];

  return (
    <div className="animate-rise">
      <p className="text-sm text-ink-3">{today}</p>
      <h1 className="mt-1 font-display text-5xl leading-[1.05] tracking-tight sm:text-6xl">
        {greeting(now)}, {company.ownerFirstName}.
      </h1>

      <Card className="mt-8 p-6 sm:p-7">
        <div className="flex items-start gap-4">
          <CooAvatar name={company.cooName} size="lg" />
          <div className="min-w-0">
            <p className="text-sm text-ink-3">{company.cooName}, your COO</p>
            <p className="mt-1 text-lg leading-snug font-medium text-balance sm:text-xl">{brief.headline}</p>
            <ul className="mt-3 space-y-1.5 text-ink-2">
              {brief.points.map((p) => (
                <li key={p} className="flex gap-2.5">
                  <span aria-hidden className="mt-2.5 size-1 shrink-0 rounded-full bg-ink-3" />
                  {p}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </Card>

      {notice && (
        <Suspense>
          <div className="mt-4 lg:hidden">{notice}</div>
        </Suspense>
      )}

      <div className="mt-4 grid grid-cols-3 gap-3">
        {tiles.map(({ Icon, label, value, unit, href }) => (
          <Link key={label} href={href} className="group rounded-2xl border border-line bg-surface p-4 transition-shadow hover:shadow-lift">
            <Icon className="size-4 text-ink-3 transition-colors group-hover:text-accent" />
            <p className="mt-3 text-2xl font-semibold tracking-tight tabular-nums">
              {value} <span className="block text-sm font-normal text-ink-3 sm:inline">{unit}</span>
            </p>
            <p className="text-xs text-ink-2">{label}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}

function HeroSkeleton() {
  return (
    <div>
      <Skeleton className="h-4 w-40 rounded-md" />
      <Skeleton className="mt-3 h-14 w-96 max-w-full rounded-xl" />
      <Skeleton className="mt-8 h-40" />
      <div className="mt-4 grid grid-cols-3 gap-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-28" />
        ))}
      </div>
    </div>
  );
}

async function NeedsYou({ host }: { host: DashboardHost }) {
  const backend = await host.backend();
  const [{ company }, decisions] = await Promise.all([backend.overview(), backend.decisions()]);
  const now = await host.now();
  const shown = decisions.slice(0, 2);

  return (
    <>
      <SectionHeader
        title="Needs you"
        action={decisions.length > shown.length && <SeeAll href="/decisions" label={`All ${decisions.length} decisions`} />}
      />
      <h2 id="needs-you" className="sr-only">
        Decisions that need you
      </h2>
      {shown.length === 0 ? (
        <Empty icon={<PartyPopper className="size-5" />} title="You're all caught up">
          {company.cooName} is running things. You&apos;ll hear when something needs you.
        </Empty>
      ) : (
        <DecisionList
          decide={host.actions.decide}
          connections={host.connections}
          tracesUrl={host.tracesUrl}
          decisions={shown}
          cooName={company.cooName}
          ages={Object.fromEntries(shown.map((d) => [d.id, ago(d.createdAt, now)]))}
        />
      )}
    </>
  );
}

async function Goals({ host }: { host: DashboardHost }) {
  const backend = await host.backend();
  const [{ company }, goals] = await Promise.all([backend.overview(), backend.goals()]);
  if (goals.length === 0) {
    return (
      <Card className="p-5 text-sm text-ink-2">
        No goals yet. {company.cooName} sets them with you while getting to know the business.
      </Card>
    );
  }
  return (
    <Card className="space-y-6 p-5">
      {goals.map((g) => (
        <Link key={g.id} href="/goals" className="block">
          <GoalMini goal={g} />
        </Link>
      ))}
    </Card>
  );
}

async function Recent({ host }: { host: DashboardHost }) {
  const backend = await host.backend();
  const [{ company }, events, now] = await Promise.all([backend.overview(), backend.timeline(4), host.now()]);
  if (events.length === 0) {
    return <Card className="p-5 text-sm text-ink-2">Nothing yet. Everything {company.cooName} does will show up here.</Card>;
  }
  return (
    <Card className="p-5">
      <Timeline events={events} cooName={company.cooName} now={now} compact />
    </Card>
  );
}
