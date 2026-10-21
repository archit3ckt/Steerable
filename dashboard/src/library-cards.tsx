"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import type { CellValue, LibraryColumn, LibraryPage } from "./backend/types";
import { CellView, number, rowTitle } from "./library-cells";
import type { ViewContext } from "./library-workspace";

const FIELDS = 5; // fields on a card, below its title

function empty(v: CellValue | undefined): boolean {
  return v === null || v === undefined || v === "" || (Array.isArray(v) && !v.length);
}

/** The first picture in a row's files columns, for its card's cover. */
function cover(columns: LibraryColumn[], cells: Record<string, CellValue>, files: ViewContext["files"]): { col: string; id: string } | null {
  for (const c of columns) {
    if (c.type !== "files" || !Array.isArray(cells[c.name])) continue;
    const id = (cells[c.name] as string[]).find((f) => files[f]?.kind === "image");
    if (id) return { col: c.name, id };
  }
  return null;
}

/**
 * Rows as cards, monday- and Teable-style: the first field as the title, a picture from the row's files
 * as the cover when it has one, and the next few shown fields below. A card opens the row's side panel;
 * the view's filters, sort and hidden fields apply as in the grid, and it pages the same way.
 */
export function CardsView({ ctx, page }: { ctx: ViewContext; page: LibraryPage }) {
  const { shown, nav, pageSize } = ctx;
  const title = ctx.columns[0];
  const from = page.total ? nav.offset + 1 : 0;
  const to = Math.min(nav.offset + pageSize, page.total);

  if (!page.rows.length) {
    return (
      <p className="rounded-2xl border border-line bg-surface px-4 py-10 text-center text-sm text-ink-3">
        {nav.q || Object.keys(ctx.config.where ?? {}).length ? "No rows match." : "No rows yet."}
      </p>
    );
  }
  return (
    <>
      <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
        {page.rows.map((r) => {
          const pic = ctx.filesUrl ? cover(ctx.columns, r.cells, ctx.files) : null;
          const fields = shown.filter((c) => c.id !== title?.id && c.name !== pic?.col && !empty(r.cells[c.name])).slice(0, FIELDS);
          return (
            <li key={r.id} className="min-w-0">
              <button
                type="button"
                onClick={() => ctx.openRow(r.id)}
                className="flex h-full w-full flex-col overflow-hidden rounded-2xl border border-line bg-surface text-start shadow-card transition-shadow hover:shadow-lift"
              >
                {pic && (
                  // eslint-disable-next-line @next/next/no-img-element -- an owner's own file, served by the host
                  <img src={`${ctx.filesUrl}/${encodeURIComponent(pic.id)}`} alt="" loading="lazy" className="aspect-[4/3] w-full bg-surface-2 object-cover" />
                )}
                <span className="flex min-w-0 flex-1 flex-col gap-3 p-4">
                  <span className="font-medium break-words text-ink" dir="auto">
                    {rowTitle(ctx.columns, r.cells) || <span className="text-ink-3">Untitled</span>}
                  </span>
                  {fields.length > 0 && (
                    <dl className="flex flex-col gap-2">
                      {fields.map((c) => (
                        <div key={c.id} className="min-w-0">
                          <dt className="text-[11px] font-medium tracking-wide text-ink-3 uppercase">{c.name}</dt>
                          <dd className="mt-0.5 min-w-0 truncate text-sm text-ink-2" dir="auto">
                            <CellView col={c} value={r.cells[c.name]} related={ctx.related} files={ctx.files} filesUrl={ctx.filesUrl} />
                          </dd>
                        </div>
                      ))}
                    </dl>
                  )}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      {page.total > pageSize && (
        <div className="mt-3 flex items-center justify-end gap-2 text-sm text-ink-3">
          <span>
            {number(from)}–{number(to)} of {number(page.total)}
          </span>
          <button type="button" disabled={nav.offset === 0} onClick={() => ctx.go({ offset: Math.max(0, nav.offset - pageSize) })} className="rounded-lg border border-line p-1.5 hover:text-ink disabled:opacity-40" aria-label="Previous page">
            <ChevronLeft className="size-4" />
          </button>
          <button type="button" disabled={to >= page.total} onClick={() => ctx.go({ offset: nav.offset + pageSize })} className="rounded-lg border border-line p-1.5 hover:text-ink disabled:opacity-40" aria-label="Next page">
            <ChevronRight className="size-4" />
          </button>
        </div>
      )}
    </>
  );
}
