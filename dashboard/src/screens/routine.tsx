import { Suspense } from "react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, Check, Eye } from "lucide-react";
import type { DashboardHost } from "../host";
import { ago } from "../format";
import { Poll } from "../poll";
import { HowItWorks } from "../routine-code";
import { RoutineSwitch, RunNow, StageSteps, WatchToggle } from "../work-bits";
import { RunChanges } from "../run-changes";
import { TraceViewer } from "../trace-viewer";
import { Card, cx, Pill, SectionHeader, Skeleton } from "../ui";

/** One routine: what it does, its steps as a flow chart, and its recent runs. */
export function RoutinePage({
  host,
  id,
}: {
  host: DashboardHost;
  id: string | Promise<string>;
}) {
  return (
    <div className="mx-auto max-w-5xl">
      <Link
        href="/work"
        className="mb-6 inline-flex items-center gap-1.5 text-sm text-ink-3 hover:text-ink"
      >
        <ArrowLeft className="size-4" /> Work
      </Link>
      <Suspense fallback={<Skeleton className="h-[36rem]" />}>
        <Routine host={host} id={id} />
      </Suspense>
    </div>
  );
}

async function Routine({
  host,
  id,
}: {
  host: DashboardHost;
  id: string | Promise<string>;
}) {
  const backend = await host.backend();
  const [r, now] = await Promise.all([
    backend.routine(decodeURIComponent(await id)),
    host.now(),
  ]);
  if (!r) notFound();
  const facts = [
    { label: "Runs", value: r.schedule },
    r.hoursSavedPerWeek > 0 && {
      label: "Saves you",
      value: `About ${r.hoursSavedPerWeek}h a week`,
    },
    r.goal && { label: "Moves", value: r.goal },
    {
      label: "Last run",
      value: r.lastRun ? ago(r.lastRun.at, now) : "Not yet",
    },
    r.nextRun && { label: "Next run", value: r.nextRun },
  ].filter(Boolean) as { label: string; value: string }[];

  return (
    <div className="space-y-10">
      {(r.building || r.runningNow) && <Poll seconds={3} />}
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-2xl">
          {r.runningNow && (
            <p className="mb-2 inline-flex items-center gap-2 rounded-full bg-accent-soft px-3 py-1 text-sm font-medium text-accent">
              <span
                className="size-2 animate-pulse rounded-full bg-accent"
                aria-hidden
              />{" "}
              Running now · started {ago(r.runningNow.since, now)}
            </p>
          )}
          {r.watch && !r.runningNow && (
            <p className="mb-2">
              <Pill tone="sky">
                <Eye className="size-3.5" /> Under watch
              </Pill>
            </p>
          )}
          <h1 className={cx("font-display leading-tight tracking-tight", r.name.length > 60 ? "text-3xl" : "text-4xl sm:text-5xl")}>{r.name}</h1>
          <p className="mt-2 text-ink-2">{r.description}</p>
        </div>
        <div className="flex items-center gap-3">
          {!r.runningNow && (
            <RunNow routine={r} run={host.actions.runRoutine} />
          )}
          <RoutineSwitch
            routine={r}
            setPaused={host.actions.setRoutinePaused}
          />
        </div>
      </header>

      {r.stage && <StageSteps stage={r.stage} paused={r.status === "paused"} />}

      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-[repeat(auto-fit,minmax(9.5rem,1fr))]">
        {facts.map((f) => (
          <div
            key={f.label}
            className="rounded-2xl border border-line bg-surface px-4 py-3 shadow-card"
          >
            <dt className="text-xs text-ink-3">{f.label}</dt>
            <dd className="mt-0.5 font-medium">{f.value}</dd>
          </div>
        ))}
      </dl>

      {r.building && (
        <BeingSetUp
          steps={r.building.steps}
          since={r.building.since}
          change={r.building.change}
          now={now}
        />
      )}

      {r.ready && (
        <section>
          <SectionHeader
            title={
              r.ready.change
                ? "The update is ready for you to look at"
                : "Ready for you to look at"
            }
            action={
              <Link
                href="/decisions"
                className="text-sm font-medium text-accent hover:underline"
              >
                Decide in Decisions
              </Link>
            }
          />
          <Card className="p-5 sm:p-6">
            {r.ready.change && (
              <p className="mb-2 text-sm text-ink">{r.ready.change}</p>
            )}
            <p className="text-sm text-ink-2">
              It was tried once in a practice run, where nothing is sent.{" "}
              {r.ready.change ? "The new version" : "It"} doesn&apos;t run until
              you switch it on.
            </p>
            <TraceViewer
              id={r.ready.trace}
              url={host.tracesUrl}
              open
              showReview
            />
          </Card>
        </section>
      )}

      {(r.stage === "watched" || r.stage === "trusted") && !r.ready && (
        <section>
          <SectionHeader
            title={r.watch ? "Under watch" : "Running on its own"}
          />
          <Card className="p-5 sm:p-6">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <p className="max-w-2xl text-sm text-ink-2">
                {r.watch
                  ? `${WATCH_WHY[r.watch.why ?? "new"]} Before it does anything it can't undo (sending, submitting, paying, posting), it's checked first, with the page as it is and your records. Anything that looks off is held back for you. ${
                      r.watch.runs === 0
                        ? "It hasn't run under watch yet."
                        : `${r.watch.runs} watched run${r.watch.runs === 1 ? "" : "s"} so far${
                            r.watch.clean
                              ? `, the last ${r.watch.clean} without a problem`
                              : ""
                          }.`
                    } After ${r.watch.needed} clean runs in a row, you're asked whether it can run on its own.`
                  : `It runs without a check before each thing it can't undo${
                      r.record?.onItsOwnSince
                        ? `, since ${ago(r.record.onItsOwnSince, now)}`
                        : ""
                    }. If it hits a problem, it's watched again until it's proved itself.`}
              </p>
              <WatchToggle routine={r} watch={host.actions.watchRoutine} />
            </div>
            {r.record && (
              <dl className="mt-5 grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-4">
                {[
                  {
                    label: `Runs, last ${r.record.days} days`,
                    value: String(r.record.runs),
                  },
                  {
                    label: "Problems",
                    value: String(r.record.problems),
                    bad: r.record.problems > 0,
                  },
                  {
                    label: "Held back for you",
                    value: String(r.record.held),
                    bad: r.record.held > 0,
                  },
                  {
                    label: "Last problem",
                    value: r.record.lastProblem
                      ? ago(r.record.lastProblem, now)
                      : "Never",
                  },
                ].map((f) => (
                  <div key={f.label} className="bg-surface px-4 py-3">
                    <dt className="text-xs text-ink-3">{f.label}</dt>
                    <dd
                      className={cx(
                        "mt-0.5 font-medium",
                        f.bad && "text-amber",
                      )}
                    >
                      {f.value}
                    </dd>
                  </div>
                ))}
              </dl>
            )}
          </Card>
        </section>
      )}

      <section>
        <SectionHeader title="How it works" />
        {r.flow ? (
          <HowItWorks steps={r.flow} current={r.runningNow?.step ?? null} code={r.code} codeMap={r.codeMap} codeMapPending={r.codeMapPending} />
        ) : r.flowPending ? (
          <Card className="p-6">
            <Poll seconds={4} />
            <div className="flex gap-4" aria-hidden>
              {[0, 1, 2, 3].map((n) => (
                <Skeleton key={n} className="h-24 w-44 rounded-2xl" />
              ))}
            </div>
            <p className="mt-4 text-sm text-ink-3">
              Drawing its steps. This takes a moment, once.
            </p>
          </Card>
        ) : (
          <Card className="p-6 text-sm text-ink-3">
            {r.building
              ? "Its steps appear here once it's set up."
              : "Its steps aren't written down yet."}
          </Card>
        )}
      </section>

      <section>
        <SectionHeader title="Recent runs" />
        {r.runs.length ? (
          <Card className="divide-y divide-line">
            {r.runs.map((run) => (
              <div key={run.id ?? run.at} className="px-5 py-3 text-sm">
                <div className="flex items-center gap-3">
                  <span
                    className={cx(
                      "size-2 shrink-0 rounded-full",
                      run.ok ? "bg-accent" : "bg-amber",
                    )}
                  />
                  <span className="min-w-0 flex-1">{run.summary}</span>
                  <span className="shrink-0 text-xs text-ink-3">
                    {ago(run.at, now)}
                  </span>
                </div>
                {run.changes && (
                  <div className="pl-5">
                    <RunChanges
                      run={run.id}
                      changes={run.changes}
                      url={host.runChangesUrl}
                    />
                  </div>
                )}
                {run.trace && (
                  <div className="pl-5">
                    <TraceViewer id={run.trace} url={host.tracesUrl} watched />
                  </div>
                )}
              </div>
            ))}
          </Card>
        ) : (
          <Card className="p-6 text-sm text-ink-3">
            It hasn&apos;t run yet.
          </Card>
        )}
      </section>
    </div>
  );
}

const WATCH_WHY = {
  new: "It's new, so its first runs are watched.",
  owner: "You asked for it to be watched.",
  problem: "It hit a problem, so its next runs are checked again.",
  fixed: "It was just fixed, so its next runs are checked again.",
} as const;

/** While the COO builds the routine: what it has done so far, the newest still going. */
function BeingSetUp({
  steps,
  since,
  change,
  now,
}: {
  steps: string[];
  since: string;
  change?: string;
  now: number;
}) {
  return (
    <section aria-live="polite">
      <SectionHeader title={change ? "Being updated" : "Being set up"} />
      <Card className="p-5 sm:p-6">
        {change && <p className="mb-2 text-sm text-ink">{change}</p>}
        <p className="text-sm text-ink-2">
          Started {ago(since, now)}.{" "}
          {change
            ? "It keeps running as it is until the new version is tested in a practice run."
            : "It's built and tested in a practice run first, so nothing is sent until it's ready."}
        </p>
        <ol className="mt-4 space-y-2 text-sm">
          {steps.length === 0 && (
            <li className="flex items-center gap-2 text-ink">
              <span
                className="ml-1 size-2 animate-pulse rounded-full bg-accent"
                aria-hidden
              />{" "}
              Getting started…
            </li>
          )}
          {steps.map((step, i) =>
            i === steps.length - 1 ? (
              <li key={i} className="flex items-start gap-2 text-ink">
                <span
                  className="mt-1.5 ml-1 size-2 shrink-0 animate-pulse rounded-full bg-accent"
                  aria-hidden
                />
                <span>{step}…</span>
              </li>
            ) : (
              <li key={i} className="flex items-start gap-2 text-ink-3">
                <Check className="mt-0.5 size-4 shrink-0" aria-hidden />
                <span>{step}</span>
              </li>
            ),
          )}
        </ol>
      </Card>
    </section>
  );
}
