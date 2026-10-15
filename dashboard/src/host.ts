import type { CellValue, CompanyBackend, LibraryView, LibraryViewConfig } from "./backend/types";
import { AgentError } from "./backend/agent";

/**
 * What an app hosting the dashboard provides. The dashboard is only the owner's screens; the
 * host decides who's signed in, which company they see, and where its engine is:
 *
 * - self-hosted (this folder's app): one owner, a passphrase, the engine's agent API next door
 * - Steerable Cloud: accounts, teams and many companies, each engine in its own container
 *
 * Pages take a host; client components take the host's server actions as props, so the
 * dashboard never reaches for a session or a company itself.
 */
export type DashboardHost = {
  /** The signed-in owner's company. Must check who's asking (pages call it on every render). */
  backend(): Promise<CompanyBackend>;
  /** "Now" for this request (Next forbids reading the clock while rendering). */
  now(): Promise<number>;
  actions: DashboardActions;
  /** Whether this dashboard has a Connections page ("Connect …" buttons on decisions link there). */
  connections: boolean;
  /**
   * A GET route answering the backend's chatActivity() as JSON. The chat polls it to show what
   * the COO is doing while the owner waits (a route, since Server Actions run one at a time).
   */
  chatActivityUrl?: string;
  /**
   * A GET route answering the backend's status() as JSON. With it, the health line under the
   * company name opens a live panel of what the COO is doing in the background.
   */
  statusUrl?: string;
  /**
   * A route for chat attachments: POST ?name=<file name> with the raw bytes answers the
   * backend's uploadFile() as JSON; GET /<id> answers file(id). With it, the chat can attach
   * pictures and files.
   */
  chatFilesUrl?: string;
  /**
   * A GET route answering the backend's chatPage() as JSON (body in the package's chat-routes.ts).
   * With it, the chat loads long threads a page at a time, and new messages without reloading.
   */
  chatPageUrl?: string;
  /**
   * A GET route answering the backend's runChanges() as JSON (?run=&table=&after=&limit=; body in
   * the package's run-routes.ts). With it, runs that changed the library open a table of what changed.
   */
  runChangesUrl?: string;
  /**
   * A route serving a plan's version to the chat (GET ?id=<plan>&v=<version>; body in plan-routes.ts):
   * the plans a reply saved open beside the chat, like artifacts.
   */
  plansUrl?: string;
  /**
   * A GET route for practice and watched runs (body in the package's trace-routes.ts): ?id=<trace>
   * answers the backend's trace() as JSON, &shot=<n>.jpg a picture from it. With it, decisions and
   * routine pages show exactly what a routine would do, or did, step by step.
   */
  tracesUrl?: string;
  /**
   * A route for library spreadsheets (body in the package's library-routes.ts): GET exports a table,
   * POST imports a CSV or Excel file. With it, the library shows Import and Export.
   */
  libraryFilesUrl?: string;
};

/** The owner's actions, as the host's Server Actions ("use server"), each calling host.backend(). */
export type DashboardActions = {
  /** `note`: the owner's words, for an option that asks for them. */
  decide(decisionId: string, optionId: string, note?: string): Promise<ActionResult>;
  setRoutinePaused(routineId: string, paused: boolean): Promise<ActionResult>;
  /** "Run now": one run of a routine that's switched on. */
  runRoutine(routineId: string): Promise<ActionResult>;
  /** Watch its runs (check what it can't undo first), or let it run on its own. */
  watchRoutine(routineId: string, watch: boolean): Promise<ActionResult>;
  toggleTodo(todoId: string): Promise<ActionResult>;
  startOnboarding(): Promise<ActionResult>;
  /** `files`: ids the chat got from the host's chatFilesUrl. */
  sendMessage(text: string, files?: string[]): Promise<ActionResult>;
  newConversation(): Promise<ActionResult>;
  /** The owner adds something the COO asked for (a private link, a key). */
  saveValue(name: string, value: string): Promise<ActionResult>;
  /** A library row: add one (rowId null) or change some cells (by column name; null clears). */
  saveLibraryRow(tableId: string, rowId: string | null, cells: Record<string, CellValue>): Promise<ActionResult & { id?: string }>;
  setLibraryRowArchived(tableId: string, rowId: string, archived: boolean): Promise<ActionResult>;
  saveLibraryView(tableId: string, viewId: string | null, view: { name?: string; type?: LibraryView["type"]; config?: LibraryViewConfig }): Promise<ActionResult & { id?: string }>;
  deleteLibraryView(tableId: string, viewId: string): Promise<ActionResult>;
  commentLibraryRow(tableId: string, rowId: string, text: string, ask: boolean): Promise<ActionResult>;
  /** A book from a file uploaded through chatFilesUrl; returns its id. */
  teachBook(fileId: string, why: string): Promise<ActionResult & { id?: string }>;
  answerBookIdea(bookId: string, ideaId: string, approve: boolean): Promise<ActionResult>;
  setBookPaused(bookId: string, paused: boolean): Promise<ActionResult>;
  retryBook(bookId: string): Promise<ActionResult>;
  removeBook(bookId: string): Promise<ActionResult>;
  /** The owner's edit of a plan: a new version. */
  savePlan(planId: string, body: string, note: string): Promise<ActionResult>;
  restorePlan(planId: string, version: number): Promise<ActionResult>;
  /** Archives it and goes back to the library. */
  removePlan(planId: string): Promise<ActionResult>;
};

/** Actions return { error } instead of throwing: in production Next hides thrown messages. */
export type ActionResult = { error?: string };

/**
 * The body of each host action: runs it against the backend and turns the engine's errors
 * (written for the owner) into { error }. The host calls refresh() from next/cache afterwards.
 *
 *   export async function decide(id: string, option: string) {
 *     const result = await dashboardAction(backend, (b) => b.decide(id, option));
 *     refresh();
 *     return result;
 *   }
 */
export async function dashboardAction(backend: () => Promise<CompanyBackend>, work: (b: CompanyBackend) => Promise<unknown>): Promise<ActionResult> {
  try {
    await work(await backend());
    return {};
  } catch (error) {
    if (error instanceof AgentError) return { error: error.message };
    throw error;
  }
}

/** Library cells from the browser, checked for shape (the engine checks the values): up to 100 columns. */
export function libraryCells(cells: unknown): Record<string, CellValue> {
  if (!cells || typeof cells !== "object" || Array.isArray(cells)) return {};
  const out: Record<string, CellValue> = {};
  for (const [name, value] of Object.entries(cells).slice(0, 100)) {
    if (name.length > 60) continue;
    if (value === null || typeof value === "boolean" || (typeof value === "number" && Number.isFinite(value))) out[name] = value;
    else if (typeof value === "string") out[name] = value.slice(0, 20_000);
  }
  return out;
}

/** A view from the browser, checked for shape (the engine checks the names and columns). */
export function libraryViewInput(view: unknown): { name?: string; type?: LibraryView["type"]; config?: LibraryViewConfig } {
  const v = view && typeof view === "object" ? (view as Record<string, unknown>) : {};
  const text = (x: unknown, max = 60) => (typeof x === "string" ? x.slice(0, max) : undefined);
  const out: { name?: string; type?: LibraryView["type"]; config?: LibraryViewConfig } = {};
  if (text(v.name) !== undefined) out.name = text(v.name);
  if (v.type === "grid" || v.type === "kanban" || v.type === "calendar") out.type = v.type;
  const c = v.config && typeof v.config === "object" ? (v.config as Record<string, unknown>) : null;
  if (c) {
    const where: Record<string, string> = {};
    if (c.where && typeof c.where === "object") for (const [k, x] of Object.entries(c.where).slice(0, 20)) if (typeof x === "string") where[k.slice(0, 60)] = x.slice(0, 200);
    out.config = {
      sort: text(c.sort),
      dir: c.dir === "desc" ? "desc" : "asc",
      where,
      hidden: Array.isArray(c.hidden) ? c.hidden.filter((h): h is string => typeof h === "string").slice(0, 100) : [],
      group: text(c.group),
      by: text(c.by),
    };
  }
  return out;
}

/** The file ids a chat message may carry (from the host's chatFilesUrl), up to 10. */
export function chatFiles(files: unknown): string[] {
  return Array.isArray(files) ? files.filter((f): f is string => typeof f === "string" && /^[\w-]{1,40}$/.test(f)).slice(0, 10) : [];
}

/**
 * The text of a chat message as the engine takes it, or null if there's nothing to send. Long
 * text is fine: the engine refuses past its limit (20,000 characters) with a plain reason.
 */
export function chatText(text: string): string | null {
  const trimmed = text.trim();
  return trimmed || null;
}
