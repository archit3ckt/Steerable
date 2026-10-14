"use client";

import { Calendar, CheckSquare, CircleDot, Hash, Link2, Paperclip, Tags, Text, Type, User, Waypoints } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { CellValue, LibraryColumn, LibraryFileInfo } from "./backend/types";
import { Pill, cx, type Tone } from "./ui";

/** How the library's cells look and are edited, shared by its grid, board, calendar and row panel. */

export const ICONS: Record<LibraryColumn["type"], typeof Type> = {
  text: Type,
  longtext: Text,
  number: Hash,
  date: Calendar,
  status: CircleDot,
  person: User,
  link: Link2,
  checkbox: CheckSquare,
  relation: Waypoints,
  tags: Tags,
  files: Paperclip,
};

/** Each column's narrowest width in the grid, in rem. Text-like columns also share whatever room is left. */
export const MIN_REM: Record<LibraryColumn["type"], number> = {
  text: 14,
  longtext: 18,
  number: 8.5,
  date: 9,
  status: 9.5,
  person: 10,
  link: 14,
  checkbox: 6.5,
  relation: 11,
  tags: 11,
  files: 11,
};
export const STRETCHES = new Set<LibraryColumn["type"]>(["text", "longtext", "link"]);

export const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const GOOD = ["won", "done", "applied", "active", "paid", "offer", "hired", "yes", "approved", "interview"];
const BAD = ["rejected", "lost", "cancelled", "canceled", "failed", "no", "declined"];
const OTHER: Tone[] = ["amber", "violet", "sky", "neutral"];

export function statusTone(label: string, labels: string[]): Tone {
  const l = label.toLowerCase();
  if (BAD.includes(l)) return "rose";
  if (GOOD.includes(l)) return "accent";
  if (l === "new") return "sky";
  return OTHER[Math.max(0, labels.indexOf(label)) % OTHER.length];
}

/** Fixed formats (not the browser's locale), so the server and the browser draw the same thing. */
export function number(n: number) {
  return n.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

export function display(col: LibraryColumn, value: CellValue | undefined): string {
  if (value === null || value === undefined || value === "") return "";
  if (Array.isArray(value)) return value.join(", ");
  if (col.type === "number" && typeof value === "number") return col.options.unit === "$" ? `$${number(value)}` : `${number(value)}${col.options.unit ? ` ${col.options.unit}` : ""}`;
  if (col.type === "date" && typeof value === "string" && /^\d{4}-\d{2}-\d{2}/.test(value)) {
    const [y, m, d] = value.slice(0, 10).split("-").map(Number);
    return `${d} ${MONTHS[m - 1]} ${y}`;
  }
  if (col.type === "link" && typeof value === "string") return value.replace(/^https?:\/\/(www\.)?/, "");
  if (col.type === "checkbox") return value ? "Yes" : "No";
  return String(value);
}

/** What the row is called: its first text cell. */
export function rowTitle(columns: LibraryColumn[], cells: Record<string, CellValue>): string {
  const primary = columns[0];
  return primary ? display(primary, cells[primary.name]) : "";
}

export function CellView({
  col,
  value,
  related,
  files = {},
  filesUrl,
}: {
  col: LibraryColumn;
  value: CellValue | undefined;
  related: Record<string, string>;
  files?: Record<string, LibraryFileInfo>;
  filesUrl?: string;
}) {
  if (col.type === "checkbox") {
    return (
      <span className={cx("grid size-4 place-items-center rounded border text-xs", value ? "border-accent bg-accent text-bg" : "border-line")} aria-label={value ? "Yes" : "No"}>
        {value ? "✓" : ""}
      </span>
    );
  }
  if (value === null || value === undefined || value === "" || (Array.isArray(value) && !value.length)) return <span className="text-ink-3/60">—</span>;
  if (col.type === "status") return <Pill tone={statusTone(String(value), col.options.labels ?? [])}>{String(value)}</Pill>;
  if (col.type === "relation") return <Pill>{related[String(value)] ?? "(a row)"}</Pill>;
  if (col.type === "tags" && Array.isArray(value)) {
    return (
      <span className="inline-flex flex-wrap gap-1">
        {value.map((t) => (
          <Pill key={t} tone="violet">
            {t}
          </Pill>
        ))}
      </span>
    );
  }
  if (col.type === "files" && Array.isArray(value)) {
    return (
      <span className="inline-flex flex-wrap gap-1">
        {value.map((id) =>
          filesUrl ? (
            <a
              key={id}
              href={`${filesUrl}/${encodeURIComponent(id)}`}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="inline-flex max-w-[12rem] items-center gap-1 rounded-md bg-surface-2 px-1.5 py-0.5 text-xs text-ink-2 hover:text-ink"
            >
              <Paperclip className="size-3 shrink-0" aria-hidden />
              <span className="truncate">{files[id]?.name ?? "file"}</span>
            </a>
          ) : (
            <Pill key={id}>{files[id]?.name ?? "file"}</Pill>
          ),
        )}
      </span>
    );
  }
  if (col.type === "link") {
    return (
      <a href={String(value)} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()} className="text-ink-2 underline decoration-line underline-offset-2 hover:text-ink">
        {display(col, value)}
      </a>
    );
  }
  return <>{display(col, value)}</>;
}

/** An input for one cell. Saves on Enter or when it loses focus; Escape cancels. Tags are written "a, b". */
export function CellEditor({
  col,
  value,
  onSave,
  onCancel,
  autoFocus = true,
  className,
}: {
  col: LibraryColumn;
  value: CellValue | undefined;
  onSave: (value: CellValue) => void;
  onCancel?: () => void;
  autoFocus?: boolean;
  className?: string;
}) {
  const initial = value === null || value === undefined ? "" : Array.isArray(value) ? value.join(", ") : String(value);
  const [text, setText] = useState(col.type === "date" ? initial.slice(0, 10) : initial);
  const done = useRef(false);
  const commit = () => {
    if (done.current) return;
    done.current = true;
    if (text.trim() === initial.trim()) return onCancel?.();
    if (col.type === "tags") {
      const list = text.split(",").map((t) => t.trim()).filter(Boolean);
      return onSave(list.length ? list : null);
    }
    onSave(text.trim() === "" ? null : text.trim());
  };
  const keys = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      done.current = true;
      onCancel?.();
    } else if (e.key === "Enter" && (col.type !== "longtext" || e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      commit();
    }
  };
  const base = cx("w-full rounded-md border border-accent bg-surface px-2 py-1 text-sm text-ink outline-none", className);
  if (col.type === "status") {
    return (
      <select
        autoFocus={autoFocus}
        value={text}
        onChange={(e) => {
          done.current = true;
          onSave(e.target.value || null);
        }}
        onBlur={() => !done.current && onCancel?.()}
        onKeyDown={(e) => e.key === "Escape" && onCancel?.()}
        className={base}
      >
        <option value="">—</option>
        {(col.options.labels ?? []).map((l) => (
          <option key={l} value={l}>
            {l}
          </option>
        ))}
      </select>
    );
  }
  if (col.type === "longtext") {
    return <textarea autoFocus={autoFocus} value={text} rows={4} onChange={(e) => setText(e.target.value)} onBlur={commit} onKeyDown={keys} className={cx(base, "resize-y")} dir="auto" />;
  }
  return (
    <input
      autoFocus={autoFocus}
      type={col.type === "date" ? "date" : "text"}
      inputMode={col.type === "number" ? "decimal" : col.type === "link" ? "url" : undefined}
      placeholder={col.type === "link" ? "https://" : col.type === "tags" ? (col.options.labels?.join(", ") ?? "one, another") : undefined}
      value={text}
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onKeyDown={keys}
      className={base}
      dir="auto"
    />
  );
}

/**
 * A small menu that closes on a click outside it, Escape, scrolling or resizing. It floats above the
 * page (fixed, placed under its button), so a scrolling parent like the view tabs can't clip it.
 */
export function Menu({
  label,
  icon,
  active,
  align = "left",
  className,
  children,
}: {
  label: ReactNode;
  icon?: ReactNode;
  active?: boolean;
  align?: "left" | "right";
  className?: string;
  children: (close: () => void) => ReactNode;
}) {
  const [at, setAt] = useState<{ top: number; left: number } | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const open = at !== null;
  useEffect(() => {
    if (!open) return;
    const close = () => setAt(null);
    const away = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && close();
    const esc = (e: KeyboardEvent) => e.key === "Escape" && close();
    const scrolled = (e: Event) => !ref.current?.contains(e.target as Node) && close(); // not its own list
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    window.addEventListener("resize", close);
    window.addEventListener("scroll", scrolled, true);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
      window.removeEventListener("resize", close);
      window.removeEventListener("scroll", scrolled, true);
    };
  }, [open]);

  function toggle() {
    if (open || !button.current) return setAt(null);
    const r = button.current.getBoundingClientRect();
    const width = 256; // w-64
    const left = align === "right" ? r.right - width : r.left;
    setAt({ top: r.bottom + 4, left: Math.max(8, Math.min(left, window.innerWidth - width - 8)) });
  }

  return (
    <div ref={ref} className="relative">
      <button
        ref={button}
        type="button"
        aria-expanded={open}
        onClick={toggle}
        className={cx("inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm hover:bg-surface-2", active ? "text-accent" : "text-ink-2", className)}
      >
        {icon}
        {label}
      </button>
      {at && (
        <div
          role="menu"
          style={{ top: at.top, left: at.left, maxHeight: `calc(100vh - ${at.top + 16}px)` }}
          className="fixed z-[60] w-64 overflow-y-auto rounded-xl border border-line bg-surface p-2 shadow-lg"
        >
          {children(() => setAt(null))}
        </div>
      )}
    </div>
  );
}

export const menuItem = "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-surface-2";
