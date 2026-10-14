"use client";

import { BookOpen, Check, ChevronDown, Loader2, Pause, Play, Repeat, RotateCcw, Sparkles, Target, Trash2, Upload, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useRef, useState, useTransition } from "react";
import type { BookIdea } from "./backend/types";
import type { DashboardActions } from "./host";
import { Markdown } from "./markdown";
import { cx } from "./ui";

/** Books the owner teaches the COO, in the library: teaching one, answering its ideas, and its actions. */

const ACCEPT = ".epub,.pdf,.docx,.txt,.md";

export function TeachBook({
  cooName,
  filesUrl,
  teach,
  startOpen = false,
  variant = "button",
}: {
  cooName: string;
  filesUrl?: string;
  teach: DashboardActions["teachBook"];
  startOpen?: boolean;
  variant?: "button" | "card";
}) {
  const router = useRouter();
  const [open, setOpen] = useState(startOpen);
  const [file, setFile] = useState<File | null>(null);
  const [why, setWhy] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!filesUrl) return null;

  async function start() {
    if (!file) return setError("Choose the book's file first.");
    setBusy(true);
    setError(null);
    const res = await fetch(`${filesUrl}?name=${encodeURIComponent(file.name)}`, { method: "POST", body: file }).catch(() => null);
    const uploaded = await res?.json().catch(() => null);
    if (!res?.ok || !uploaded?.id) {
      setBusy(false);
      return setError(uploaded?.error ?? "That file didn't upload. Try again.");
    }
    const result = await teach(uploaded.id, why);
    if (result.error || !result.id) {
      setBusy(false);
      return setError(result.error ?? "That book couldn't be added.");
    }
    router.push(`/library/books/${result.id}`);
  }

  return (
    <>
      {variant === "card" ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="flex h-full min-h-32 w-full flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-line p-5 text-sm text-ink-2 transition-colors hover:border-accent hover:text-ink"
        >
          <BookOpen className="size-5 text-accent" aria-hidden />
          Teach {cooName} a book
        </button>
      ) : (
        <button type="button" onClick={() => setOpen(true)} className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-bg hover:bg-accent-hover">
          <BookOpen className="size-4" aria-hidden /> Teach {cooName} a book
        </button>
      )}
      {open && (
        <div className="fixed inset-0 z-50 grid place-items-center p-4">
          <button type="button" aria-label="Close" onClick={() => !busy && setOpen(false)} className="absolute inset-0 bg-ink/30" />
          <div role="dialog" aria-modal="true" aria-label={`Teach ${cooName} a book`} className="relative w-full max-w-lg rounded-2xl bg-bg p-6 shadow-2xl">
            <button type="button" onClick={() => !busy && setOpen(false)} className="absolute top-4 right-4 rounded-lg p-1 text-ink-3 hover:text-ink" aria-label="Close">
              <X className="size-5" />
            </button>
            <h2 className="font-display text-2xl">Teach {cooName} a book</h2>
            <p className="mt-2 text-sm text-ink-2">
              {cooName} reads it, takes notes, and suggests skills, routines and goals for running your business the book&apos;s way. Nothing changes until you add them.
            </p>
            <label className="mt-5 flex cursor-pointer items-center gap-3 rounded-xl border border-dashed border-line px-4 py-4 text-sm hover:border-accent">
              <Upload className="size-5 shrink-0 text-accent" aria-hidden />
              <span className="min-w-0 flex-1">
                {file ? <span className="font-medium break-words text-ink">{file.name}</span> : <span className="text-ink-2">Choose the book: EPUB, PDF, Word or text, up to 20 MB</span>}
              </span>
              <input type="file" accept={ACCEPT} className="sr-only" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            </label>
            <label className="mt-4 block text-sm">
              <span className="text-ink-2">What do you like about it? (optional)</span>
              <textarea
                value={why}
                onChange={(e) => setWhy(e.target.value)}
                rows={3}
                placeholder="It taught me to build systems so the shop runs without me."
                className="mt-1 w-full resize-y rounded-lg border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
                dir="auto"
              />
            </label>
            <p className="mt-3 text-xs text-ink-3">Use a copy you own. It stays in your company&apos;s files and is only used for your business.</p>
            {error && (
              <p role="alert" className="mt-3 text-sm text-rose">
                {error}
              </p>
            )}
            <div className="mt-5 flex justify-end">
              <button
                type="button"
                onClick={start}
                disabled={busy || !file}
                className="inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-bg hover:bg-accent-hover disabled:opacity-60"
              >
                {busy && <Loader2 className="size-4 animate-spin" aria-hidden />}
                {busy ? "Opening the book…" : "Start reading"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

const KIND = {
  skill: { Icon: Sparkles, word: "Skill", add: "Add this skill" },
  routine: { Icon: Repeat, word: "Routine", add: "Start this routine" },
  goal: { Icon: Target, word: "Goal", add: "Add this goal" },
} as const;

function details(idea: BookIdea) {
  const body = idea.body as Record<string, unknown>;
  if (idea.kind === "routine") {
    const when = body.at ? `${body.every ?? "daily"} at ${body.at}` : String(body.every ?? "on a schedule");
    return `${String(body.description ?? idea.summary)}. Runs ${when}${body.saves ? `; saves about ${body.saves}h a week` : ""}.`;
  }
  return `${String(body.goal ?? idea.name)}${body.metric ? `. Measured by ${body.metric}` : ""}${body.target ? `, target ${body.target}` : ""}.`;
}

/** One idea from a book, with Add and Skip. */
export function IdeaCard({ bookId, idea, answer }: { bookId: string; idea: BookIdea; answer: DashboardActions["answerBookIdea"] }) {
  const [pending, start] = useTransition();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const k = KIND[idea.kind];
  const go = (approve: boolean) =>
    start(async () => {
      setError(null);
      const result = await answer(bookId, idea.id, approve);
      if (result.error) setError(result.error);
    });
  return (
    <li className="rounded-2xl border border-line bg-surface p-5">
      <div className="flex items-start gap-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-accent-soft text-accent">
          <k.Icon className="size-4" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-xs text-ink-3">
            {k.word}
            {idea.source && ` · ${idea.source}`}
          </p>
          <h3 className="font-medium text-ink">{idea.name}</h3>
          <p className="mt-0.5 text-sm text-ink-2">{idea.summary}</p>
          <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="mt-2 inline-flex items-center gap-1 text-xs text-ink-3 hover:text-ink">
            {open ? "Hide details" : "Details"} <ChevronDown className={cx("size-3.5 transition-transform", open && "rotate-180")} aria-hidden />
          </button>
          {open && (
            <div className="mt-2 rounded-xl bg-bg px-4 py-3 text-sm">
              {idea.kind === "skill" && typeof idea.body === "string" ? <Markdown text={idea.body} /> : <p className="text-ink-2">{details(idea)}</p>}
            </div>
          )}
          {error && (
            <p role="alert" className="mt-2 text-sm text-rose">
              {error}
            </p>
          )}
        </div>
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <button type="button" disabled={pending} onClick={() => go(false)} className="rounded-lg px-3 py-1.5 text-sm text-ink-2 hover:bg-surface-2 hover:text-ink disabled:opacity-60">
          Skip
        </button>
        <button
          type="button"
          disabled={pending}
          onClick={() => go(true)}
          className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-bg hover:bg-accent-hover disabled:opacity-60"
        >
          {pending ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Check className="size-4" aria-hidden />}
          {k.add}
        </button>
      </div>
    </li>
  );
}

/** Pause or resume what was learned, try a failed study again, or forget the book. */
export function BookActions({
  bookId,
  title,
  status,
  actions,
}: {
  bookId: string;
  title: string;
  status: string;
  actions: Pick<DashboardActions, "setBookPaused" | "retryBook" | "removeBook">;
}) {
  const [pending, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const run = (work: () => Promise<{ error?: string }>) =>
    start(async () => {
      setError(null);
      const result = await work();
      if (result.error) setError(result.error);
    });
  const button = "inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-sm text-ink-2 hover:border-accent hover:text-ink disabled:opacity-60";
  return (
    <div className="flex flex-wrap items-center gap-2">
      {status === "failed" && (
        <button type="button" disabled={pending} onClick={() => run(() => actions.retryBook(bookId))} className={button}>
          <RotateCcw className="size-4" aria-hidden /> Try again
        </button>
      )}
      {(status === "ready" || status === "learned") && (
        <button type="button" disabled={pending} onClick={() => run(() => actions.setBookPaused(bookId, true))} className={button} title="Its skills are set aside until you resume it">
          <Pause className="size-4" aria-hidden /> Pause this book
        </button>
      )}
      {status === "paused" && (
        <button type="button" disabled={pending} onClick={() => run(() => actions.setBookPaused(bookId, false))} className={button}>
          <Play className="size-4" aria-hidden /> Resume
        </button>
      )}
      <button
        type="button"
        disabled={pending}
        onClick={() => window.confirm(`Forget “${title}”? Its skills, notes and text go. Routines and goals you added from it stay.`) && run(() => actions.removeBook(bookId))}
        className={cx(button, "hover:border-rose hover:text-rose")}
      >
        <Trash2 className="size-4" aria-hidden /> Forget this book
      </button>
      {pending && <Loader2 className="size-4 animate-spin text-ink-3" aria-label="Working" />}
      {error && (
        <p role="alert" className="w-full text-sm text-rose">
          {error}
        </p>
      )}
    </div>
  );
}

/** A search passage, its matching words (marked [like this] by the engine) highlighted. */
export function Passage({ text }: { text: string }) {
  return (
    <>
      {text.split(/\[([^\]]*)\]/).map((part, i) =>
        i % 2 ? (
          <mark key={i} className="rounded bg-amber-soft px-0.5 text-ink">
            {part}
          </mark>
        ) : (
          part
        ),
      )}
    </>
  );
}

/** Search inside a book: a plain GET form, so the results come with the page. */
export function BookSearch({ initial, cooName }: { initial: string; cooName: string }) {
  const ref = useRef<HTMLInputElement>(null);
  return (
    <form method="get" className="flex gap-2" onSubmit={() => ref.current?.blur()}>
      <input
        ref={ref}
        name="q"
        type="search"
        defaultValue={initial}
        placeholder={`What does it say about… (pricing, hiring)`}
        aria-label={`Search the book, as ${cooName} does`}
        className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
        dir="auto"
      />
      <button type="submit" className="rounded-lg border border-line px-3 py-2 text-sm text-ink-2 hover:border-accent hover:text-ink">
        Search
      </button>
    </form>
  );
}
