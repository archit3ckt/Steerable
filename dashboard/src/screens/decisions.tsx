import { Suspense, type ReactNode } from "react";
import { PartyPopper } from "lucide-react";
import type { DashboardHost } from "../host";
import { ago } from "../format";
import { DecisionList } from "../decision-card";
import { AuthorizeDecision, ChoiceDecision, SignedList } from "../decision-signing";
import { DecideSmallSwitch, SettledList } from "../small-decisions";
import { Empty, PageHeader, Skeleton } from "../ui";

export function DecisionsPage({ host }: { host: DashboardHost }) {
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title="Decisions"
        subtitle="What needs you. Quick ones take a tap, choices show you the options side by side, and anything you authorize reads like what it is: something done in your name."
      />
      <Suspense fallback={<Skeleton className="h-[32rem] rounded-3xl" />}>
        <Decisions host={host} />
      </Suspense>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="text-xs font-semibold tracking-[0.08em] text-ink-3 uppercase">{title}</h2>
      {children}
    </section>
  );
}

async function Decisions({ host }: { host: DashboardHost }) {
  const backend = await host.backend();
  const [{ company }, decisions, prefs, settled, signed] = await Promise.all([
    backend.overview(),
    backend.decisions(),
    backend.preferences?.().catch(() => null) ?? null,
    backend.settledDecisions?.().catch(() => []) ?? [],
    backend.signedDecisions?.().catch(() => []) ?? [],
  ]);
  const now = await host.now();
  const { setDecideSmall, undoSettled, undoSigned } = host.actions;
  // The name on a signature: the owner's first name (the self-hosted greeting's stand-in isn't a name).
  const signer = company.ownerFirstName && company.ownerFirstName !== "there" ? company.ownerFirstName : "Owner";
  const ages = Object.fromEntries(decisions.map((d) => [d.id, ago(d.createdAt, now)]));
  const choices = decisions.filter((d) => d.display === "choice");
  const toSign = decisions.filter((d) => d.display === "authorize" && d.authorize);
  const quick = decisions.filter((d) => !choices.includes(d) && !toSign.includes(d));

  return (
    <div className="space-y-10">
      {prefs && setDecideSmall && <DecideSmallSwitch on={prefs.decideSmall} cooName={company.cooName} setOn={setDecideSmall} />}
      {decisions.length === 0 && (
        <Empty icon={<PartyPopper className="size-5" />} title="Nothing to decide">
          {company.cooName} is running things. When something needs you, it shows up here and in your morning brief.
        </Empty>
      )}
      {quick.length > 0 && (
        <Section title="Quick ones">
          <DecisionList
            decide={host.actions.decide}
            connections={host.connections}
            tracesUrl={host.tracesUrl}
            decisions={quick}
            cooName={company.cooName}
            ages={ages}
          />
        </Section>
      )}
      {choices.length > 0 && (
        <Section title="A direction to choose">
          {choices.map((d) => (
            <ChoiceDecision key={d.id} decision={d} cooName={company.cooName} age={ages[d.id]} decide={host.actions.decide} />
          ))}
        </Section>
      )}
      {toSign.length > 0 && (
        <Section title="To authorize">
          {toSign.map((d) => (
            <AuthorizeDecision
              key={d.id}
              decision={d}
              cooName={company.cooName}
              ownerName={signer}
              age={ages[d.id]}
              decide={host.actions.decide}
              tracesUrl={host.tracesUrl}
            />
          ))}
        </Section>
      )}
      {signed.length > 0 && (
        <Section title="Signed by you">
          <SignedList
            items={signed}
            ownerName={signer}
            undo={undoSigned}
            ages={Object.fromEntries(signed.flatMap((s) => [[s.id, ago(s.at, now)], ...(s.undone ? [[`undone:${s.id}`, ago(s.undone, now)]] : [])]))}
          />
        </Section>
      )}
      {settled.length > 0 && undoSettled && (
        <SettledList items={settled} undo={undoSettled} ages={Object.fromEntries(settled.map((s) => [s.id, ago(s.at, now)]))} />
      )}
    </div>
  );
}
