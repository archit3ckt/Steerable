"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";
import { cx } from "./ui";

/** Puts text on the clipboard (with a fallback where the Clipboard API isn't there, like plain http). */
async function copy(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  }
}

/** A Copy button that says "Copied" for a moment. `label` names what it copies, for screen readers. */
export function CopyButton({ text, label = "Copy", className, showLabel = false }: { text: string; label?: string; className?: string; showLabel?: boolean }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        if (await copy(text)) {
          setDone(true);
          setTimeout(() => setDone(false), 1500);
        }
      }}
      aria-label={done ? "Copied" : label}
      title={done ? "Copied" : label}
      className={cx("inline-flex items-center gap-1 rounded-lg px-1.5 py-1 text-xs transition-colors", done ? "text-accent" : "text-ink-3 hover:bg-surface-2 hover:text-ink", className)}
    >
      {done ? <Check className="size-3.5" aria-hidden /> : <Copy className="size-3.5" aria-hidden />}
      {showLabel && <span>{done ? "Copied" : "Copy"}</span>}
    </button>
  );
}
