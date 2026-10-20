"use client";

import { Archive, Loader2, Table2, Undo2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import type { LibraryTableSummary } from "./backend/types";
import type { DashboardActions } from "./host";
import { cx } from "./ui";

type SetArchived = DashboardActions["setLibraryTableArchived"];

const BUTTON = "inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-sm text-ink-2 hover:border-accent hover:text-ink disabled:opacity-60";

/** On a table's page: take the whole table out of the Library, after a plain "are you sure". */
export function ArchiveTableButton({ table, setArchived }: { table: { id: string; name: string }; setArchived: SetArchived }) {
  const router = useRouter();
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function archive() {
    setBusy(true);
    setError("");
    const result = await setArchived(table.id, true);
    if (result.error) {
      setBusy(false);
      setError(result.error);
      return;
    }
    router.push("/library");
  }

  if (!asking) {
    return (
      <button type="button" onClick={() => setAsking(true)} className={BUTTON}>
        <Archive className="size-4" aria-hidden /> Archive table
      </button>
    );
  }
  return (
    <div className="w-full max-w-sm rounded-xl border border-line bg-surface p-4 text-sm sm:w-auto">
      <p className="text-ink">Archive “{table.name}”?</p>
      <p className="mt-1 text-ink-2">It leaves your Library with everything in it kept. You can bring it back any time from the Library page.</p>
      {error && <p role="alert" className="mt-2 rounded-lg bg-rose-soft px-3 py-2 text-rose">{error}</p>}
      <div className="mt-3 flex gap-2">
        <button type="button" disabled={busy} onClick={archive} className={cx(BUTTON, "border-accent text-ink")}>
          {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Archive className="size-4" aria-hidden />} Archive it
        </button>
        <button type="button" disabled={busy} onClick={() => setAsking(false)} className="rounded-lg px-3 py-1.5 text-ink-2 hover:text-ink">
          Keep it
        </button>
      </div>
    </div>
  );
}

/** On the Library page: the archived tables, each with "Bring back". */
export function ArchivedTables({ tables, setArchived }: { tables: LibraryTableSummary[]; setArchived: SetArchived }) {
  const router = useRouter();
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function bringBack(id: string) {
    setBusy(id);
    setError("");
    const result = await setArchived(id, false);
    setBusy("");
    if (result.error) setError(result.error);
    else router.push(`/library/${encodeURIComponent(id)}`);
  }

  return (
    <details className="mt-6 rounded-xl border border-line px-4 py-3">
      <summary className="cursor-pointer text-sm text-ink-2 hover:text-ink">
        Archived tables ({tables.length})
      </summary>
      {error && <p role="alert" className="mt-3 rounded-lg bg-rose-soft px-3 py-2 text-sm text-rose">{error}</p>}
      <ul className="mt-3 divide-y divide-line">
        {tables.map((t) => (
          <li key={t.id} className="flex items-center gap-3 py-2.5">
            <Table2 className="size-4 shrink-0 text-ink-3" aria-hidden />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm text-ink">{t.name}</p>
              <p className="text-xs text-ink-3">{t.rows.toLocaleString("en-US")} {t.rows === 1 ? "row" : "rows"}</p>
            </div>
            <button type="button" disabled={Boolean(busy)} onClick={() => bringBack(t.id)} className={BUTTON}>
              {busy === t.id ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Undo2 className="size-4" aria-hidden />} Bring back
            </button>
          </li>
        ))}
      </ul>
    </details>
  );
}
