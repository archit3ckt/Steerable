"use client";

import { BookOpen, FileText, LayoutDashboard, Loader2, Plus, Search, Table2, Upload } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, useTransition } from "react";
import type { Book, DashboardSummary, LibraryTableSummary, Plan } from "./backend/types";
import { cx } from "./ui";

/** The library's own sidebar, like monday's list of boards: every table, findable by name. */
export function LibrarySidebar({
  tables,
  dashboards = [],
  books = [],
  plans = [],
  active,
  canTeach = false,
}: {
  tables: LibraryTableSummary[];
  dashboards?: DashboardSummary[];
  books?: Book[];
  plans?: Plan[];
  active?: string;
  canTeach?: boolean;
}) {
  const [find, setFind] = useState("");
  const words = find.toLowerCase().split(/\s+/).filter(Boolean);
  const shown = tables.filter((t) => words.every((w) => `${t.name} ${t.description}`.toLowerCase().includes(w)));
  return (
    <nav aria-label="Tables" className="flex min-h-0 flex-1 flex-col">
      <Link href="/library" className={cx("mb-4 flex items-center gap-2 px-2 font-display text-2xl", !active && "text-accent")}>
        Library
      </Link>
      {tables.length > 5 && (
        <label className="relative mb-3 block px-1">
          <span className="sr-only">Find a table</span>
          <Search className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-ink-3" aria-hidden />
          <input
            type="search"
            value={find}
            onChange={(e) => setFind(e.target.value)}
            placeholder="Find a table"
            className="w-full rounded-lg border border-line bg-surface py-1.5 pr-2 pl-8 text-sm outline-none focus:border-accent"
          />
        </label>
      )}
      <ul className="-mx-1 min-h-0 flex-1 space-y-0.5 overflow-y-auto px-1">
        {dashboards.length > 0 && (
          <li className="mb-1 px-2 text-xs font-medium tracking-wide text-ink-3 uppercase" aria-hidden>
            Dashboards
          </li>
        )}
        {dashboards
          .filter((d) => words.every((w) => `${d.name} ${d.description}`.toLowerCase().includes(w)))
          .map((d) => {
            const current = d.id === active;
            return (
              <li key={d.id}>
                <Link
                  href={`/library/dashboards/${d.id}`}
                  aria-current={current ? "page" : undefined}
                  title={d.description || d.name}
                  className={cx(
                    "flex items-center gap-2.5 rounded-lg px-2 py-2 text-sm transition-colors",
                    current ? "bg-surface font-medium text-ink shadow-sm" : "text-ink-2 hover:bg-surface-2 hover:text-ink",
                  )}
                >
                  <LayoutDashboard className={cx("size-4 shrink-0", current ? "text-accent" : "text-ink-3")} aria-hidden />
                  <span className="min-w-0 flex-1 truncate" dir="auto">
                    {d.name}
                  </span>
                </Link>
              </li>
            );
          })}
        {dashboards.length > 0 && (
          <li className="mt-5 mb-1 px-2 text-xs font-medium tracking-wide text-ink-3 uppercase" aria-hidden>
            Tables
          </li>
        )}
        {shown.map((t) => {
          const current = t.id === active || t.name === active;
          return (
            <li key={t.id}>
              <Link
                href={`/library/${encodeURIComponent(t.id)}`}
                aria-current={current ? "page" : undefined}
                title={t.description || t.name}
                className={cx(
                  "flex items-center gap-2.5 rounded-lg px-2 py-2 text-sm transition-colors",
                  current ? "bg-surface font-medium text-ink shadow-sm" : "text-ink-2 hover:bg-surface-2 hover:text-ink",
                )}
              >
                <Table2 className={cx("size-4 shrink-0", current ? "text-accent" : "text-ink-3")} aria-hidden />
                <span className="min-w-0 flex-1 truncate">{t.name}</span>
                <span className="text-xs text-ink-3 tabular-nums">{t.rows.toLocaleString("en-US")}</span>
              </Link>
            </li>
          );
        })}
        {shown.length === 0 && <li className="px-2 py-2 text-sm text-ink-3">{tables.length ? "No table by that name." : "No tables yet."}</li>}
        {plans.length > 0 && (
          <li className="mt-5 mb-1 px-2 text-xs font-medium tracking-wide text-ink-3 uppercase" aria-hidden>
            Plans
          </li>
        )}
        {plans
          .filter((p) => words.every((w) => p.title.toLowerCase().includes(w)))
          .map((p) => {
            const current = p.id === active;
            return (
              <li key={p.id}>
                <Link
                  href={`/library/plans/${p.id}`}
                  aria-current={current ? "page" : undefined}
                  title={p.title}
                  className={cx(
                    "flex items-center gap-2.5 rounded-lg px-2 py-2 text-sm transition-colors",
                    current ? "bg-surface font-medium text-ink shadow-sm" : "text-ink-2 hover:bg-surface-2 hover:text-ink",
                  )}
                >
                  <FileText className={cx("size-4 shrink-0", current ? "text-accent" : "text-ink-3")} aria-hidden />
                  <span className="min-w-0 flex-1 truncate" dir="auto">
                    {p.title}
                  </span>
                </Link>
              </li>
            );
          })}
        {(books.length > 0 || canTeach) && (
          <li className="mt-5 mb-1 px-2 text-xs font-medium tracking-wide text-ink-3 uppercase" aria-hidden>
            Books
          </li>
        )}
        {books
          .filter((b) => words.every((w) => `${b.title} ${b.author}`.toLowerCase().includes(w)))
          .map((b) => {
            const current = b.id === active;
            return (
              <li key={b.id}>
                <Link
                  href={`/library/books/${b.id}`}
                  aria-current={current ? "page" : undefined}
                  title={b.author ? `${b.title}, by ${b.author}` : b.title}
                  className={cx(
                    "flex items-center gap-2.5 rounded-lg px-2 py-2 text-sm transition-colors",
                    current ? "bg-surface font-medium text-ink shadow-sm" : "text-ink-2 hover:bg-surface-2 hover:text-ink",
                  )}
                >
                  <BookOpen className={cx("size-4 shrink-0", current ? "text-violet" : "text-ink-3")} aria-hidden />
                  <span className="min-w-0 flex-1 truncate" dir="auto">
                    {b.title}
                  </span>
                  {b.status === "studying" ? (
                    <Loader2 className="size-3.5 animate-spin text-accent" aria-label="Studying" />
                  ) : b.waiting ? (
                    <span className="grid h-5 min-w-5 place-items-center rounded-full bg-accent px-1.5 text-[0.7rem] font-semibold text-accent-ink" aria-label={`${b.waiting} ideas waiting`}>
                      {b.waiting}
                    </span>
                  ) : null}
                </Link>
              </li>
            );
          })}
        {canTeach && (
          <li>
            <Link href="/library?teach=1" className="flex items-center gap-2.5 rounded-lg px-2 py-2 text-sm text-ink-3 hover:bg-surface-2 hover:text-ink">
              <Plus className="size-4 shrink-0" aria-hidden /> Teach a book
            </Link>
          </li>
        )}
      </ul>
    </nav>
  );
}

/** The library page's search box: searches every table as the owner types (?q in the address). */
export function LibrarySearch({ initial }: { initial: string }) {
  const router = useRouter();
  const [pending, startNav] = useTransition();
  const [text, setText] = useState(initial);
  useEffect(() => {
    if (text.trim() === initial.trim()) return;
    const t = setTimeout(() => {
      const q = text.trim();
      startNav(() => router.replace(q ? `/library?q=${encodeURIComponent(q)}` : "/library", { scroll: false }));
    }, 350);
    return () => clearTimeout(t);
  }, [text, initial, router]);
  return (
    <label className="relative block">
      <span className="sr-only">Search the library</span>
      <Search className="pointer-events-none absolute top-1/2 left-3.5 size-5 -translate-y-1/2 text-ink-3" aria-hidden />
      <input
        type="search"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Search every table"
        autoFocus={Boolean(initial)}
        className="w-full rounded-xl border border-line bg-surface py-3 pr-10 pl-11 text-base outline-none focus:border-accent"
        dir="auto"
      />
      {pending && <Loader2 className="absolute top-1/2 right-3.5 size-4 -translate-y-1/2 animate-spin text-ink-3" aria-label="Searching" />}
    </label>
  );
}

/** Import a spreadsheet (CSV or Excel) as a new table, then open it. */
export function LibraryImport({ url }: { url: string }) {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function upload(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    setError(null);
    const res = await fetch(`${url}?name=${encodeURIComponent(file.name)}`, { method: "POST", body: file }).catch(() => null);
    const got = await res?.json().catch(() => null);
    if (input.current) input.current.value = "";
    if (!res?.ok || !got?.table) {
      setBusy(false);
      return setError(got?.error ?? "That file couldn't be imported. Try again.");
    }
    router.push(`/library/${encodeURIComponent(got.table.id)}`);
  }
  return (
    <div className="flex flex-col items-end">
      <button
        type="button"
        onClick={() => input.current?.click()}
        disabled={busy}
        className="inline-flex items-center gap-2 rounded-xl border border-line bg-surface px-4 py-3 text-sm text-ink-2 hover:border-accent hover:text-ink disabled:opacity-70"
      >
        {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Upload className="size-4" aria-hidden />}
        {busy ? "Importing…" : "Import a spreadsheet"}
      </button>
      <input ref={input} type="file" accept=".csv,.xlsx,.tsv" className="sr-only" onChange={(e) => upload(e.target.files?.[0])} />
      {error && (
        <p role="alert" className="mt-1 max-w-xs text-right text-xs text-rose">
          {error}
        </p>
      )}
    </div>
  );
}
