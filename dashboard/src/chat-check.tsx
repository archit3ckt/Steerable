"use client";

import { Check as CheckIcon, ChevronRight, FlaskConical, Globe, Loader2, RotateCcw } from "lucide-react";
import { useEffect, useState, useTransition } from "react";
import type { Check, CheckKind, CheckResult } from "./backend/types";
import { openPlan } from "./chat-artifacts";
import type { DashboardActions } from "./host";
import { Pill, cx } from "./ui";

const KINDS: Record<CheckKind, { button: string; running: string; title: string; what: string }> = {
  customers: { button: "Test it with customers", running: "Three customers are going through it", title: "Customer test",
    what: "Three of your likely customers go through it and say where they get stuck." },
  numbers: { button: "Check the numbers", running: "Checking every figure", title: "Numbers check",
    what: "Every figure is worked out again, against what you've told me about the business." },
  week: { button: "Try it on a normal week", running: "Running an ordinary week through it", title: "A normal week",
    what: "An ordinary week is run through it step by step, to find where it stalls." },
  pushback: { button: "Hear the pushback", running: "Three people are pushing back on it", title: "Pushback",
    what: "Three people who'd doubt it make their strongest case against it." },
};
const POLL_MS = 2500;

/**
 * Under a reply that proposes something: a button that tests it before the owner acts on it (the
 * engine's checks.py), and the result: what held up, what broke and for whom, and exact edits the
 * owner picks. Edits to a plan become its next version; edits to a reply go to the COO in the chat.
 */
export function ChatCheck({
  messageId,
  kind,
  cooName,
  url,
  startCheck,
  applyCheck,
  sendMessage,
}: {
  messageId: string;
  kind: CheckKind;
  cooName: string;
  url: string;
  startCheck: DashboardActions["startCheck"];
  applyCheck: DashboardActions["applyCheck"];
  sendMessage: DashboardActions["sendMessage"];
}) {
  const [check, setCheck] = useState<Check | null>(null); // null: not asked yet
  const [error, setError] = useState<string | null>(null);
  const [starting, startTransition] = useTransition();
  const running = check?.status === "running";

  // What's there already (a test run before a reload), then, while one runs, how it's going.
  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = () =>
      fetch(`${url}?message=${messageId}`, { cache: "no-store" })
        .then((res) => (res.ok ? (res.json() as Promise<Check>) : null))
        .then((found) => {
          if (!live || !found) return;
          setCheck(found);
          if (found.status === "running") timer = setTimeout(load, POLL_MS);
        })
        .catch(() => live && (timer = setTimeout(load, POLL_MS * 2)));
    if (check === null || running) timer = setTimeout(load, check === null ? 0 : POLL_MS);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [url, messageId, running]); // eslint-disable-line react-hooks/exhaustive-deps -- check: only whether it's loaded

  const label = KINDS[kind] ?? KINDS.customers;
  const start = () =>
    startTransition(async () => {
      setError(null);
      const result = await startCheck(messageId, kind);
      if (result.error) setError(result.error);
      else if (result.check) setCheck(result.check);
    });

  if (check === null) return null;
  if (check.status === "none" || check.status === "failed") {
    return (
      <div className="mt-2">
        <button
          type="button"
          onClick={start}
          disabled={starting}
          title={`${label.what} It uses a little of this month's included work.`}
          className="inline-flex items-center gap-2 rounded-full border border-line bg-surface px-3.5 py-1.5 text-sm text-ink-2 transition-colors hover:border-accent hover:text-ink disabled:opacity-60"
        >
          {starting ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <FlaskConical className="size-4 text-accent" aria-hidden />}
          {check.status === "failed" ? "Try the test again" : label.button}
        </button>
        {(error || (check.status === "failed" && check.error)) && (
          <p role="alert" className="mt-1.5 text-sm text-rose">
            {error ?? (check.status === "failed" ? check.error : "")}
          </p>
        )}
      </div>
    );
  }
  if (check.status === "running") {
    return (
      <p className="mt-2 inline-flex items-center gap-2 rounded-full bg-surface-2 px-3.5 py-1.5 text-sm text-ink-2" aria-live="polite">
        <Loader2 className="size-4 animate-spin" aria-hidden /> {label.running}…
      </p>
    );
  }
  return (
    <CheckCard
      messageId={messageId}
      check={check}
      label={label}
      cooName={cooName}
      onRetest={start}
      retesting={starting}
      applyCheck={applyCheck}
      sendMessage={sendMessage}
      onApplied={(applied) => setCheck({ ...check, applied: [...(check.applied ?? []), ...applied], planChanged: false })}
    />
  );
}

function CheckCard({
  messageId,
  check,
  label,
  cooName,
  onRetest,
  retesting,
  applyCheck,
  sendMessage,
  onApplied,
}: {
  messageId: string;
  check: Extract<Check, { status: "done" }>;
  label: (typeof KINDS)[CheckKind];
  cooName: string;
  onRetest: () => void;
  retesting: boolean;
  applyCheck: DashboardActions["applyCheck"];
  sendMessage: DashboardActions["sendMessage"];
  onApplied: (applied: string[]) => void;
}) {
  const { result, plan } = check;
  const applied = new Set(check.applied ?? []);
  // Edits to a plan must still fit its text; edits to a reply go to the COO in words, so all of them can.
  const usable = result.edits.filter((e) => !applied.has(e.id) && (!plan || e.applies));
  const [picked, setPicked] = useState<Set<string>>(() => new Set(usable.map((e) => e.id)));
  const [pending, startTransition] = useTransition();
  const [note, setNote] = useState<{ text: string; error?: boolean } | null>(null);
  const broke = result.findings.length;

  const use = () =>
    startTransition(async () => {
      const ids = usable.filter((e) => picked.has(e.id)).map((e) => e.id);
      if (!ids.length) return;
      if (plan) {
        const r = await applyCheck(messageId, ids);
        if (r.error) return setNote({ text: r.error, error: true });
        onApplied(ids.filter((id) => !r.skipped?.includes(id)));
        setNote({ text: `Saved as version ${r.version} of the plan.` });
        if (r.plan && r.version) openPlan(r.plan, r.version);
      } else {
        const r = await sendMessage(askToChange(result, ids));
        setNote(r.error ? { text: r.error, error: true } : { text: `Sent to ${cooName}.` });
        if (!r.error) onApplied(ids);
      }
    });

  return (
    <section aria-label={label.title} className="mt-2 max-w-xl rounded-2xl border border-line bg-surface px-4 py-3 text-sm shadow-card">
      <header className="flex flex-wrap items-center gap-2">
        <FlaskConical className="size-4 text-accent" aria-hidden />
        <h3 className="font-medium text-ink">{label.title}</h3>
        {broke ? (
          <Pill tone="amber">
            {broke} thing{broke > 1 ? "s" : ""} to fix
          </Pill>
        ) : (
          <Pill tone="accent">Held up</Pill>
        )}
        {check.page && (
          <span className="inline-flex items-center gap-1 text-xs text-ink-3" title={check.page}>
            <Globe className="size-3.5" aria-hidden /> went through the live page
          </span>
        )}
      </header>
      <p className="mt-2 leading-relaxed text-ink" dir="auto">
        {result.summary}
      </p>

      {result.findings.length > 0 && (
        <ul className="mt-3 space-y-2">
          {result.findings.map((f) => (
            <li key={f.id} className="rounded-xl bg-amber-soft/50 px-3 py-2" dir="auto">
              <p className="font-medium text-ink">{f.moment}</p>
              <p className="text-ink-2">{f.problem}</p>
              {f.voices.length > 0 && <p className="mt-0.5 text-xs text-ink-3">{f.voices.join(", ")}</p>}
            </li>
          ))}
        </ul>
      )}

      {result.held.length > 0 && (
        <ul className="mt-3 space-y-1 text-ink-2">
          {result.held.map((h) => (
            <li key={h} className="flex gap-2" dir="auto">
              <CheckIcon className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden /> {h}
            </li>
          ))}
        </ul>
      )}

      {usable.length > 0 && (
        <fieldset className="mt-3 border-t border-line pt-3">
          <legend className="sr-only">Changes to make</legend>
          <p className="mb-2 text-xs font-medium text-ink-3">Suggested changes</p>
          <ul className="space-y-2">
            {usable.map((e) => (
              <li key={e.id}>
                <label className="flex cursor-pointer gap-2.5">
                  <input
                    type="checkbox"
                    checked={picked.has(e.id)}
                    onChange={(ev) => {
                      const next = new Set(picked);
                      if (ev.target.checked) next.add(e.id);
                      else next.delete(e.id);
                      setPicked(next);
                    }}
                    className="mt-1 size-4 shrink-0 accent-accent"
                  />
                  <span className="min-w-0" dir="auto">
                    <span className="block text-ink">{e.why}</span>
                    {e.find && <del className="block text-xs break-words text-ink-3">{e.find}</del>}
                    <ins className="block text-xs break-words text-accent no-underline">{e.replace}</ins>
                  </span>
                </label>
              </li>
            ))}
          </ul>
          <button
            type="button"
            onClick={use}
            disabled={pending || !usable.some((e) => picked.has(e.id))}
            className="mt-3 inline-flex items-center gap-2 rounded-full bg-accent px-4 py-1.5 text-sm font-medium text-accent-ink transition-colors hover:bg-accent-hover disabled:opacity-50"
          >
            {pending && <Loader2 className="size-4 animate-spin" aria-hidden />}
            {plan ? "Make these changes to the plan" : `Ask ${cooName} to make these changes`}
          </button>
        </fieldset>
      )}
      {note && (
        <p role={note.error ? "alert" : "status"} className={cx("mt-2 text-sm", note.error ? "text-rose" : "text-ink-2")}>
          {note.text}
        </p>
      )}

      {result.voices.length > 0 && (
        <details className="group mt-3 border-t border-line pt-2">
          <summary className="flex cursor-pointer list-none items-center gap-1 text-xs font-medium text-ink-3 hover:text-ink">
            <ChevronRight className="size-3.5 transition-transform group-open:rotate-90" aria-hidden /> How each one went
          </summary>
          <ul className="mt-2 space-y-2">
            {result.voices.map((v) => (
              <li key={v.who} dir="auto">
                <p className="font-medium text-ink">{v.who}</p>
                <p className="text-ink-2">{v.went}</p>
                {v.stuck && <p className="text-xs text-ink-3">Stuck on: {v.stuck}</p>}
              </li>
            ))}
          </ul>
        </details>
      )}

      {check.planChanged && (
        <button
          type="button"
          onClick={onRetest}
          disabled={retesting}
          className="mt-3 inline-flex items-center gap-1.5 text-sm font-medium text-accent hover:underline disabled:opacity-60"
        >
          <RotateCcw className="size-3.5" aria-hidden /> The plan has changed since. Test it again
        </button>
      )}
    </section>
  );
}

/** The picked edits as a message to the COO, for a reply that has no plan to change directly. */
function askToChange(result: CheckResult, ids: string[]): string {
  const lines = result.edits
    .filter((e) => ids.includes(e.id))
    .map((e) => (e.find ? `- ${e.why}: change “${e.find}” to “${e.replace}”` : `- ${e.why}: ${e.replace}`));
  return `From the test, please make these changes to what you proposed:\n${lines.join("\n")}`;
}
