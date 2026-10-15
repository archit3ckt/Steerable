import { Suspense, type ReactNode } from "react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, BookOpen, FileText, Loader2, Table2 } from "lucide-react";
import type { DashboardHost } from "../host";
import { ago } from "../format";
import { LibraryWorkspace, type LibraryBody, type LibraryNav } from "../library-workspace";
import { LibraryImport, LibrarySearch, LibrarySidebar } from "../library-sidebar";
import type { Actor, Book, BookPassage, CellValue, LibraryColumn, LibraryPage as LibraryPageData, PlanChange } from "../backend/types";
import { BookActions, BookSearch, IdeaCard, Passage, TeachBook } from "../library-books";
import { PlanEditor, RemovePlan, RestorePlan } from "../library-plans";
import { Markdown } from "../markdown";
import { Poll } from "../poll";
import { orNull } from "../shell";
import { Card, Empty, PageHeader, Skeleton, cx } from "../ui";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

const PAGE_SIZE = 100;
const LANE_SIZE = 50; // cards read per board column

/**
 * The library's frame: its own sidebar of tables (like monday's boards) and the rest of the width.
 * The shell is wide on /library (nav.tsx WIDE): a slim rail of the main pages instead of its sidebar.
 * On phones there's no sidebar: the library page lists the tables.
 */
function LibraryFrame({ host, active, children }: { host: DashboardHost; active?: string | Promise<string>; children: ReactNode }) {
  return (
    <div className="lg:-mt-14 lg:-mr-6 lg:-mb-16 lg:-ml-12 lg:flex">
      <aside className="sticky top-0 hidden h-dvh w-64 shrink-0 flex-col border-r border-line px-3 py-7 lg:flex">
        <Suspense fallback={<Skeleton className="h-48" />}>
          <TableList host={host} active={active} />
        </Suspense>
      </aside>
      <div className="min-w-0 flex-1 lg:pt-10 lg:pb-12 lg:pl-8">{children}</div>
    </div>
  );
}

async function TableList({ host, active }: { host: DashboardHost; active?: string | Promise<string> }) {
  const backend = await host.backend();
  const [tables, books, plans, id] = await Promise.all([orNull(backend.library()), orNull(backend.books()), orNull(backend.plans()), active]);
  return (
    <LibrarySidebar
      tables={tables ?? []}
      books={books ?? []}
      plans={plans ?? []}
      active={id ? decodeURIComponent(id) : undefined}
      canTeach={Boolean(host.chatFilesUrl)}
    />
  );
}

/** The library: the tables of records the COO and its routines keep (job openings, leads, orders). */
export function LibraryPage({ host, searchParams }: { host: DashboardHost; searchParams?: SearchParams }) {
  return (
    <LibraryFrame host={host}>
      <div className="mx-auto max-w-5xl lg:pt-4">
        <PageHeader title="Library" subtitle="The records kept for your business. Change anything you like: nothing is ever deleted, only archived." />
        <Suspense fallback={<Skeleton className="h-64" />}>
          <Overview host={host} searchParams={searchParams} />
        </Suspense>
      </div>
    </LibraryFrame>
  );
}

async function Overview({ host, searchParams }: { host: DashboardHost; searchParams?: SearchParams }) {
  const params = await searchParams;
  const q = one(params?.q).trim().slice(0, 200);
  return (
    <>
      <div className="mb-6 flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <LibrarySearch initial={q} />
        </div>
        {host.libraryFilesUrl && <LibraryImport url={host.libraryFilesUrl} />}
      </div>
      {q ? (
        <Results host={host} q={q} />
      ) : (
        <>
          <Plans host={host} />
          <Books host={host} teach={one(params?.teach) === "1"} />
          <Tables host={host} />
        </>
      )}
    </>
  );
}

function bookLine(b: Book): ReactNode {
  if (b.status === "studying") {
    return (
      <span className="inline-flex items-center gap-1.5 text-accent">
        <Loader2 className="size-3.5 animate-spin" aria-hidden /> {b.progress ?? "Reading"}
      </span>
    );
  }
  if (b.status === "failed") return <span className="text-rose">{b.error ?? "The study didn't finish"}</span>;
  if (b.status === "paused") return "Paused: its skills are set aside";
  if (b.waiting) return <span className="font-medium text-accent">{b.waiting} {b.waiting === 1 ? "idea" : "ideas"} waiting for you</span>;
  return `Learned: ${b.approved} ${b.approved === 1 ? "idea" : "ideas"} added`;
}

/** Who changed a plan, in words. */
function byWhom(who: Actor, coo: string): string {
  return who === "you" ? "you" : who === "autopilot" ? "a routine" : coo;
}

/** The business's plans (business plan, marketing plan...), each kept up to date with its versions. */
async function Plans({ host }: { host: DashboardHost }) {
  const backend = await host.backend();
  const [{ company }, plans] = await Promise.all([backend.overview(), orNull(backend.plans())]);
  if (!plans?.length) return null;
  return (
    <section className="mb-10">
      <h2 className="mb-3 text-sm font-medium tracking-wide text-ink-3 uppercase">Plans</h2>
      <div className="grid gap-3 sm:grid-cols-2">
        {plans.map((p) => (
          <Link key={p.id} href={`/library/plans/${p.id}`} className="group min-w-0">
            <Card className="flex h-full gap-3 p-5 transition-colors group-hover:border-accent">
              <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-accent-soft text-accent">
                <FileText className="size-4" aria-hidden />
              </span>
              <div className="min-w-0">
                <p className="truncate font-medium" dir="auto">
                  {p.title}
                </p>
                {p.summary && (
                  <p className="mt-0.5 line-clamp-2 text-sm text-ink-2" dir="auto">
                    {p.summary}
                  </p>
                )}
                <p className="mt-2 text-xs text-ink-3">
                  Version {p.version} · changed {ago(p.updatedAt)} by {byWhom(p.updatedBy, company.cooName)}
                </p>
              </div>
            </Card>
          </Link>
        ))}
      </div>
    </section>
  );
}

/** Books the owner taught the COO, and the way to teach one. */
async function Books({ host, teach }: { host: DashboardHost; teach: boolean }) {
  const backend = await host.backend();
  const [{ company }, books] = await Promise.all([backend.overview(), orNull(backend.books())]);
  if (!host.chatFilesUrl && !books?.length) return null;
  return (
    <section className="mb-10">
      {books?.some((b) => b.status === "studying") && <Poll seconds={6} />}
      <h2 className="mb-3 text-sm font-medium tracking-wide text-ink-3 uppercase">Books {company.cooName} learned from</h2>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {(books ?? []).map((b) => (
          <Link key={b.id} href={`/library/books/${b.id}`} className="group min-w-0">
            <Card className="h-full p-5 transition-colors group-hover:border-accent">
              <div className="flex items-start gap-3">
                <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-violet-soft text-violet">
                  <BookOpen className="size-4" aria-hidden />
                </span>
                <div className="min-w-0 flex-1">
                  <h3 className="font-medium break-words text-ink" dir="auto">
                    {b.title}
                  </h3>
                  {b.author && <p className="text-sm text-ink-3">{b.author}</p>}
                  <p className="mt-2 text-xs">{bookLine(b)}</p>
                </div>
              </div>
            </Card>
          </Link>
        ))}
        {host.chatFilesUrl && <TeachBook cooName={company.cooName} filesUrl={host.chatFilesUrl} teach={host.actions.teachBook} startOpen={teach} variant="card" />}
      </div>
    </section>
  );
}

function Passages({ passages, q }: { passages: BookPassage[]; q?: string }) {
  return (
    <ul className="space-y-3">
      {passages.map((p, i) => (
        <li key={i}>
          <Link href={`/library/books/${p.bookId}${q ? `?q=${encodeURIComponent(q)}` : ""}`} className="block rounded-xl border border-line bg-surface px-4 py-3 hover:border-accent">
            <p className="mb-1 text-xs text-ink-3">
              {q ? `“${p.book}”, ` : ""}chapter {p.chapter}: {p.chapterTitle}
            </p>
            <p className="text-sm leading-relaxed text-ink-2" dir="auto">
              <Passage text={p.passage} />
            </p>
          </Link>
        </li>
      ))}
    </ul>
  );
}

const ROWS_PER_TABLE = 5;

function cellText(col: LibraryColumn, value: CellValue | undefined, related: Record<string, string>): string {
  if (value === null || value === undefined || value === "") return "";
  if (col.type === "relation") return related[String(value)] ?? "";
  if (col.type === "checkbox") return value ? col.name : "";
  if (col.type === "link") return String(value).replace(/^https?:\/\/(www\.)?/, "");
  if (col.type === "files") return "";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "number") return value.toLocaleString("en-US", { maximumFractionDigits: 2 });
  return String(value);
}

/** The words searched for, marked in a piece of text. */
function Marked({ text, words }: { text: string; words: string[] }) {
  if (!words.length) return <>{text}</>;
  const pattern = new RegExp(`(${words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi");
  return (
    <>
      {text.split(pattern).map((part, i) =>
        i % 2 ? (
          <mark key={i} className="rounded bg-amber-soft px-0.5 text-ink">
            {part}
          </mark>
        ) : (
          part
        ),
      )}
    </>
  );
}

/** What a search finds: tables by name, then matching rows in each table (a few each, with a link to all). */
async function Results({ host, q }: { host: DashboardHost; q: string }) {
  const backend = await host.backend();
  const tables = await backend.library();
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  const named = tables.filter((t) => words.every((w) => `${t.name} ${t.description}`.toLowerCase().includes(w)));
  const [pages, passages] = await Promise.all([
    Promise.all(tables.map((t) => orNull(backend.libraryTable(t.id, { q, limit: ROWS_PER_TABLE })))),
    orNull(backend.searchBooks(q)),
  ]);
  const hits = pages.filter((p): p is LibraryPageData => Boolean(p && p.total > 0)).sort((a, b) => b.total - a.total);
  const found = hits.reduce((n, p) => n + p.total, 0);
  if (!named.length && !hits.length && !passages?.length) {
    return (
      <Empty icon={<Table2 className="size-5" />} title={`Nothing matches “${q}”`}>
        Every word has to appear in a row&apos;s text. Try fewer or different words.
      </Empty>
    );
  }
  const query = encodeURIComponent(q);
  return (
    <div className="space-y-8">
      {named.length > 0 && (
        <section>
          <h2 className="mb-3 text-sm font-medium tracking-wide text-ink-3 uppercase">Tables</h2>
          <div className="flex flex-wrap gap-2">
            {named.map((t) => (
              <Link
                key={t.id}
                href={`/library/${encodeURIComponent(t.id)}`}
                className="inline-flex items-center gap-2 rounded-xl border border-line bg-surface px-3 py-2 text-sm hover:border-accent"
              >
                <Table2 className="size-4 text-accent" aria-hidden />
                <Marked text={t.name} words={words} />
                <span className="text-xs text-ink-3">{t.rows.toLocaleString("en-US")}</span>
              </Link>
            ))}
          </div>
        </section>
      )}
      {hits.length > 0 && (
        <section>
          <h2 className="mb-3 text-sm font-medium tracking-wide text-ink-3 uppercase">
            {found.toLocaleString("en-US")} matching {found === 1 ? "row" : "rows"}
          </h2>
          <div className="space-y-4">
            {hits.map((page) => {
              const [primary, ...rest] = page.columns;
              const base = `/library/${encodeURIComponent(page.table.id)}?q=${query}`;
              return (
                <Card key={page.table.id} className="overflow-hidden">
                  <div className="flex items-baseline gap-3 border-b border-line px-5 py-3">
                    <h3 className="flex-1 font-medium">{page.table.name}</h3>
                    <Link href={base} className="text-sm text-accent hover:underline">
                      {page.total > page.rows.length ? `See all ${page.total.toLocaleString("en-US")}` : "Open the table"}
                    </Link>
                  </div>
                  <ul className="divide-y divide-line">
                    {page.rows.map((row) => {
                      const details = rest
                        .map((c) => cellText(c, row.cells[c.name], page.related))
                        .filter(Boolean)
                        .slice(0, 4);
                      return (
                        <li key={row.id}>
                          <Link href={`${base}&row=${encodeURIComponent(row.id)}`} className="block px-5 py-3 hover:bg-surface-2">
                            <p className="truncate text-sm font-medium" dir="auto">
                              <Marked text={primary ? cellText(primary, row.cells[primary.name], page.related) || "Untitled" : "Untitled"} words={words} />
                            </p>
                            {details.length > 0 && (
                              <p className="mt-0.5 truncate text-xs text-ink-3" dir="auto">
                                {details.map((d, i) => (
                                  <span key={i}>
                                    {i > 0 && " · "}
                                    <Marked text={d.length > 80 ? `${d.slice(0, 79)}…` : d} words={words} />
                                  </span>
                                ))}
                              </p>
                            )}
                          </Link>
                        </li>
                      );
                    })}
                  </ul>
                </Card>
              );
            })}
          </div>
        </section>
      )}
      {passages && passages.length > 0 && (
        <section>
          <h2 className="mb-3 text-sm font-medium tracking-wide text-ink-3 uppercase">In your books</h2>
          <Passages passages={passages} q={q} />
        </section>
      )}
    </div>
  );
}

async function Tables({ host }: { host: DashboardHost }) {
  const backend = await host.backend();
  const [{ company }, tables, now] = await Promise.all([backend.overview(), backend.library(), host.now()]);
  if (!tables.length) {
    return (
      <Empty icon={<Table2 className="size-5" />} title="Nothing here yet">
        When {company.cooName} or a routine keeps records for you (job openings, leads, orders, suppliers), they show up here as tables you can search, sort and change.
      </Empty>
    );
  }
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {tables.map((t) => (
        <Link key={t.id} href={`/library/${encodeURIComponent(t.id)}`} className="group min-w-0">
          <Card className="h-full p-5 transition-colors group-hover:border-accent">
            <div className="flex items-start gap-3">
              <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-accent-soft text-accent">
                <Table2 className="size-4" aria-hidden />
              </span>
              <div className="min-w-0 flex-1">
                <h2 className="font-medium text-ink">{t.name}</h2>
                {t.description && <p className="mt-0.5 text-sm text-ink-2">{t.description}</p>}
                <p className="mt-2 text-xs text-ink-3">
                  {t.rows.toLocaleString("en-US")} {t.rows === 1 ? "row" : "rows"} · changed {ago(t.updated, now)}
                </p>
                <p className="mt-2 truncate text-xs text-ink-3">{t.columns.join(" · ")}</p>
              </div>
            </div>
          </Card>
        </Link>
      ))}
    </div>
  );
}

/** One table as a grid. `searchParams`: the view (?q, sort, dir, where.<column>, archived, offset, row). */
export function LibraryTablePage({ host, id, searchParams }: { host: DashboardHost; id: string | Promise<string>; searchParams?: SearchParams }) {
  return (
    <LibraryFrame host={host} active={id}>
      <div className="-mx-1 sm:-mx-4 lg:mx-0">
        <Link href="/library" className="mb-4 inline-flex items-center gap-1.5 text-sm text-ink-3 hover:text-ink lg:hidden">
          <ArrowLeft className="size-4" aria-hidden /> Library
        </Link>
        <Suspense fallback={<Skeleton className="h-[32rem]" />}>
          <TableView host={host} id={id} searchParams={searchParams} />
        </Suspense>
      </div>
    </LibraryFrame>
  );
}

function one(value: string | string[] | undefined): string {
  return (Array.isArray(value) ? value[0] : value) ?? "";
}

function addDays(day: string, n: number): string {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

async function TableView({ host, id, searchParams }: { host: DashboardHost; id: string | Promise<string>; searchParams?: SearchParams }) {
  const tableId = decodeURIComponent(await id);
  const params = (await searchParams) ?? {};
  const backend = await host.backend();
  const [meta, { company }, now] = await Promise.all([backend.libraryTable(tableId, { limit: 1 }), backend.overview(), host.now()]);
  if (!meta) notFound();
  const view = meta.views.find((v) => v.id === one(params.view)) ?? meta.views[0];
  const cfg = view.config;
  const nav: LibraryNav = {
    view: view.id,
    q: one(params.q).slice(0, 200),
    offset: Math.max(0, Math.floor(Number(one(params.offset)) || 0)),
    row: one(params.row),
    month: /^\d{4}-\d{2}$/.test(one(params.month)) ? one(params.month) : "",
    archived: view.type === "grid" && one(params.archived) === "1",
  };
  const base = { q: nav.q || undefined, where: cfg.where, sort: cfg.sort, dir: cfg.dir };
  const related = { ...meta.related };
  const files = { ...meta.files };
  let body: LibraryBody;
  let total: number;
  if (view.type === "kanban" && cfg.by) {
    const by = cfg.by;
    const labels = meta.columns.find((c) => c.name === by)?.options.labels ?? [];
    const where = { ...cfg.where };
    delete where[by];
    const pages = await Promise.all([...labels, ""].map((label) => backend.libraryTable(tableId, { ...base, where: { ...where, [by]: label }, limit: LANE_SIZE })));
    for (const p of pages) {
      Object.assign(related, p?.related);
      Object.assign(files, p?.files);
    }
    const lanes = pages.map((p, i) => ({ value: i < labels.length ? labels[i] : null, total: p?.total ?? 0, rows: p?.rows ?? [] }));
    total = lanes.reduce((n, l) => n + l.total, 0);
    body = { kind: "kanban", by, lanes };
  } else if (view.type === "calendar" && cfg.by) {
    const today = new Date(now).toISOString().slice(0, 10);
    const month = nav.month || today.slice(0, 7);
    const first = `${month}-01`;
    const start = addDays(first, -((new Date(`${first}T00:00:00Z`).getUTCDay() + 6) % 7)); // the Monday on or before the 1st
    const [page, undated] = await Promise.all([
      backend.libraryTable(tableId, { ...base, between: [cfg.by, start, addDays(start, 41)], limit: 500 }),
      backend.libraryTable(tableId, { ...base, where: { ...cfg.where, [cfg.by]: "" }, limit: 1 }),
    ]);
    Object.assign(related, page?.related);
    total = page?.total ?? 0;
    body = { kind: "calendar", by: cfg.by, month, start, today, rows: page?.rows ?? [], undated: undated?.total ?? 0 };
  } else {
    const page = await backend.libraryTable(tableId, { ...base, group: cfg.group, archived: nav.archived, offset: nav.offset, limit: PAGE_SIZE });
    if (!page) notFound();
    Object.assign(related, page.related);
    Object.assign(files, page.files);
    total = page.total;
    body = { kind: "grid", page };
  }
  const detail = nav.row ? await backend.libraryRow(tableId, nav.row) : null;
  return (
    <>
      <header className="mb-4">
        <h1 className="font-display text-4xl leading-tight">{meta.table.name}</h1>
        {meta.table.description && <p className="mt-1 text-ink-2">{meta.table.description}</p>}
      </header>
      <LibraryWorkspace
        table={meta.table}
        columns={meta.columns}
        views={meta.views}
        view={view}
        related={related}
        files={files}
        total={total}
        body={body}
        nav={nav}
        basePath={`/library/${encodeURIComponent(meta.table.id)}`}
        detail={detail}
        cooName={company.cooName}
        now={now}
        pageSize={PAGE_SIZE}
        filesUrl={host.chatFilesUrl}
        libraryFilesUrl={host.libraryFilesUrl}
        actions={host.actions}
      />
    </>
  );
}

/** A book the owner taught the COO: how its study is going, the ideas waiting, what was learned, its notes and text. */
export function LibraryBookPage({ host, id, searchParams }: { host: DashboardHost; id: string | Promise<string>; searchParams?: SearchParams }) {
  return (
    <LibraryFrame host={host} active={id}>
      <div className="mx-auto max-w-3xl">
        <Link href="/library" className="mb-4 inline-flex items-center gap-1.5 text-sm text-ink-3 hover:text-ink lg:hidden">
          <ArrowLeft className="size-4" aria-hidden /> Library
        </Link>
        <Suspense fallback={<Skeleton className="h-[32rem]" />}>
          <BookView host={host} id={id} searchParams={searchParams} />
        </Suspense>
      </div>
    </LibraryFrame>
  );
}

async function BookView({ host, id, searchParams }: { host: DashboardHost; id: string | Promise<string>; searchParams?: SearchParams }) {
  const bookId = decodeURIComponent(await id);
  const q = one((await searchParams)?.q).trim().slice(0, 200);
  const backend = await host.backend();
  const [book, { company }] = await Promise.all([backend.book(bookId, q || undefined), backend.overview()]);
  if (!book) notFound();
  const coo = company.cooName;
  const waiting = book.proposals.filter((p) => p.status === "waiting");
  const added = book.proposals.filter((p) => p.status === "approved");
  const skipped = book.proposals.filter((p) => p.status === "declined");
  const section = "mb-3 text-sm font-medium tracking-wide text-ink-3 uppercase";
  return (
    <article className="space-y-10 lg:pt-4">
      {book.status === "studying" && <Poll seconds={5} />}
      <header>
        <p className="mb-2 inline-flex items-center gap-1.5 text-sm text-violet">
          <BookOpen className="size-4" aria-hidden /> A book {coo} learned from
        </p>
        <h1 className="font-display text-4xl leading-tight" dir="auto">
          {book.title}
        </h1>
        {book.author && <p className="mt-1 text-ink-2">by {book.author}</p>}
        {book.why && (
          <blockquote className="mt-4 border-l-2 border-accent pl-4 text-ink-2 italic" dir="auto">
            {book.why}
          </blockquote>
        )}
        <p className="mt-3 text-sm text-ink-3">
          {book.chapters} chapters · about {Math.round(book.words / 1000).toLocaleString("en-US")}k words
        </p>
      </header>

      {book.status === "studying" && (
        <Card className="flex items-start gap-3 p-5">
          <Loader2 className="mt-0.5 size-5 shrink-0 animate-spin text-accent" aria-hidden />
          <div>
            <p className="font-medium">
              {coo} is studying it: {book.progress?.toLowerCase() ?? "reading"}.
            </p>
            <p className="mt-1 text-sm text-ink-2">Most books take a few minutes. You can leave this page; the ideas will be waiting here.</p>
          </div>
        </Card>
      )}
      {book.status === "failed" && (
        <Card className="p-5">
          <p className="font-medium text-rose">The study didn&apos;t finish.</p>
          <p className="mt-1 text-sm text-ink-2">{book.error}</p>
        </Card>
      )}
      {book.status === "paused" && (
        <Card className="p-5 text-sm text-ink-2">This book is paused: {coo} has set its skills aside. Resume it to use them again.</Card>
      )}

      {waiting.length > 0 && (
        <section>
          <h2 className={section}>
            {waiting.length} {waiting.length === 1 ? "idea" : "ideas"} waiting for you
          </h2>
          <p className="mb-4 text-sm text-ink-2">What {coo} would change about how it runs your business, from this book. Add the ones you agree with.</p>
          <ul className="space-y-3">
            {waiting.map((idea) => (
              <IdeaCard key={idea.id} bookId={book.id} idea={idea} answer={host.actions.answerBookIdea} />
            ))}
          </ul>
        </section>
      )}

      {added.length > 0 && (
        <section>
          <h2 className={section}>What {coo} learned</h2>
          <Card className="divide-y divide-line">
            {added.map((idea) => (
              <div key={idea.id} className="px-5 py-3">
                <p className="text-sm font-medium">
                  {idea.name} <span className="font-normal text-ink-3">· {idea.kind === "skill" ? "skill" : idea.kind === "routine" ? "routine" : "goal"}{idea.source && `, ${idea.source}`}</span>
                </p>
                <p className="text-sm text-ink-2">{idea.note ?? idea.summary}</p>
              </div>
            ))}
          </Card>
          {skipped.length > 0 && <p className="mt-2 text-xs text-ink-3">You skipped {skipped.length}.</p>}
        </section>
      )}

      {book.status !== "studying" && (
        <section>
          <h2 className={section}>Ask the book</h2>
          <BookSearch initial={q} cooName={coo} />
          {q && (
            <div className="mt-4">
              {book.passages.length ? <Passages passages={book.passages} /> : <p className="text-sm text-ink-3">Nothing in the book matches “{q}”.</p>}
            </div>
          )}
          <p className="mt-2 text-xs text-ink-3">{coo} searches it the same way when your questions touch on it, and says which chapter it&apos;s quoting.</p>
        </section>
      )}

      {book.notes && (
        <section>
          <details className="group rounded-2xl border border-line bg-surface">
            <summary className="cursor-pointer list-none px-5 py-4 font-medium">{coo}&apos;s notes, chapter by chapter</summary>
            <div className="border-t border-line px-5 py-4 text-sm">
              <Markdown text={book.notes} />
            </div>
          </details>
        </section>
      )}

      {book.contents.length > 0 && (
        <section>
          <h2 className={section}>Contents</h2>
          <ol className="columns-1 gap-8 text-sm text-ink-2 sm:columns-2">
            {book.contents.map((c, i) => (
              <li key={i} className="mb-1 break-inside-avoid" dir="auto">
                <span className="mr-2 text-ink-3 tabular-nums">{i + 1}.</span>
                {c}
              </li>
            ))}
          </ol>
        </section>
      )}

      <footer className="border-t border-line pt-6">
        <BookActions bookId={book.id} title={book.title} status={book.status} actions={host.actions} />
      </footer>
    </article>
  );
}

/** A plan: the current text (editable), every version with who changed it and why, and any version's changes with a way back. */
export function LibraryPlanPage({ host, id, searchParams }: { host: DashboardHost; id: string | Promise<string>; searchParams?: SearchParams }) {
  return (
    <LibraryFrame host={host} active={id}>
      <div className="mx-auto max-w-6xl">
        <Link href="/library" className="mb-4 inline-flex items-center gap-1.5 text-sm text-ink-3 hover:text-ink lg:hidden">
          <ArrowLeft className="size-4" aria-hidden /> Library
        </Link>
        <Suspense fallback={<Skeleton className="h-[32rem]" />}>
          <PlanView host={host} id={id} searchParams={searchParams} />
        </Suspense>
      </div>
    </LibraryFrame>
  );
}

async function PlanView({ host, id, searchParams }: { host: DashboardHost; id: string | Promise<string>; searchParams?: SearchParams }) {
  const planId = decodeURIComponent(await id);
  const params = await searchParams;
  const backend = await host.backend();
  const [plan, { company }] = await Promise.all([backend.plan(planId), backend.overview()]);
  if (!plan) notFound();
  const coo = company.cooName;
  const asked = Number.parseInt(one(params?.v), 10);
  const shown = Number.isFinite(asked) && asked !== plan.version ? await backend.planVersion(plan.id, asked) : null;
  const whole = one(params?.whole) === "1";
  const last = plan.versions[0];
  return (
    <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_17rem] lg:pt-4">
      <article className="min-w-0">
        <header className="mb-6">
          <p className="mb-2 inline-flex items-center gap-1.5 text-sm text-accent">
            <FileText className="size-4" aria-hidden /> Plan
          </p>
          <h1 className="font-display text-4xl leading-tight" dir="auto">
            {plan.title}
          </h1>
          <p className="mt-2 text-sm text-ink-3">
            Version {plan.version} · changed {ago(plan.updatedAt)} by {byWhom(plan.updatedBy, coo)}
            {last?.note ? `: ${last.note}` : ""}
          </p>
        </header>

        {shown ? (
          <section>
            <Card className="mb-5 flex flex-wrap items-center justify-between gap-4 p-5">
              <div>
                <p className="font-medium">Version {shown.n}</p>
                <p className="text-sm text-ink-2">
                  {ago(shown.at)} by {byWhom(shown.who, coo)}
                  {shown.note ? `: ${shown.note}` : ""}
                </p>
              </div>
              <RestorePlan planId={plan.id} version={shown.n} restore={host.actions.restorePlan} />
            </Card>
            <div className="mb-3 flex gap-4 text-sm">
              <Link href={`/library/plans/${plan.id}?v=${shown.n}`} className={whole ? "text-ink-3 hover:text-ink" : "font-medium text-ink"}>
                What it changed
              </Link>
              <Link href={`/library/plans/${plan.id}?v=${shown.n}&whole=1`} className={whole ? "font-medium text-ink" : "text-ink-3 hover:text-ink"}>
                The whole version
              </Link>
            </div>
            {whole ? (
              <Card className="p-6">
                <div dir="auto">
                  <Markdown text={shown.body} />
                </div>
              </Card>
            ) : (
              <Changes changes={shown.changes} first={shown.n === 1} />
            )}
          </section>
        ) : (
          <PlanEditor planId={plan.id} body={plan.body} save={host.actions.savePlan}>
            <Card className="p-6">
              <div dir="auto">
                <Markdown text={plan.body} />
              </div>
            </Card>
          </PlanEditor>
        )}
        <div className="mt-10 border-t border-line pt-5">
          <RemovePlan planId={plan.id} title={plan.title} remove={host.actions.removePlan} />
        </div>
      </article>

      <aside>
        <h2 className="mb-3 text-sm font-medium tracking-wide text-ink-3 uppercase">History</h2>
        <ol className="space-y-1">
          {plan.versions.map((v) => {
            const current = v.n === plan.version;
            const selected = shown ? shown.n === v.n : current;
            return (
              <li key={v.n}>
                <Link
                  href={current ? `/library/plans/${plan.id}` : `/library/plans/${plan.id}?v=${v.n}`}
                  aria-current={selected ? "page" : undefined}
                  className={cx("block rounded-xl px-3 py-2.5 text-sm transition-colors", selected ? "bg-surface shadow-sm" : "hover:bg-surface-2")}
                >
                  <span className="flex items-baseline justify-between gap-2">
                    <span className="font-medium">
                      Version {v.n}
                      {current && <span className="ml-1.5 text-xs font-normal text-accent">current</span>}
                    </span>
                    <span className="shrink-0 text-xs text-ink-3">{ago(v.at)}</span>
                  </span>
                  <span className="mt-0.5 block text-ink-2">
                    {v.restoredFrom ? `Back to version ${v.restoredFrom}` : v.note || "No note"}{" "}
                    <span className="text-ink-3">· {byWhom(v.who, coo)}</span>
                  </span>
                </Link>
              </li>
            );
          })}
        </ol>
      </aside>
    </div>
  );
}

/** What a version changed: added lines in green, removed ones struck through in rose, the rest folded. */
function Changes({ changes, first }: { changes: PlanChange[]; first: boolean }) {
  if (!changes.length) {
    return (
      <Empty icon={<FileText className="size-5" aria-hidden />} title="No changes">
        This version says the same as the one before.
      </Empty>
    );
  }
  return (
    <Card className="overflow-hidden py-2 font-mono text-sm leading-relaxed">
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
            {c.text}
          </p>
        ),
      )}
    </Card>
  );
}
