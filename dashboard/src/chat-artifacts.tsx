"use client";

import { ChevronRight, FileText, Loader2, X } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { ChatArtifacts as Artifacts, PlanVersionDetail } from "./backend/types";
import { Markdown } from "./markdown";
import { PlanChanges, withoutTitle } from "./plan-text";
import { RunChanges } from "./run-changes";
import { cx } from "./ui";

type Opened = { id: string; version: number };

/** What's open beside the chat, from the address (?open=plan:<id>:<version>), so Back closes it. */
function parseOpen(value: string | null): Opened | null {
  const m = value?.match(/^plan:(pl[0-9a-f]{4,20}):(\d{1,6})$/);
  return m ? { id: m[1], version: Number(m[2]) } : null;
}

function setOpen(opened: Opened | null) {
  const params = new URLSearchParams(window.location.search);
  if (opened) params.set("open", `plan:${opened.id}:${opened.version}`);
  else params.delete("open");
  const qs = params.toString();
  window.history.pushState(null, "", qs ? `?${qs}` : window.location.pathname);
}

/**
 * The chat page, split when a reply's plan is open: the conversation on the left and the plan beside it
 * at full height, like artifacts (the shell goes wide meanwhile: nav.tsx WideMarker). On a phone the plan
 * covers the screen. Without plansUrl, cards link to the Library instead.
 */
export function ChatSplit({ plansUrl, children }: { plansUrl?: string; children: ReactNode }) {
  const opened = parseOpen(useSearchParams().get("open"));
  if (!opened || !plansUrl) return <div className="mx-auto max-w-3xl">{children}</div>;
  return (
    <div className="lg:-mt-14 lg:-mr-12 lg:-mb-16 lg:flex lg:items-start">
      <div className="mx-auto w-full max-w-3xl min-w-0 lg:mx-0 lg:w-[min(44rem,45%)] lg:max-w-none lg:shrink-0 lg:pt-14 lg:pr-10 lg:pb-16">
        {children}
      </div>
      <PlanPane key={`${opened.id}:${opened.version}`} url={plansUrl} opened={opened} onClose={() => setOpen(null)} />
    </div>
  );
}
type Loaded = { id: string; title: string; current: number; version: PlanVersionDetail };

/**
 * What a reply made or changed in the library, under the reply, like artifacts: each plan it saved
 * (opens beside the chat at the version it saved) and the rows it changed per table. They're the
 * Library's own plans and tables, not copies.
 */
export function ChatArtifacts({ artifacts, plansUrl, changesUrl }: { artifacts: Artifacts; plansUrl?: string; changesUrl?: string }) {
  const open = parseOpen(useSearchParams().get("open"));
  const plans = artifacts.plans ?? [];
  const changes = artifacts.changes ?? [];
  if (!plans.length && !changes.length) return null;
  return (
    <div className="mt-2 space-y-2">
      {plans.map((p) => {
        const inner = (
          <>
            <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-accent-soft text-accent">
              <FileText className="size-4" aria-hidden />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate font-medium text-ink" dir="auto">
                {p.title}
              </span>
              <span className="block truncate text-xs text-ink-3">
                {p.created ? "New plan" : `Version ${p.version}`}
                {p.note && !p.created ? ` · ${p.note}` : ""}
              </span>
            </span>
            <ChevronRight className="size-4 shrink-0 text-ink-3" aria-hidden />
          </>
        );
        const shown = open?.id === p.id && open.version === p.version;
        const card = cx(
          "flex w-full max-w-md items-center gap-3 rounded-2xl border bg-surface px-3 py-2.5 text-left text-sm transition-colors hover:border-accent",
          shown ? "border-accent" : "border-line",
        );
        return plansUrl ? (
          <button key={p.id} type="button" aria-pressed={shown} onClick={() => setOpen(shown ? null : { id: p.id, version: p.version })} className={card}>
            {inner}
          </button>
        ) : (
          <Link key={p.id} href={`/library/plans/${p.id}?v=${p.version}`} className={card}>
            {inner}
          </Link>
        );
      })}
      {changes.length > 0 && <RunChanges run={artifacts.run} changes={changes} url={changesUrl} />}
    </div>
  );
}

/** A plan beside the chat (the whole screen on a phone): the version a reply saved, and what it changed. */
function PlanPane({ url, opened, onClose }: { url: string; opened: Opened; onClose: () => void }) {
  const [data, setData] = useState<Loaded | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"plan" | "changes">("plan");
  const close = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    let live = true;
    fetch(`${url}?${new URLSearchParams({ id: opened.id, v: String(opened.version) })}`, { cache: "no-store" })
      .then(async (res) => {
        const body = await res.json().catch(() => ({}));
        if (!live) return;
        if (res.ok) setData(body as Loaded);
        else setError((body as { error?: string }).error ?? "Couldn't open the plan.");
      })
      .catch(() => live && setError("Couldn't open the plan."));
    return () => {
      live = false;
    };
  }, [url, opened]);

  useEffect(() => {
    close.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const v = data?.version;
  const latest = data && v && v.n === data.current;
  return (
    <aside
      aria-label={data?.title ?? "Plan"}
      className="fixed inset-0 z-50 flex flex-col bg-bg lg:sticky lg:top-0 lg:z-0 lg:h-dvh lg:min-w-0 lg:flex-1 lg:border-l lg:border-line"
    >
        <header className="flex items-start gap-3 border-b border-line px-5 py-4 sm:px-6">
          <div className="min-w-0 flex-1">
            <p className="inline-flex items-center gap-1.5 text-xs text-accent">
              <FileText className="size-3.5" aria-hidden /> Plan
            </p>
            <h2 className="mt-1 truncate font-display text-2xl" dir="auto">
              {data?.title ?? " "}
            </h2>
            {v && (
              <p className="mt-0.5 text-xs text-ink-3">
                Version {v.n}
                {latest ? " · the current one" : ` · it's at version ${data.current} now`}
                {v.note ? ` · ${v.note}` : ""}
              </p>
            )}
          </div>
          <button ref={close} type="button" onClick={onClose} aria-label="Close" className="rounded-full p-2 text-ink-3 hover:bg-surface-2 hover:text-ink">
            <X className="size-5" aria-hidden />
          </button>
        </header>
        {v && v.n > 1 && (
          <div className="flex gap-4 border-b border-line px-5 py-2.5 text-sm sm:px-6" role="tablist">
            {(["plan", "changes"] as const).map((t) => (
              <button
                key={t}
                type="button"
                role="tab"
                aria-selected={tab === t}
                onClick={() => setTab(t)}
                className={cx(tab === t ? "font-medium text-ink" : "text-ink-3 hover:text-ink")}
              >
                {t === "plan" ? "The plan" : "What changed"}
              </button>
            ))}
          </div>
        )}
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 sm:px-6">
          {error ? (
            <p role="alert" className="text-sm text-rose">
              {error}
            </p>
          ) : !data || !v ? (
            <p className="flex items-center gap-2 text-sm text-ink-3">
              <Loader2 className="size-4 animate-spin" aria-hidden /> Opening the plan
            </p>
          ) : tab === "changes" && v.n > 1 ? (
            <PlanChanges changes={v.changes} first={false} />
          ) : (
            <div dir="auto">
              <Markdown text={withoutTitle(v.body, data.title)} />
            </div>
          )}
        </div>
        <footer className="border-t border-line px-5 py-3 sm:px-6">
          <Link
            href={latest ? `/library/plans/${opened.id}` : `/library/plans/${opened.id}?v=${opened.version}`}
            className="inline-flex items-center gap-1 text-sm font-medium text-accent hover:underline"
          >
            Open in Library <ChevronRight className="size-4" aria-hidden />
          </Link>
        </footer>
    </aside>
  );
}
