import { FileText } from "lucide-react";
import type { PlanChange } from "./backend/types";
import { Card, Empty, cx } from "./ui";

/* A plan's text as people read it, for the Library's plan page and the chat's plan panel. */

/** The plan's text without a first heading that only repeats its title (shown above it already). */
export function withoutTitle(body: string, title: string): string {
  const m = body.match(/^\s*#\s+(.+)\n+/);
  return m && m[1].trim().toLowerCase() === title.trim().toLowerCase() ? body.slice(m[0].length) : body;
}

/** A line of a plan as people read it: a heading without its #s, a list item with a bullet. */
function readable(text: string): { text: string; heading: boolean } {
  const heading = text.match(/^#{1,6}\s+(.*)$/);
  if (heading) return { text: heading[1], heading: true };
  return { text: text.replace(/^(\s*)[-*+]\s+/, "$1\u2022 ").replace(/\*\*(.+?)\*\*/g, "$1"), heading: false };
}

/** What a version changed: added lines in green, removed ones struck through in rose, the rest folded. */
export function PlanChanges({ changes, first }: { changes: PlanChange[]; first: boolean }) {
  if (!changes.length) {
    return (
      <Empty icon={<FileText className="size-5" aria-hidden />} title="No changes">
        This version says the same as the one before.
      </Empty>
    );
  }
  return (
    <Card className="overflow-hidden py-2 text-sm leading-relaxed">
      {first && <p className="px-5 pb-2 font-sans text-sm text-ink-3">The first version: all of it is new.</p>}
      {changes.map((c, k) =>
        c.op === "skip" ? (
          <p key={k} className="px-5 py-1 font-sans text-xs text-ink-3">
            {c.count} unchanged {c.count === 1 ? "line" : "lines"}
          </p>
        ) : (
          <p
            key={k}
            dir="auto"
            className={cx(
              "min-h-[1.6em] px-5 whitespace-pre-wrap",
              c.op === "add" && "bg-accent-soft text-ink",
              c.op === "del" && "bg-rose-soft text-ink-2 line-through decoration-rose/60",
              c.op === "same" && "text-ink-3",
            )}
          >
            <span aria-hidden className="mr-3 inline-block w-3 select-none">
              {c.op === "add" ? "+" : c.op === "del" ? "−" : ""}
            </span>
            <span className="sr-only">{c.op === "add" ? "Added: " : c.op === "del" ? "Removed: " : ""}</span>
            <span className={cx(readable(c.text).heading && "font-medium text-ink")}>{readable(c.text).text}</span>
          </p>
        ),
      )}
    </Card>
  );
}
