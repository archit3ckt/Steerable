"use client";

import { useState, useTransition } from "react";
import Link from "next/link";
import { Check, ChevronDown, Loader2, MessageCircle, Plug, Signpost, Sparkles, TriangleAlert } from "lucide-react";
import type { Decision, DecisionKind } from "./backend/types";
import type { DashboardActions } from "./host";
import { TraceViewer } from "./trace-viewer";
import { CooAvatar, Pill, cx, inputClass, type Tone } from "./ui";

const KIND: Record<DecisionKind, { label: string; tone: Tone; Icon: typeof Sparkles }> = {
  problem: { label: "Something came up", tone: "amber", Icon: TriangleAlert },
  approval: { label: "New idea", tone: "accent", Icon: Sparkles },
  choice: { label: "Your call", tone: "sky", Icon: Signpost },
};

type Resolved = { id: string; title: string; choice: string };

/** A list of decision cards that briefly confirms each one the owner makes. */
export function DecisionList({
  decisions,
  cooName,
  ages,
  decide,
  connections,
  tracesUrl,
}: {
  decisions: Decision[];
  cooName: string;
  ages: Record<string, string>;
  decide: DashboardActions["decide"];
  /** Whether "Connect …" can link to a Connections page. */
  connections: boolean;
  /** The host's tracesUrl: decisions with a practice or watched run show it. */
  tracesUrl?: string;
}) {
  const [resolved, setResolved] = useState<Resolved[]>([]);

  return (
    <div className="space-y-4">
      {resolved.map((r) => (
        <div
          key={r.id}
          role="status"
          className="flex animate-rise items-center gap-3 rounded-2xl border border-accent/20 bg-accent-soft px-5 py-4 text-accent"
        >
          <span className="grid size-7 shrink-0 place-items-center rounded-full bg-accent text-accent-ink">
            <Check className="size-4" strokeWidth={3} />
          </span>
          <p className="text-sm">
            <span className="font-medium">{r.choice}.</span>{" "}
            <span className="opacity-80">{cooName} is on it. You&apos;ll see it in the timeline.</span>
          </p>
        </div>
      ))}
      {decisions.map((d) => (
        <DecisionCard
          decide={decide}
          connections={connections}
          tracesUrl={tracesUrl}
          key={d.id}
          decision={d}
          cooName={cooName}
          age={ages[d.id]}
          onDecided={(choice) => setResolved((prev) => [{ id: d.id, title: d.title, choice }, ...prev].slice(0, 3))}
        />
      ))}
    </div>
  );
}

export function DecisionCard({
  decision: d,
  cooName,
  age,
  onDecided,
  decide,
  connections,
  tracesUrl,
}: {
  decision: Decision;
  cooName: string;
  age?: string;
  onDecided?: (choice: string) => void;
  decide: DashboardActions["decide"];
  connections: boolean;
  tracesUrl?: string;
}) {
  const [picked, setPicked] = useState(d.recommendation.optionId);
  const [note, setNote] = useState("");
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const kind = KIND[d.kind];
  const pickedOption = d.options.find((o) => o.id === picked);
  // Some questions come without a pick: then nothing is preselected and the owner chooses.
  const hasPick = Boolean(d.recommendation.optionId);
  const goingWithRecommendation = hasPick && picked === d.recommendation.optionId;
  const needsWords = Boolean(pickedOption?.input && !pickedOption.input.optional && !note.trim());

  function confirm() {
    setError(null);
    startTransition(async () => {
      try {
        const result = await decide(d.id, picked, pickedOption?.input ? note.trim() || undefined : undefined);
        if (result.error) setError(result.error);
        else onDecided?.(pickedOption?.label ?? "Done");
      } catch {
        setError(`That didn't go through. Try again, or ask ${cooName}.`);
      }
    });
  }

  return (
    <article
      className={cx(
        "animate-rise overflow-hidden rounded-3xl border bg-surface shadow-card transition-shadow hover:shadow-lift",
        d.urgent ? "border-rose/25" : "border-line",
        pending && "opacity-70",
      )}
    >
      {d.urgent && <div className="h-1 bg-linear-to-r from-rose/70 via-amber/60 to-transparent" />}

      <div className="p-6 sm:p-7">
        <div className="flex flex-wrap items-center gap-2">
          <Pill tone={kind.tone}>
            <kind.Icon className="size-3.5" />
            {kind.label}
          </Pill>
          {d.urgent && <Pill tone="rose">Needs you today</Pill>}
          {d.goal && <Pill>For: {d.goal}</Pill>}
          {age && <span className="ml-auto text-xs text-ink-3">{age}</span>}
        </div>

        <h3 className="mt-4 text-xl leading-snug font-semibold tracking-tight text-balance sm:text-[1.35rem]">{d.title}</h3>
        <p className="mt-2 leading-relaxed text-ink-2">{d.context}</p>

        {d.facts && d.facts.length > 0 && (
          <dl className="mt-5 flex flex-wrap gap-px overflow-hidden rounded-xl border border-line bg-line">
            {d.facts.map((f) => (
              <div key={f.label} className="min-w-36 flex-1 bg-surface px-4 py-3">
                <dt className="text-xs text-ink-3">{f.label}</dt>
                <dd className="mt-0.5 font-medium">{f.value}</dd>
              </div>
            ))}
          </dl>
        )}

        {d.concerns && d.concerns.length > 0 && (
          <div className="mt-5 rounded-xl border border-amber/25 bg-amber-soft/50 px-4 py-3">
            <p className="flex items-center gap-2 text-sm font-medium text-amber">
              <TriangleAlert className="size-4" /> What I noticed
            </p>
            <ul className="mt-1.5 list-disc space-y-1 pl-5 text-sm text-ink-2">
              {d.concerns.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          </div>
        )}

        {d.trace && <TraceViewer id={d.trace} url={tracesUrl} watched={d.id.startsWith("watch:")} />}

        {d.draft && (
          <details className="group mt-4 rounded-xl border border-line bg-surface-2/60">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-4 py-3 text-sm font-medium [&::-webkit-details-marker]:hidden">
              {d.draft.label}
              <ChevronDown className="size-4 text-ink-3 transition-transform group-open:rotate-180" />
            </summary>
            <p className="border-t border-line px-4 py-4 text-sm leading-relaxed whitespace-pre-line text-ink-2">{d.draft.body}</p>
          </details>
        )}

        {hasPick && (
          <div className="mt-6 flex gap-3 rounded-2xl bg-accent-soft/70 p-4">
            <CooAvatar name={cooName} size="sm" />
            <p className="text-sm leading-relaxed">
              <span className="font-medium">{cooName} recommends: </span>
              {d.options.find((o) => o.id === d.recommendation.optionId)?.label}.{" "}
              <span className="text-ink-2">{d.recommendation.why}</span>
            </p>
          </div>
        )}

        <fieldset className="mt-5 space-y-2" disabled={pending}>
          <legend className="sr-only">Options</legend>
          {d.options.map((o) => {
            const selected = picked === o.id;
            const recommended = o.id === d.recommendation.optionId;
            return (
              <label
                key={o.id}
                className={cx(
                  "flex cursor-pointer items-start gap-3 rounded-xl border px-4 py-3 transition-colors",
                  selected ? "border-accent bg-accent-soft/40" : "border-line hover:border-ink-3/40 hover:bg-surface-2/50",
                )}
              >
                <input
                  type="radio"
                  name={`decision-${d.id}`}
                  value={o.id}
                  checked={selected}
                  onChange={() => setPicked(o.id)}
                  className="sr-only"
                />
                <span
                  aria-hidden
                  className={cx(
                    "mt-0.5 grid size-5 shrink-0 place-items-center rounded-full border-2 transition-colors",
                    selected ? "border-accent bg-accent" : "border-ink-3/40",
                  )}
                >
                  {selected && <span className="size-1.5 rounded-full bg-accent-ink" />}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-2 font-medium">
                    {o.label}
                    {recommended && <Pill tone="accent">Recommended</Pill>}
                  </span>
                  {o.outcome && <span className="mt-0.5 block text-sm text-ink-2">{o.outcome}</span>}
                  {o.input && selected && (
                    <textarea
                      value={note}
                      onChange={(e) => setNote(e.target.value)}
                      placeholder={o.input.placeholder}
                      aria-label={o.input.placeholder}
                      rows={3}
                      maxLength={2000}
                      autoFocus
                      className={cx(inputClass, "mt-2 w-full resize-y text-sm")}
                    />
                  )}
                </span>
              </label>
            );
          })}
        </fieldset>

        {error && (
          <p role="alert" className="mt-3 text-sm text-rose">
            {error}
          </p>
        )}

        {d.connect && (connections || d.connect.provider.startsWith("value:")) && (
          <Link
            href={
              d.connect.provider.startsWith("value:")
                ? `/add/${encodeURIComponent(d.connect.provider.slice(6))}`
                : d.connect.provider.startsWith("site:")
                ? `/connections/website?url=${encodeURIComponent(`https://${d.connect.provider.slice(5)}/`)}`
                : d.connect.provider.startsWith("account:")
                  ? `/accounts/signup?site=${encodeURIComponent(d.connect.provider.slice(8))}&again=1`
                  : "/connections"
            }
            className="mt-5 flex items-center gap-3 rounded-2xl border border-accent/25 bg-accent-soft px-4 py-3 text-accent transition-shadow hover:shadow-card"
          >
            <Plug className="size-5 shrink-0" />
            <span className="flex-1 text-sm">
              <span className="font-medium">{d.connect.label}</span>
              <span className="block text-ink-2">
                {d.connect.provider.startsWith("value:") ? "One step, and it's kept private." : <>Then come back and pick &ldquo;Try again&rdquo;.</>}
              </span>
            </span>
          </Link>
        )}

        <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
          <Link
            href="/chat"
            className="inline-flex items-center gap-1.5 rounded-full px-1 text-sm text-ink-2 transition-colors hover:text-ink"
          >
            <MessageCircle className="size-4" />
            Talk it through with {cooName}
          </Link>
          <button
            type="button"
            onClick={confirm}
            disabled={pending || !picked || needsWords}
            className="inline-flex min-h-11 items-center gap-2 rounded-full bg-accent px-6 font-medium text-accent-ink shadow-sm transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-60"
          >
            {pending ? <Loader2 className="size-4 animate-spin" /> : <Check className="size-4" strokeWidth={2.5} />}
            {pending ? "Telling " + cooName + "…" : needsWords ? "Say what to change" : goingWithRecommendation ? `Go with ${cooName}'s pick` : picked ? "Confirm my choice" : "Pick one"}
          </button>
        </div>
      </div>
    </article>
  );
}
