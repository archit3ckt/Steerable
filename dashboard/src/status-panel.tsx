"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { ChevronRight, X } from "lucide-react";
import type { BackgroundStatus, Helper } from "./backend/types";
import { ago } from "./format";
import { cx } from "./ui";

const DOT: Record<Helper["state"], string> = {
  working: "bg-accent animate-pulse",
  idle: "bg-ink-3/60",
  attention: "bg-amber",
  needsYou: "bg-violet",
};

const LABEL: Record<Helper["state"], string> = {
  working: "Working now",
  idle: "",
  attention: "Needs a look",
  needsYou: "Waiting for you",
};

/**
 * The health line under the company name, as a button: it opens what the COO is doing in the
 * background (the backend's status(), from the host's statusUrl), refreshed every few seconds
 * while it's open.
 */
export function StatusButton({ statusUrl, cooName, children }: { statusUrl: string; cooName: string; children: ReactNode }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<BackgroundStatus | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!open) return;
    let alive = true;
    const load = () =>
      fetch(statusUrl, { cache: "no-store" })
        .then((r) => (r.ok ? r.json() : Promise.reject()))
        .then((s: BackgroundStatus) => alive && (setStatus(s), setFailed(false)))
        .catch(() => alive && setFailed(true));
    load();
    const timer = setInterval(load, 4000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [open, statusUrl]);

  return (
    <>
      <button
        type="button"
        onClick={() => {
          dialog.current?.showModal();
          setOpen(true);
        }}
        className="group flex max-w-full items-center gap-1.5 truncate text-left text-xs text-ink-2 hover:text-ink"
        aria-haspopup="dialog"
      >
        {children}
        <ChevronRight className="size-3 shrink-0 opacity-60 transition-transform group-hover:translate-x-0.5" />
      </button>
      <dialog
        ref={dialog}
        onClose={() => setOpen(false)}
        onClick={(e) => e.target === dialog.current && dialog.current?.close()}
        aria-labelledby="status-title"
        className="m-auto w-[min(30rem,calc(100vw-2rem))] rounded-2xl border border-line bg-surface p-0 text-ink shadow-card backdrop:bg-black/40"
      >
        <div className="p-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 id="status-title" className="font-display text-2xl tracking-tight">
                What {cooName} is doing
              </h2>
              <p className="mt-1 text-sm text-ink-2">Everything running in the background, live.</p>
            </div>
            <button type="button" onClick={() => dialog.current?.close()} className="-m-1 rounded-full p-1 text-ink-3 hover:text-ink" aria-label="Close">
              <X className="size-5" />
            </button>
          </div>

          {open && status && status.helpers.length > 0 ? (
            <ul className="mt-5 divide-y divide-line">
              {status.helpers.map((h) => (
                <HelperRow key={h.id} helper={h} now={Date.parse(status.now)} onOpen={() => dialog.current?.close()} />
              ))}
            </ul>
          ) : open && status ? (
            <p className="mt-5 text-sm text-ink-2">{cooName} runs on your own server. Its dashboard there shows what&apos;s running.</p>
          ) : failed ? (
            <p className="mt-5 text-sm text-ink-2">Can&apos;t reach {cooName} right now. This will update when it&apos;s back.</p>
          ) : (
            <ul className="mt-5 space-y-4" aria-hidden>
              {[0, 1, 2, 3].map((i) => (
                <li key={i} className="h-9 animate-pulse rounded-lg bg-surface-2" />
              ))}
            </ul>
          )}
        </div>
      </dialog>
    </>
  );
}

function HelperRow({ helper: h, now, onOpen }: { helper: Helper; now: number; onOpen: () => void }) {
  const label = LABEL[h.state];
  const row = (
    <div className="flex items-start gap-3 py-3">
      <span className={cx("mt-1.5 size-2 shrink-0 rounded-full", DOT[h.state])} />
      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-baseline gap-x-2 text-sm font-medium">
          {h.name}
          {label && <span className={cx("text-xs font-normal", h.state === "working" ? "text-accent" : h.state === "attention" ? "text-amber" : "text-violet")}>{label}</span>}
        </p>
        <p className="text-sm text-ink-2">{h.summary}</p>
      </div>
      {h.lastAt && <span className="shrink-0 pt-0.5 text-xs text-ink-3">{ago(h.lastAt, now)}</span>}
    </div>
  );
  return <li>{h.state === "needsYou" ? <Link href="/decisions" onClick={onOpen} className="block hover:bg-surface-2/60">{row}</Link> : row}</li>;
}
