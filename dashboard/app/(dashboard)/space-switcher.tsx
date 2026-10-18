"use client";

import Link from "next/link";
import { useTransition, type ReactNode } from "react";
import { Check, ChevronsUpDown, Loader2, Plus } from "lucide-react";
import { switchSpace } from "../../local/space-actions";
import { cx } from "../../src/ui";

/** The company card, with a menu of the spaces on this server and a way to add one. */
export function SpaceSwitcher({ current, spaces, children }: { current: string; spaces: { id: string; name: string }[]; children: ReactNode }) {
  const [pending, start] = useTransition();
  return (
    // Only the chevron opens it: the card itself has a button (the status panel).
    <div className="relative flex items-center gap-2">
      <div className="min-w-0 flex-1">{children}</div>
      <details className="group">
        <summary className="grid cursor-pointer list-none place-items-center rounded-lg p-1.5 transition-colors hover:bg-surface/60 [&::-webkit-details-marker]:hidden">
          {pending ? <Loader2 className="size-4 shrink-0 animate-spin text-ink-3" /> : <ChevronsUpDown className="size-4 shrink-0 text-ink-3" />}
          <span className="sr-only">Switch space</span>
        </summary>
        <ul className="absolute top-full left-0 z-40 mt-2 w-64 rounded-xl border border-line bg-surface p-1 shadow-lift">
          {spaces.map((s) => (
            <li key={s.id}>
              <button
                type="button"
                disabled={pending}
                onClick={() => start(() => switchSpace(s.id))}
                className={cx("flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition-colors hover:bg-surface-2", s.id === current && "font-medium")}
              >
                <span className="min-w-0 flex-1 truncate">{s.name}</span>
                {s.id === current && <Check className="size-4 text-accent" />}
              </button>
            </li>
          ))}
          <li className="mt-1 border-t border-line pt-1">
            <Link href="/spaces/new" className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink">
              <Plus className="size-4" />
              New space
            </Link>
          </li>
        </ul>
      </details>
    </div>
  );
}
