"use client";

import { useState, type ReactNode } from "react";
import { cx } from "./ui";

/** Goals as cards or on a timeline; both are rendered on the server, this only switches. */
export function GoalsViews({ cards, timeline }: { cards: ReactNode; timeline: ReactNode }) {
  const [view, setView] = useState<"cards" | "timeline">("cards");
  const tab = (id: typeof view, label: string) => (
    <button
      type="button"
      onClick={() => setView(id)}
      aria-pressed={view === id}
      className={cx("rounded-full px-4 py-1.5 text-sm font-medium transition-colors", view === id ? "bg-surface text-ink shadow-card" : "text-ink-3 hover:text-ink")}
    >
      {label}
    </button>
  );
  return (
    <div>
      <div className="mb-6 inline-flex gap-1 rounded-full bg-surface-2 p-1">
        {tab("cards", "Goals")}
        {tab("timeline", "Timeline")}
      </div>
      {view === "cards" ? cards : timeline}
    </div>
  );
}
