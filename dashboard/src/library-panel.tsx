"use client";

import { Archive, Loader2, Paperclip, Send, Undo2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { CellValue, LibraryColumn, LibraryRowDetail } from "./backend/types";
import { ago } from "./format";
import { CellEditor, CellView, ICONS, rowTitle } from "./library-cells";
import { Poll } from "./poll";
import { cx } from "./ui";

/**
 * One row with every field (editable), its files, comments and what happened to it: Teable's
 * expanded record. A comment can ask the COO to act on the row; its reply lands under it.
 */
export function RowPanel({
  detail,
  columns,
  related,
  cooName,
  now,
  filesUrl,
  onClose,
  onSave,
  onArchive,
  onComment,
}: {
  detail: LibraryRowDetail;
  columns: LibraryColumn[];
  related: Record<string, string>;
  cooName: string;
  now: number;
  /** The host's chatFilesUrl: where files are uploaded and opened. */
  filesUrl?: string;
  onClose: () => void;
  onSave: (cells: Record<string, CellValue>) => Promise<string | null>;
  onArchive: (archived: boolean) => Promise<void>;
  onComment: (text: string, ask: boolean) => Promise<string | null>;
}) {
  const [cells, setCells] = useState(detail.cells);
  const [busy, setBusy] = useState(false);
  const [comment, setComment] = useState("");
  const [ask, setAsk] = useState(false);
  const [sending, setSending] = useState(false);
  const [uploading, setUploading] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [fileNames, setFileNames] = useState(detail.files);
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    panel.current?.focus();
    const esc = (e: KeyboardEvent) => e.key === "Escape" && !(e.target as HTMLElement).matches("input, textarea, select") && onClose();
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, [onClose]);
  const who = (w: string) => (w === "you" ? "You" : w === "coo" ? cooName : "Autopilot");
  const title = rowTitle(columns, cells);
  const waiting = detail.comments.some((c) => c.ask && c.status === "asked");

  async function saveField(col: LibraryColumn, value: CellValue) {
    const before = cells[col.name];
    setCells((c) => ({ ...c, [col.name]: value }));
    setProblem(null);
    const error = await onSave({ [col.name]: value });
    if (error) {
      setProblem(error);
      setCells((c) => ({ ...c, [col.name]: before }));
    }
  }

  async function attach(col: LibraryColumn, list: FileList | null) {
    if (!list?.length || !filesUrl) return;
    setUploading(col.name);
    setProblem(null);
    const ids = Array.isArray(cells[col.name]) ? [...(cells[col.name] as string[])] : [];
    const names = { ...fileNames };
    for (const file of Array.from(list).slice(0, 10)) {
      const res = await fetch(`${filesUrl}?name=${encodeURIComponent(file.name)}`, { method: "POST", body: file }).catch(() => null);
      const body = await res?.json().catch(() => null);
      if (!res?.ok || !body?.id) {
        setProblem(body?.error ?? `${file.name} didn't upload. Try again.`);
        continue;
      }
      ids.push(body.id);
      names[body.id] = { name: body.name, kind: body.kind };
    }
    setFileNames(names);
    setUploading(null);
    await saveField(col, ids.length ? ids : null);
  }

  async function send() {
    if (!comment.trim()) return;
    setSending(true);
    const error = await onComment(comment.trim(), ask);
    setSending(false);
    if (error) return setProblem(error);
    setComment("");
    setAsk(false);
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {waiting && <Poll seconds={4} />}
      <button type="button" aria-label="Close" onClick={onClose} className="absolute inset-0 bg-ink/20" />
      <div ref={panel} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title || "Row"} className="relative flex h-full w-full max-w-lg flex-col bg-bg shadow-2xl outline-none">
        <div className="flex items-start gap-3 border-b border-line px-5 py-4">
          <h2 className="min-w-0 flex-1 font-display text-2xl leading-tight break-words" dir="auto">
            {title || <span className="text-ink-3">Untitled</span>}
          </h2>
          <button type="button" onClick={onClose} className="rounded-lg p-1.5 text-ink-3 hover:bg-surface-2 hover:text-ink" aria-label="Close">
            <X className="size-5" />
          </button>
        </div>
        <div className="flex-1 space-y-4 overflow-y-auto px-5 py-5">
          {detail.archived && <p className="rounded-lg bg-surface-2 px-3 py-2 text-sm text-ink-2">This row is archived. Bring it back to change it.</p>}
          {problem && (
            <p role="alert" className="rounded-lg bg-rose-soft px-3 py-2 text-sm text-rose">
              {problem}
            </p>
          )}
          {columns.map((c) => {
            const Icon = ICONS[c.type];
            const value = cells[c.name];
            return (
              <div key={c.id}>
                <p className="mb-1 flex items-center gap-1.5 text-xs font-medium text-ink-3">
                  <Icon className="size-3.5" aria-hidden /> {c.name}
                </p>
                {detail.archived || c.type === "relation" ? (
                  <div className="min-h-8 py-1 text-sm" dir="auto">
                    <CellView col={c} value={value} related={related} files={fileNames} filesUrl={filesUrl} />
                  </div>
                ) : c.type === "checkbox" ? (
                  <button type="button" onClick={() => saveField(c, !value)} className="flex items-center gap-2 py-1 text-sm" aria-pressed={Boolean(value)}>
                    <CellView col={c} value={value} related={related} /> {value ? "Yes" : "No"}
                  </button>
                ) : c.type === "files" ? (
                  <div className="space-y-2">
                    {Array.isArray(value) && value.length > 0 && (
                      <ul className="space-y-1">
                        {value.map((id) => (
                          <li key={id} className="flex items-center gap-2 text-sm">
                            <CellView col={c} value={[id]} related={related} files={fileNames} filesUrl={filesUrl} />
                            <button
                              type="button"
                              onClick={() => saveField(c, value.filter((x) => x !== id).length ? value.filter((x) => x !== id) : null)}
                              className="text-xs text-ink-3 hover:text-rose"
                            >
                              Remove
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                    {filesUrl && (
                      <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-sm text-ink-2 hover:border-accent hover:text-ink">
                        {uploading === c.name ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Paperclip className="size-4" aria-hidden />}
                        Add files
                        <input type="file" multiple className="sr-only" onChange={(e) => attach(c, e.target.files)} />
                      </label>
                    )}
                  </div>
                ) : (
                  <CellEditor key={JSON.stringify(value)} col={c} value={value} autoFocus={false} onSave={(v) => saveField(c, v)} className="border-line bg-surface px-3 py-2 focus:border-accent" />
                )}
              </div>
            );
          })}

          <section className="border-t border-line pt-4">
            <h3 className="mb-3 text-xs font-medium tracking-wide text-ink-3 uppercase">Comments</h3>
            {detail.comments.length > 0 && (
              <ol className="mb-3 space-y-3">
                {detail.comments.map((c) => (
                  <li key={c.id} className={cx("rounded-xl px-3 py-2 text-sm", c.who === "coo" ? "bg-accent-soft/60" : "bg-surface")}>
                    <p className="mb-0.5 flex items-center gap-2 text-xs text-ink-3">
                      <span className="font-medium text-ink-2">{who(c.who)}</span>
                      {ago(c.at, now)}
                      {c.ask && c.status === "asked" && (
                        <span className="inline-flex items-center gap-1 text-accent">
                          <Loader2 className="size-3 animate-spin" aria-hidden /> {cooName} is on it
                        </span>
                      )}
                      {c.ask && c.status === "answered" && <span className="text-accent">Asked {cooName}</span>}
                      {c.ask && c.status === "failed" && <span className="text-rose">{cooName} couldn&apos;t get to it</span>}
                    </p>
                    <p className="whitespace-pre-wrap" dir="auto">
                      {c.text}
                    </p>
                  </li>
                ))}
              </ol>
            )}
            <textarea
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) send();
              }}
              rows={2}
              placeholder={ask ? `What should ${cooName} do with this row?` : "Add a comment"}
              className="w-full resize-y rounded-lg border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
              dir="auto"
            />
            <div className="mt-2 flex items-center justify-between gap-3">
              <label className="flex items-center gap-2 text-sm text-ink-2">
                <input type="checkbox" checked={ask} onChange={(e) => setAsk(e.target.checked)} className="accent-[var(--accent)]" />
                Ask {cooName} to do this
              </label>
              <button
                type="button"
                disabled={sending || !comment.trim()}
                onClick={send}
                className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-bg hover:bg-accent-hover disabled:opacity-50"
              >
                {sending ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Send className="size-4" aria-hidden />}
                {ask ? "Ask" : "Comment"}
              </button>
            </div>
          </section>

          <section className="border-t border-line pt-4">
            <h3 className="mb-3 text-xs font-medium tracking-wide text-ink-3 uppercase">History</h3>
            <ol className="space-y-2.5">
              {detail.history.map((h, i) => (
                <li key={i} className="text-sm">
                  <span className="font-medium">{who(h.who)}</span> <span className="text-ink-2">· {h.what.replace(/; /g, " · ")}</span>
                  <span className="ml-1.5 text-xs text-ink-3">{ago(h.at, now)}</span>
                </li>
              ))}
            </ol>
          </section>
        </div>
        <div className="flex items-center justify-between border-t border-line px-5 py-3">
          <span className="text-xs text-ink-3">Added {ago(detail.created, now)}</span>
          <button
            type="button"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              await onArchive(!detail.archived);
              setBusy(false);
            }}
            className="inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-sm text-ink-2 hover:border-accent hover:text-ink disabled:opacity-60"
          >
            {detail.archived ? <Undo2 className="size-4" aria-hidden /> : <Archive className="size-4" aria-hidden />}
            {detail.archived ? "Bring back" : "Archive"}
          </button>
        </div>
      </div>
    </div>
  );
}
