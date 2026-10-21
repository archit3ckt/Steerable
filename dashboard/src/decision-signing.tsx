"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import { Check, Info, Loader2, PenLine, TriangleAlert, Undo2 } from "lucide-react";
import type { Decision, SignedDecision } from "./backend/types";
import type { DashboardActions } from "./host";
import { TraceViewer } from "./trace-viewer";
import { cx, inputClass } from "./ui";

const HOLD_MS = 1200; // how long "Sign" is held down
const SHOW_SIGNED_MS = 1400; // the signature and seal play out before the decision goes in (and the card makes way)
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function initials(name: string): string {
  return name.trim().split(/\s+/).map((w) => w[0] ?? "").join("").slice(0, 2).toUpperCase() || "✓";
}

function dated(d: Date): string {
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}, ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

// ---------- a direction to choose ----------

/** A choice of direction: its options side by side as cards, each with its case; pick one, then confirm. */
export function ChoiceDecision({
  decision: d,
  cooName,
  age,
  decide,
}: {
  decision: Decision;
  cooName: string;
  age?: string;
  decide: DashboardActions["decide"];
}) {
  const [picked, setPicked] = useState("");
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const chosen = d.options.find((o) => o.id === picked);

  function go() {
    setError(null);
    startTransition(async () => {
      try {
        const result = await decide(d.id, picked);
        if (result.error) setError(result.error);
        else setDone(true);
      } catch {
        setError(`That didn't go through. Try again, or ask ${cooName}.`);
      }
    });
  }

  return (
    <article className="animate-rise rounded-3xl border border-line bg-surface p-5 shadow-card sm:p-7">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-[11px] font-semibold tracking-[0.14em] text-ink-3 uppercase">A direction to choose</span>
        {age && <span className="text-xs text-ink-3">{age}</span>}
      </div>
      <h3 className="mt-2 font-display text-3xl leading-tight" dir="auto">{d.title}</h3>
      {d.context && <p className="mt-2 text-ink-2" dir="auto">{d.context}</p>}

      <div className={cx("mt-6 grid gap-4 sm:grid-cols-2", d.options.length >= 3 && "lg:grid-cols-3")}>
        {d.options.map((o) => {
          const on = o.id === picked;
          const theirs = o.id === d.recommendation.optionId;
          return (
            <button
              key={o.id}
              type="button"
              aria-pressed={on}
              disabled={done || pending}
              onClick={() => setPicked(on ? "" : o.id)}
              className={cx(
                "relative flex flex-col gap-4 rounded-2xl border bg-surface p-5 text-start transition-all duration-300 motion-safe:hover:-translate-y-0.5",
                on ? "border-2 border-accent shadow-lift ring-4 ring-accent/15 motion-safe:-translate-y-1" : "border-line shadow-card",
                picked && !on && "opacity-55",
              )}
            >
              {theirs && (
                <span className="absolute -top-3 left-5 rounded-full bg-accent px-2.5 py-0.5 text-xs font-semibold text-accent-ink">
                  {cooName}&apos;s pick
                </span>
              )}
              <span className="flex items-start justify-between gap-3">
                <span className="font-display text-2xl leading-tight" dir="auto">{o.label}</span>
                <span
                  aria-hidden
                  className={cx("grid size-6 shrink-0 place-items-center rounded-full", on ? "bg-accent text-accent-ink" : "border-2 border-line")}
                >
                  {on && <Check className="size-3.5" strokeWidth={3} />}
                </span>
              </span>
              {o.outcome && <span className="text-sm text-ink-2" dir="auto">{o.outcome}</span>}
              {!!o.pros?.length && (
                <span className="flex flex-col gap-1.5">
                  <span className="text-[11px] font-semibold tracking-wider text-accent uppercase">For</span>
                  {o.pros.map((p) => (
                    <span key={p} className="flex gap-2 text-sm" dir="auto">
                      <span aria-hidden className="font-semibold text-accent">+</span>
                      {p}
                    </span>
                  ))}
                </span>
              )}
              {!!o.cons?.length && (
                <span className="flex flex-col gap-1.5">
                  <span className="text-[11px] font-semibold tracking-wider text-amber uppercase">Against</span>
                  {o.cons.map((c) => (
                    <span key={c} className="flex gap-2 text-sm" dir="auto">
                      <span aria-hidden className="font-semibold text-amber">−</span>
                      {c}
                    </span>
                  ))}
                </span>
              )}
              {!!o.tags?.length && (
                <span className="mt-auto flex flex-wrap gap-1.5">
                  {o.tags.map((t) => (
                    <span key={t} className="rounded-full bg-surface-2 px-2.5 py-1 text-xs text-ink-2">
                      {t}
                    </span>
                  ))}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {d.recommendation.why && !picked && (
        <p className="mt-4 text-sm text-ink-2">
          <span className="font-medium text-ink">{cooName}:</span> {d.recommendation.why}
        </p>
      )}
      {chosen && !done && (
        <div className="mt-5 flex animate-rise flex-wrap items-center justify-between gap-3 rounded-2xl border border-line bg-surface p-4 shadow-lift">
          <p className="text-sm sm:text-base">
            You chose <span className="font-semibold">{chosen.label}</span>.
          </p>
          <div className="flex gap-2">
            <button type="button" onClick={() => setPicked("")} disabled={pending} className="min-h-11 rounded-xl border border-line px-4 text-sm text-ink-2 hover:text-ink">
              Change
            </button>
            <button type="button" onClick={go} disabled={pending} className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-accent px-5 text-sm font-medium text-accent-ink hover:bg-accent-hover">
              {pending && <Loader2 className="size-4 animate-spin" aria-hidden />}
              Go with this
            </button>
          </div>
        </div>
      )}
      {done && chosen && (
        <p role="status" className="mt-5 flex animate-rise items-center gap-3 rounded-2xl bg-accent-soft p-4 text-sm text-accent">
          <span className="grid size-7 shrink-0 place-items-center rounded-full bg-accent text-accent-ink">
            <Check className="size-4" strokeWidth={3} />
          </span>
          <span>
            <span className="font-medium">Decided: {chosen.label}.</span> {cooName} is on it.
          </span>
        </p>
      )}
      {error && <p role="alert" className="mt-4 rounded-xl bg-rose-soft px-3 py-2 text-sm text-rose">{error}</p>}
    </article>
  );
}

// ---------- something to authorize ----------

/** Press and hold to sign: a ring fills; letting go early cancels. Space or Enter held does the same. */
function HoldToSign({ onSigned, disabled }: { onSigned: () => void; disabled?: boolean }) {
  const [progress, setProgress] = useState(0);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => () => {
    if (timer.current) clearInterval(timer.current);
  }, []);

  function begin() {
    if (disabled || timer.current) return;
    const from = performance.now();
    timer.current = setInterval(() => {
      const p = Math.min(1, (performance.now() - from) / HOLD_MS);
      setProgress(p);
      if (p >= 1) {
        if (timer.current) clearInterval(timer.current);
        timer.current = null;
        onSigned();
      }
    }, 16);
  }
  function end() {
    if (!timer.current) return;
    clearInterval(timer.current);
    timer.current = null;
    setProgress(0);
  }

  const holding = progress > 0 && progress < 1;
  return (
    <div className="flex flex-col items-center gap-2">
      <button
        type="button"
        aria-label="Hold to sign"
        disabled={disabled}
        onPointerDown={(e) => {
          e.preventDefault();
          begin();
        }}
        onPointerUp={end}
        onPointerLeave={end}
        onPointerCancel={end}
        onKeyDown={(e) => {
          if ((e.key === " " || e.key === "Enter") && !e.repeat) {
            e.preventDefault();
            begin();
          }
        }}
        onKeyUp={(e) => (e.key === " " || e.key === "Enter") && end()}
        onContextMenu={(e) => e.preventDefault()}
        className="relative grid size-24 touch-none place-items-center rounded-full bg-surface text-accent shadow-lift select-none disabled:opacity-60"
      >
        <svg aria-hidden viewBox="0 0 104 104" className="absolute inset-0 size-full -rotate-90">
          <circle cx="52" cy="52" r="46" fill="none" className="stroke-line" strokeWidth="6" />
          <circle
            cx="52"
            cy="52"
            r="46"
            fill="none"
            className="stroke-accent"
            strokeWidth="6"
            strokeLinecap="round"
            strokeDasharray="289.03"
            strokeDashoffset={289.03 * (1 - progress)}
          />
        </svg>
        <span className="relative flex flex-col items-center gap-0.5 text-sm font-semibold">
          <PenLine className="size-5" aria-hidden />
          Sign
        </span>
      </button>
      <span className="text-xs text-ink-3">{holding ? "Keep holding…" : "Press and hold"}</span>
    </div>
  );
}

/**
 * Something the owner authorizes: a document of what it will do, its limits, what it won't do and how
 * to undo it, signed by pressing and holding. The signature and seal play out first, then it's decided.
 */
export function AuthorizeDecision({
  decision: d,
  cooName,
  ownerName,
  age,
  decide,
  tracesUrl,
}: {
  decision: Decision;
  cooName: string;
  ownerName: string;
  age?: string;
  decide: DashboardActions["decide"];
  tracesUrl?: string;
}) {
  const a = d.authorize!;
  const [signedAt, setSignedAt] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [other, setOther] = useState("");
  const [note, setNote] = useState("");
  const [pending, startTransition] = useTransition();
  const later = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (later.current) clearTimeout(later.current);
  }, []);
  const others = d.options.filter((o) => o.id !== a.optionId);
  const otherOption = others.find((o) => o.id === other);

  function signed() {
    setError(null);
    setSignedAt(new Date());
    later.current = setTimeout(() => {
      startTransition(async () => {
        try {
          const result = await decide(d.id, a.optionId);
          if (result.error) {
            setSignedAt(null);
            setError(result.error);
          }
        } catch {
          setSignedAt(null);
          setError(`That didn't go through. Try again, or ask ${cooName}.`);
        }
      });
    }, SHOW_SIGNED_MS);
  }

  function pickOther(id: string) {
    const o = others.find((x) => x.id === id);
    if (o?.input && other !== id) return setOther(id);
    setError(null);
    startTransition(async () => {
      try {
        const result = await decide(d.id, id, o?.input ? note.trim() || undefined : undefined);
        if (result.error) setError(result.error);
      } catch {
        setError(`That didn't go through. Try again, or ask ${cooName}.`);
      }
    });
  }

  const clauses = [
    { title: "What it will do", lines: a.does },
    { title: "Its limits", lines: a.limits },
    { title: "What it won't do", lines: a.wont },
    { title: "How you can undo it", lines: [a.undo] },
  ].filter((c) => c.lines.length);

  return (
    <div className="animate-rise">
      <article className="relative rounded-md border border-line bg-[color-mix(in_oklab,var(--surface)_96%,var(--amber-soft))] px-5 py-7 shadow-lift sm:px-12 sm:py-10">
        <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line pb-3">
          <span className="text-[11px] font-semibold tracking-[0.16em] text-ink-3 uppercase">Authorization</span>
          {age && <span className="text-xs text-ink-3">Asked {age}</span>}
        </div>
        <h3 className="mt-5 font-display text-3xl leading-tight sm:text-4xl" dir="auto">{a.title}</h3>
        <p className="mt-4 font-display text-lg leading-relaxed text-ink-2 sm:text-xl">
          I let {cooName}, my business manager, do this in my name:
        </p>
        <ol className="mt-5 space-y-4">
          {clauses.map((c, i) => (
            <li key={c.title} className="grid grid-cols-[2rem_minmax(0,1fr)] gap-1">
              <span className="font-display text-xl text-ink-3">{i + 1}.</span>
              <div>
                <p className="text-sm font-semibold">{c.title}</p>
                {c.lines.map((l) => (
                  <p key={l} className="mt-0.5 text-[15px] leading-relaxed text-ink-2" dir="auto">{l}</p>
                ))}
              </div>
            </li>
          ))}
        </ol>
        {a.record && (
          <p className="mt-6 flex gap-2.5 rounded-xl bg-surface-2 px-4 py-3 text-sm text-ink-2">
            <Info className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
            {a.record}
          </p>
        )}
        {!!d.concerns?.length && (
          <div className="mt-4 rounded-xl bg-amber-soft px-4 py-3 text-sm text-amber">
            <p className="flex items-center gap-2 font-medium">
              <TriangleAlert className="size-4" aria-hidden /> Before you sign
            </p>
            <ul className="mt-1.5 list-disc space-y-1 ps-5">
              {d.concerns.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          </div>
        )}
        {d.trace && (
          <div className="mt-4">
            <TraceViewer id={d.trace} url={tracesUrl} watched={d.id.startsWith("watch:")} />
          </div>
        )}

        <div className="mt-8 flex flex-col gap-6 sm:flex-row sm:items-end sm:justify-between">
          <div className="flex-1">
            <div className="relative h-14 border-b-[1.5px] border-ink">
              {signedAt && (
                <span className="absolute bottom-1 left-1 animate-write font-display text-4xl text-sky italic">{ownerName}</span>
              )}
            </div>
            <div className="mt-1.5 flex justify-between text-xs text-ink-3">
              <span>{ownerName}, owner</span>
              <span>{signedAt ? dated(signedAt) : "Date"}</span>
            </div>
          </div>
          <div className="flex justify-center sm:w-36">
            {signedAt ? (
              <div
                role="img"
                aria-label="Signed"
                className="grid size-32 animate-stamp place-items-center rounded-full border-[3px] border-accent text-accent opacity-90 shadow-[inset_0_0_0_5px_var(--surface),inset_0_0_0_7px_var(--accent)]"
              >
                <span className="flex flex-col items-center">
                  <span className="text-[10px] font-semibold tracking-[0.2em] uppercase">Signed</span>
                  <span className="font-display text-3xl leading-none">{initials(ownerName)}</span>
                  <span className="mt-0.5 text-[10px] font-semibold tracking-wider">
                    {String(signedAt.getDate()).padStart(2, "0")}.{String(signedAt.getMonth() + 1).padStart(2, "0")}.{signedAt.getFullYear()}
                  </span>
                </span>
              </div>
            ) : (
              <HoldToSign onSigned={signed} disabled={pending} />
            )}
          </div>
        </div>
      </article>

      {!signedAt && others.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-2 px-1">
          <span className="text-sm text-ink-3">Not this?</span>
          {others.map((o) => (
            <button
              key={o.id}
              type="button"
              disabled={pending}
              onClick={() => pickOther(o.id)}
              className={cx("min-h-11 rounded-xl px-3 text-sm hover:bg-surface-2", other === o.id ? "text-ink" : "text-ink-2")}
            >
              {o.label}
            </button>
          ))}
        </div>
      )}
      {otherOption?.input && !signedAt && (
        <div className="mt-2 flex animate-rise flex-col gap-2 px-1 sm:flex-row">
          <textarea
            rows={2}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder={otherOption.input.placeholder}
            className={cx(inputClass, "flex-1 resize-y")}
            aria-label={otherOption.input.placeholder}
          />
          <button
            type="button"
            disabled={pending || (!otherOption.input.optional && !note.trim())}
            onClick={() => pickOther(otherOption.id)}
            className="inline-flex min-h-11 items-center justify-center gap-2 self-start rounded-xl bg-accent px-4 text-sm font-medium text-accent-ink disabled:opacity-60"
          >
            {pending && <Loader2 className="size-4 animate-spin" aria-hidden />}
            {otherOption.label}
          </button>
        </div>
      )}
      {error && <p role="alert" className="mt-3 rounded-xl bg-rose-soft px-3 py-2 text-sm text-rose">{error}</p>}
    </div>
  );
}

// ---------- what the owner signed ----------

/** "Signed by you": each signature with its seal, and Undo. */
export function SignedList({
  items,
  ownerName,
  ages,
  undo,
}: {
  items: SignedDecision[];
  ownerName: string;
  ages: Record<string, string>;
  undo?: DashboardActions["undoSigned"];
}) {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="rounded-3xl border border-line bg-surface">
      {items.map((s, i) => (
        <div key={s.id} className={cx("flex items-center gap-4 px-5 py-4", i > 0 && "border-t border-line")}>
          <span
            aria-hidden
            className={cx(
              "grid size-10 shrink-0 -rotate-[8deg] place-items-center rounded-full border-2 font-display text-lg",
              s.undone ? "border-line text-ink-3" : "border-accent text-accent",
            )}
          >
            {initials(ownerName)}
          </span>
          <div className="min-w-0 flex-1">
            <p className={cx("text-sm font-medium", s.undone && "text-ink-3 line-through")} dir="auto">{s.title}</p>
            <p className="text-xs text-ink-3">{s.undone ? `Undone ${ages[`undone:${s.id}`] ?? ""}` : `Signed ${ages[s.id] ?? ""}`}</p>
          </div>
          {!s.undone && undo && (
            <button
              type="button"
              disabled={Boolean(busy)}
              onClick={async () => {
                setBusy(s.id);
                setError(null);
                const result = await undo(s.id);
                setBusy("");
                if (result.error) setError(result.error);
              }}
              className="inline-flex min-h-11 shrink-0 items-center gap-1.5 rounded-xl border border-line px-3 text-sm text-ink-2 hover:border-accent hover:text-ink disabled:opacity-60"
            >
              {busy === s.id ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Undo2 className="size-4" aria-hidden />}
              Undo
            </button>
          )}
        </div>
      ))}
      {error && <p role="alert" className="mx-5 mb-4 rounded-xl bg-rose-soft px-3 py-2 text-sm text-rose">{error}</p>}
    </div>
  );
}
