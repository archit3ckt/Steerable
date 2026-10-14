"use client";

import { useEffect, useRef, useState } from "react";
import {
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Database,
  Eye,
  FileText,
  Hand,
  ImageOff,
  Loader2,
  MessageSquare,
  MousePointerClick,
  ShieldAlert,
  type LucideIcon,
} from "lucide-react";
import type { Trace, TraceEvent } from "./backend/types";
import { Pill, cx, type Tone } from "./ui";

const KIND: Record<TraceEvent["kind"], { Icon: LucideIcon; label?: string; tone?: Tone }> = {
  step: { Icon: ChevronRight },
  browse: { Icon: MousePointerClick },
  would: { Icon: Eye, label: "Would do", tone: "amber" },
  did: { Icon: Check, label: "Done after a check", tone: "accent" },
  held: { Icon: Hand, label: "Held back", tone: "rose" },
  record: { Icon: Database, label: "Your records", tone: "sky" },
  message: { Icon: MessageSquare, label: "Tells you", tone: "violet" },
  draft: { Icon: FileText, label: "Saves", tone: "neutral" },
  unasked: { Icon: ShieldAlert, label: "Didn't say first", tone: "rose" },
};

/** Things that change something outside: what the owner must see first. */
const ACTIONS = new Set<TraceEvent["kind"]>(["would", "did", "held"]);

/**
 * A routine's practice run (before the owner switches it on) or a watched run, from the host's
 * tracesUrl: first everything it would do (or did, or held back) that can't be undone, then what it
 * changes in the records and tells the owner, then every step with pictures of the pages it went
 * through. Loaded when opened.
 */
export function TraceViewer({
  id,
  url,
  open: startOpen = false,
  showReview = false,
  watched = false,
}: {
  id: string;
  url?: string;
  open?: boolean;
  /** A watched (live) run, not a practice run. */
  watched?: boolean;
  /** Show the COO's read of a practice run (a decision already says it). */
  showReview?: boolean;
}) {
  const [open, setOpen] = useState(startOpen);
  const [trace, setTrace] = useState<Trace | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || trace || !url) return;
    let gone = false;
    fetch(`${url}?id=${encodeURIComponent(id)}`, { cache: "no-store" })
      .then(async (res) => {
        const data = (await res.json()) as Trace & { error?: string };
        if (!res.ok) throw new Error(data.error ?? "This run couldn't be loaded.");
        if (!gone) setTrace(data);
      })
      .catch((e) => !gone && setError(e instanceof Error ? e.message : "This run couldn't be loaded."));
    return () => {
      gone = true;
    };
  }, [open, trace, url, id]);

  if (!url) return null;
  const label = watched ? "See what it did, step by step" : "See exactly what it would do";

  return (
    <div className="mt-4 rounded-xl border border-line bg-surface-2/60">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-2 px-4 py-3 text-left text-sm font-medium"
      >
        <span className="flex items-center gap-2">
          <Eye className="size-4 text-accent" />
          {label}
        </span>
        <ChevronDown className={cx("size-4 text-ink-3 transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="border-t border-line px-4 py-4">
          {error ? (
            <p className="text-sm text-ink-3">{error}</p>
          ) : !trace ? (
            <p className="flex items-center gap-2 text-sm text-ink-3">
              <Loader2 className="size-4 animate-spin" /> Loading the run…
            </p>
          ) : (
            <TraceBody trace={trace} url={url} showReview={showReview} />
          )}
        </div>
      )}
    </div>
  );
}

function TraceBody({ trace, url, showReview }: { trace: Trace; url: string; showReview: boolean }) {
  const practice = trace.kind === "practice";
  const actions = trace.events.filter((e) => ACTIONS.has(e.kind));
  const unasked = trace.events.filter((e) => e.kind === "unasked");
  const effects = trace.events.filter((e) => e.kind === "record" || e.kind === "message" || e.kind === "draft");
  const pictured = trace.events.filter((e) => e.shot);
  const [at, setAt] = useState<number | null>(null);
  const shotUrl = (shot: string) => `${url}?id=${encodeURIComponent(trace.id)}&shot=${encodeURIComponent(shot)}`;

  const player = useRef<HTMLElement>(null);
  const show = (e: TraceEvent) => {
    setAt(pictured.findIndex((p) => p.n === e.n));
    player.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  };

  return (
    <div className="space-y-6">
      {practice && (
        <p className="text-sm text-ink-2">
          A practice run: it went through everything for real, but nothing was sent, submitted, paid or posted.
        </p>
      )}
      {showReview && trace.review?.summary && <p className="text-sm leading-relaxed text-ink">{trace.review.summary}</p>}

      <section>
        <h4 className="text-xs font-semibold tracking-wide text-ink-3 uppercase">
          {practice ? "What it would do that can't be undone" : "What it did that can't be undone"}
        </h4>
        {actions.length || unasked.length ? (
          <ol className="mt-2 space-y-2">
            {actions.map((e) => (
              <ActionItem key={e.n} event={e} shotUrl={shotUrl} onPicture={() => show(e)} />
            ))}
            {unasked.length > 0 && <Unasked events={unasked} />}
          </ol>
        ) : (
          <p className="mt-2 text-sm text-ink-3">Nothing: it only looked things up{effects.length ? " and kept notes" : ""}.</p>
        )}
      </section>

      {effects.length > 0 && (
        <section>
          <h4 className="text-xs font-semibold tracking-wide text-ink-3 uppercase">
            {practice ? "What it would note and tell you" : "What it noted and told you"}
          </h4>
          <ul className="mt-2 divide-y divide-line rounded-xl border border-line bg-surface">
            {effects.map((e) => (
              <li key={e.n} className="flex gap-3 px-3 py-2.5 text-sm">
                <Icon kind={e.kind} />
                <div className="min-w-0 flex-1">
                  <p className="font-medium">{e.title}</p>
                  {e.detail && <p className="mt-0.5 line-clamp-4 text-ink-2 whitespace-pre-line">{e.detail}</p>}
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {pictured.length > 0 && (
        <section ref={player}>
          <h4 className="text-xs font-semibold tracking-wide text-ink-3 uppercase">The pages it went through</h4>
          <Player events={pictured} at={at ?? 0} setAt={setAt} shotUrl={shotUrl} />
        </section>
      )}

      <details className="group">
        <summary className="flex cursor-pointer list-none items-center gap-1.5 text-sm text-ink-2 hover:text-ink [&::-webkit-details-marker]:hidden">
          <ChevronDown className="size-4 transition-transform group-open:rotate-180" />
          Every step ({trace.events.length})
        </summary>
        <ol className="mt-3 space-y-1.5 border-l border-line pl-4 text-sm">
          {trace.events.map((e) =>
            e.kind === "step" ? (
              <li key={e.n} className="-ml-4 pt-2 pl-4 text-xs font-semibold text-ink">
                {e.title}
              </li>
            ) : (
              <li key={e.n} className="flex items-start gap-2 text-ink-2">
                <Icon kind={e.kind} small />
                <span className="min-w-0 flex-1">
                  {e.title}
                  {e.url && <span className="block truncate text-xs text-ink-3">{e.url.replace(/^https?:\/\//, "")}</span>}
                </span>
                {e.shot && (
                  <button type="button" onClick={() => show(e)} className="shrink-0 text-xs text-accent hover:underline">
                    Picture
                  </button>
                )}
              </li>
            ),
          )}
        </ol>
      </details>
    </div>
  );
}

function Icon({ kind, small }: { kind: TraceEvent["kind"]; small?: boolean }) {
  const k = KIND[kind];
  const tone = k.tone ?? "neutral";
  const colors: Record<Tone, string> = {
    neutral: "bg-surface-2 text-ink-3",
    accent: "bg-accent-soft text-accent",
    amber: "bg-amber-soft text-amber",
    rose: "bg-rose-soft text-rose",
    sky: "bg-sky-soft text-sky",
    violet: "bg-violet-soft text-violet",
  };
  return (
    <span className={cx("grid shrink-0 place-items-center rounded-full", small ? "mt-0.5 size-4" : "size-6", colors[tone])} aria-hidden>
      <k.Icon className={small ? "size-2.5" : "size-3.5"} />
    </span>
  );
}

function ActionItem({ event: e, shotUrl, onPicture }: { event: TraceEvent; shotUrl: (s: string) => string; onPicture: () => void }) {
  const k = KIND[e.kind];
  return (
    <li
      className={cx(
        "flex gap-3 rounded-xl border bg-surface p-3",
        e.kind === "held" || e.kind === "unasked" ? "border-rose/30" : "border-line",
      )}
    >
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          {k.label && (
            <Pill tone={k.tone}>
              <k.Icon className="size-3" />
              {e.unasked && e.kind === "would" ? "Would do, without saying first" : k.label}
            </Pill>
          )}
        </div>
        <p className="mt-1.5 text-sm font-medium">{e.title}</p>
        {e.why && <p className="mt-1 text-sm text-ink-2">{e.why}</p>}
        {e.detail && (
          <details className="mt-1.5">
            <summary className="cursor-pointer text-xs text-ink-3 hover:text-ink-2">Details</summary>
            <p className="mt-1 text-xs leading-relaxed text-ink-2 whitespace-pre-line">{e.detail}</p>
          </details>
        )}
      </div>
      {e.shot && (
        <button
          type="button"
          onClick={onPicture}
          className="shrink-0 self-start overflow-hidden rounded-lg border border-line"
          aria-label="See the page at that moment"
        >
          <Shot src={shotUrl(e.shot)} box={e.box} tone={e.kind} className="w-24 sm:w-32" thin />
        </button>
      )}
    </li>
  );
}

const MARK: Partial<Record<TraceEvent["kind"], string>> = {
  would: "border-amber shadow-[0_0_0_4px_color-mix(in_oklab,var(--color-amber)_25%,transparent)]",
  held: "border-rose shadow-[0_0_0_4px_color-mix(in_oklab,var(--color-rose)_25%,transparent)]",
};

/** A picture of the page, with the element it clicked, typed into or is about to press marked on it. */
function Shot({
  src,
  alt = "",
  box,
  tone,
  className,
  thin,
  onError,
}: {
  src: string;
  alt?: string;
  box?: TraceEvent["box"];
  tone: TraceEvent["kind"];
  className?: string;
  thin?: boolean;
  onError?: () => void;
}) {
  const pad = thin ? 2 : 5; // a little room around the element, so the mark doesn't cover it
  return (
    <span className={cx("relative block", className)}>
      {/* eslint-disable-next-line @next/next/no-img-element -- a private picture from the engine, through the host's route */}
      <img src={src} alt={alt} loading="lazy" className="block h-auto w-full" onError={onError} />
      {box && (
        <span
          aria-hidden
          className={cx(
            "pointer-events-none absolute rounded-md",
            thin ? "border" : "border-2",
            MARK[tone] ?? "border-accent shadow-[0_0_0_4px_color-mix(in_oklab,var(--color-accent)_25%,transparent)]",
          )}
          style={{
            left: `calc(${box[0] * 100}% - ${pad}px)`,
            top: `calc(${box[1] * 100}% - ${pad}px)`,
            width: `calc(${box[2] * 100}% + ${pad * 2}px)`,
            height: `calc(${box[3] * 100}% + ${pad * 2}px)`,
          }}
        />
      )}
    </span>
  );
}

/** What the routine sent to a site without saying first, as one card: by site, each with what it sent. */
function Unasked({ events }: { events: TraceEvent[] }) {
  const sites = [...new Set(events.map((e) => (e.url ?? "").replace(/^https?:\/\//, "").split("/")[0]).filter(Boolean))];
  return (
    <li className="rounded-xl border border-rose/30 bg-surface p-3">
      <Pill tone="rose">
        <ShieldAlert className="size-3" />
        Didn&apos;t say first
      </Pill>
      <p className="mt-1.5 text-sm font-medium">
        Sent {events.length === 1 ? "something" : `${events.length} things`} to {sites.join(", ")} without saying what first
      </p>
      <p className="mt-1 text-sm text-ink-2">
        A form or a click on the site sent this, and the routine didn&apos;t name it beforehand. Check it&apos;s only looking, not changing
        anything.
      </p>
      <details className="mt-1.5">
        <summary className="cursor-pointer text-xs text-ink-3 hover:text-ink-2">What was sent</summary>
        <ul className="mt-1 space-y-2">
          {events.map((e) => (
            <li key={e.n} className="text-xs text-ink-2">
              <span className="font-medium break-all">{(e.url ?? "").replace(/^https?:\/\//, "")}</span>
              {e.detail && <span className="mt-0.5 block whitespace-pre-line">{e.detail}</span>}
            </li>
          ))}
        </ul>
      </details>
    </li>
  );
}

/** One picture at a time, with what it was doing then; arrows (or the keyboard's) to move through them. */
function Player({
  events,
  at,
  setAt,
  shotUrl,
}: {
  events: TraceEvent[];
  at: number;
  setAt: (n: number) => void;
  shotUrl: (s: string) => string;
}) {
  const i = Math.min(Math.max(at, 0), events.length - 1);
  const e = events[i];
  const [broken, setBroken] = useState<Record<string, boolean>>({});
  const k = KIND[e.kind];

  return (
    <div
      className="mt-2 overflow-hidden rounded-xl border border-line bg-surface focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      tabIndex={0}
      onKeyDown={(ev) => {
        if (ev.key === "ArrowRight" && i < events.length - 1) setAt(i + 1);
        if (ev.key === "ArrowLeft" && i > 0) setAt(i - 1);
      }}
      aria-label="Pictures of the pages it went through. Use the arrow keys to move."
    >
      <div className="bg-surface-2">
        {broken[e.shot!] ? (
          <div className="grid aspect-[16/10] place-items-center text-sm text-ink-3">
            <span className="flex items-center gap-2">
              <ImageOff className="size-4" /> This picture isn&apos;t kept any more.
            </span>
          </div>
        ) : (
          <Shot
            key={e.shot}
            src={shotUrl(e.shot!)}
            alt={e.title}
            box={e.box}
            tone={e.kind}
            onError={() => setBroken((b) => ({ ...b, [e.shot!]: true }))}
          />
        )}
      </div>
      <div className="flex items-center gap-3 border-t border-line px-3 py-2.5">
        <button
          type="button"
          onClick={() => setAt(i - 1)}
          disabled={i === 0}
          aria-label="Previous"
          className="grid size-9 shrink-0 place-items-center rounded-full border border-line text-ink-2 hover:bg-surface-2 disabled:opacity-40"
        >
          <ChevronLeft className="size-4" />
        </button>
        <div className="min-w-0 flex-1 text-sm">
          <p className="flex flex-wrap items-center gap-2">
            {k.label && <Pill tone={k.tone}>{k.label}</Pill>}
            <span className="font-medium">{e.title}</span>
          </p>
          <p className="mt-0.5 truncate text-xs text-ink-3">
            {i + 1} of {events.length}
            {e.url ? ` · ${e.url.replace(/^https?:\/\//, "")}` : ""}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setAt(i + 1)}
          disabled={i === events.length - 1}
          aria-label="Next"
          className="grid size-9 shrink-0 place-items-center rounded-full border border-line text-ink-2 hover:bg-surface-2 disabled:opacity-40"
        >
          <ChevronRight className="size-4" />
        </button>
      </div>
    </div>
  );
}
