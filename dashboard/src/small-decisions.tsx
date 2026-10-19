"use client";

import { useState, useTransition } from "react";
import { Loader2, Undo2 } from "lucide-react";
import type { SettledDecision } from "./backend/types";
import type { ActionResult } from "./host";
import { Card, cx } from "./ui";

/** "Decide small things for me": the switch at the top of Decisions. */
export function DecideSmallSwitch({ on, cooName, setOn }: { on: boolean; cooName: string; setOn: (on: boolean) => Promise<ActionResult> }) {
  const [value, setValue] = useState(on);
  const [error, setError] = useState("");
  const [pending, start] = useTransition();
  return (
    <Card className="mb-8 flex items-start gap-4 p-5">
      <div className="min-w-0 flex-1">
        <p className="font-medium">Decide small things for me</p>
        <p className="mt-0.5 text-sm text-ink-2">
          Small questions that are easy to undo, like a format, an order or a time, are settled with {cooName}&apos;s pick, and you
          see them below. Anything about money, people outside the business, deleting, logins, legal matters or hiring always
          comes to you.
        </p>
        {error && <p className="mt-2 text-sm text-rose">{error}</p>}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={value}
        aria-label="Decide small things for me"
        disabled={pending}
        onClick={() =>
          start(async () => {
            const next = !value;
            setValue(next);
            const result = await setOn(next);
            if (result.error) {
              setValue(!next);
              setError(result.error);
            }
          })
        }
        className={cx("relative mt-1 h-6 w-11 shrink-0 rounded-full transition-colors", value ? "bg-accent" : "bg-ink-3/30")}
      >
        <span className={cx("absolute top-0.5 left-0.5 size-5 rounded-full bg-white shadow transition-transform", value && "translate-x-5")} />
      </button>
    </Card>
  );
}

/** What was settled for the owner this week, each with Undo (it comes back to them). */
export function SettledList({ items, ages, undo }: { items: SettledDecision[]; ages: Record<string, string>; undo: (id: string) => Promise<ActionResult> }) {
  return (
    <section className="mt-12">
      <h2 className="mb-3 text-sm font-medium tracking-wide text-ink-3 uppercase">Settled for you this week</h2>
      <Card className="divide-y divide-line">
        {items.map((s) => (
          <SettledRow key={s.id} item={s} age={ages[s.id]} undo={undo} />
        ))}
      </Card>
    </section>
  );
}

function SettledRow({ item, age, undo }: { item: SettledDecision; age?: string; undo: (id: string) => Promise<ActionResult> }) {
  const [pending, start] = useTransition();
  const [error, setError] = useState("");
  return (
    <div className="flex items-start gap-3 px-5 py-4">
      <div className="min-w-0 flex-1">
        <p className="font-medium">{item.question}</p>
        <p className="text-sm text-ink-2">
          Went with: {item.chosen}
          {item.why && <span className="text-ink-3"> · {item.why}</span>}
        </p>
        {age && <p className="mt-0.5 text-xs text-ink-3">{age}</p>}
        {error && <p className="mt-1 text-sm text-rose">{error}</p>}
      </div>
      <button
        type="button"
        disabled={pending}
        onClick={() => start(async () => setError((await undo(item.id)).error ?? ""))}
        className="inline-flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-sm text-ink-2 hover:bg-surface-2 hover:text-ink"
      >
        {pending ? <Loader2 className="size-4 animate-spin" /> : <Undo2 className="size-4" />}
        Undo
      </button>
    </div>
  );
}
