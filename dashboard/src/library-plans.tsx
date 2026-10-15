"use client";

import { Loader2, Pencil, RotateCcw, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, useTransition, type ReactNode } from "react";
import type { ActionResult } from "./host";

/**
 * A plan's text, and the owner's way to change it: Edit turns it into a text box (Markdown), saved as a
 * new version with an optional note. The rendered text comes from the server (children).
 */
export function PlanEditor({
  planId,
  body,
  save,
  children,
}: {
  planId: string;
  body: string;
  save: (planId: string, body: string, note: string) => Promise<ActionResult>;
  children: ReactNode;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(body);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();

  if (!editing) {
    return (
      <div>
        <div className="mb-4 flex justify-end">
          <button
            type="button"
            onClick={() => {
              setText(body);
              setEditing(true);
            }}
            className="inline-flex items-center gap-1.5 rounded-full border border-line px-4 py-2 text-sm text-ink-2 transition-colors hover:text-ink"
          >
            <Pencil className="size-3.5" aria-hidden /> Edit
          </button>
        </div>
        {children}
      </div>
    );
  }

  const submit = () =>
    start(async () => {
      setError(null);
      const result = await save(planId, text, note);
      if (result.error) setError(result.error);
      else {
        setEditing(false);
        setNote("");
      }
    });

  return (
    <div className="space-y-3">
      <label className="block">
        <span className="sr-only">The plan</span>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={Math.min(40, Math.max(12, text.split("\n").length + 2))}
          dir="auto"
          className="w-full rounded-2xl border border-line bg-surface p-4 font-mono text-sm leading-relaxed outline-none focus:border-accent"
        />
      </label>
      <label className="block">
        <span className="mb-1 block text-sm text-ink-2">What did you change? (optional)</span>
        <input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          maxLength={300}
          placeholder="Like: moved the launch to March"
          className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
        />
      </label>
      {error && (
        <p role="alert" className="text-sm text-rose">
          {error}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={submit}
          disabled={pending || !text.trim()}
          className="inline-flex items-center gap-1.5 rounded-full bg-accent px-5 py-2 text-sm font-medium text-accent-ink transition-colors hover:bg-accent-hover disabled:opacity-60"
        >
          {pending && <Loader2 className="size-3.5 animate-spin" aria-hidden />} Save as a new version
        </button>
        <button type="button" onClick={() => setEditing(false)} disabled={pending} className="rounded-full px-4 py-2 text-sm text-ink-2 hover:text-ink">
          Cancel
        </button>
      </div>
      <p className="text-xs text-ink-3">Written in Markdown: # for a heading, - for a list. Every version is kept, so you can always go back.</p>
    </div>
  );
}

/** Make an earlier version the current one again (saved as a new version, so nothing is lost). */
export function RestorePlan({
  planId,
  version,
  restore,
}: {
  planId: string;
  version: number;
  restore: (planId: string, version: number) => Promise<ActionResult>;
}) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  return (
    <div>
      <button
        type="button"
        disabled={pending}
        onClick={() =>
          start(async () => {
            setError(null);
            const result = await restore(planId, version);
            if (result.error) setError(result.error);
            else router.push(`/library/plans/${planId}`);
          })
        }
        className="inline-flex items-center gap-1.5 rounded-full bg-accent px-4 py-2 text-sm font-medium text-accent-ink transition-colors hover:bg-accent-hover disabled:opacity-60"
      >
        {pending ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <RotateCcw className="size-3.5" aria-hidden />} Restore this version
      </button>
      {error && (
        <p role="alert" className="mt-2 text-sm text-rose">
          {error}
        </p>
      )}
    </div>
  );
}

/** Remove a plan from the library (its versions stay in the database). */
export function RemovePlan({ planId, title, remove }: { planId: string; title: string; remove: (planId: string) => Promise<ActionResult> }) {
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  if (!asking) {
    return (
      <button type="button" onClick={() => setAsking(true)} className="inline-flex items-center gap-1.5 text-sm text-ink-3 hover:text-rose">
        <Trash2 className="size-3.5" aria-hidden /> Remove this plan
      </button>
    );
  }
  return (
    <div className="space-y-2 text-sm">
      <p className="text-ink-2">Remove &ldquo;{title}&rdquo; from your library?</p>
      <div className="flex gap-2">
        <button
          type="button"
          disabled={pending}
          onClick={() =>
            start(async () => {
              const result = await remove(planId);
              if (result.error) setError(result.error);
            })
          }
          className="rounded-full bg-rose px-4 py-1.5 font-medium text-bg disabled:opacity-60"
        >
          Remove
        </button>
        <button type="button" onClick={() => setAsking(false)} className="rounded-full px-3 py-1.5 text-ink-2 hover:text-ink">
          Keep it
        </button>
      </div>
      {error && (
        <p role="alert" className="text-rose">
          {error}
        </p>
      )}
    </div>
  );
}
