"use client";

import { useEffect } from "react";
import { CloudOff, RotateCw } from "lucide-react";

/** Shown when a page can't load the company's data, most often because its COO can't be reached. */
export function DashboardError({ error, retry }: { error: Error & { digest?: string }; retry: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="mx-auto flex max-w-md flex-col items-center py-20 text-center">
      <div className="grid size-14 place-items-center rounded-full bg-amber-soft text-amber">
        <CloudOff className="size-6" />
      </div>
      <h1 className="mt-5 font-display text-4xl tracking-tight">Can&apos;t load this right now</h1>
      <p className="mt-2 text-ink-2">
        Your business manager didn&apos;t answer in time. Your routines keep running on their own, so nothing is lost. Try again in a
        minute.
      </p>
      <button
        type="button"
        onClick={() => retry()}
        className="mt-8 inline-flex items-center gap-2 rounded-full bg-accent px-5 py-2.5 font-medium text-accent-ink shadow-card transition-colors hover:bg-accent-hover"
      >
        <RotateCw className="size-4" /> Try again
      </button>
    </div>
  );
}
