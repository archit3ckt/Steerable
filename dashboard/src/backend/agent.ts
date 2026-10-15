import "server-only";
import { cache } from "react";
import type {
  BackgroundStatus,
  Book,
  BookDetail,
  Plan,
  PlanDetail,
  PlanVersionDetail,
  BookPassage,
  ChatActivity,
  ChatFile,
  Check,
  ChatPage,
  ChatMessage,
  Company,
  CompanyBackend,
  Decision,
  Goal,
  Onboarding,
  Overview,
  Routine,
  RoutineDetail,
  LibraryComment,
  LibraryPage,
  LibraryQuery,
  LibraryRow,
  LibraryRowDetail,
  LibraryTableSummary,
  LibraryView,
  RunChanges,
  Trace,
  ValueRequest,
  TimelineEvent,
  Todo,
} from "./types";

/**
 * A company's real backend: the agent API running next to the engine in its container
 * (scripts/agent_api.py in the Steerable engine). The API already answers in the shapes of
 * types.ts, in the owner's words, so this is a thin, typed HTTP client.
 */

/** An error whose message can be shown to the owner as is. */
export class AgentError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "AgentError";
  }
}

const READ_TIMEOUT_MS = 10_000;
// Applying a fix or running a prepared step can take minutes; the API waits up to 45s for a chat reply.
const WRITE_TIMEOUT_MS = 120_000;
const CHAT_TIMEOUT_MS = 55_000;

async function request<T>(
  url: string,
  token: string,
  cooName: string,
  method: "GET" | "POST",
  path: string,
  body?: unknown,
  timeout = READ_TIMEOUT_MS,
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(new URL(path, url), {
      method,
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
      signal: AbortSignal.timeout(timeout),
    });
  } catch {
    throw new AgentError(`Can't reach ${cooName} right now. Try again in a minute.`, 503);
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const message = typeof data?.error === "string" ? data.error : "Something went wrong. Try again.";
    throw new AgentError(res.status === 401 ? `${cooName} didn't recognize this app. We're on it.` : message, res.status);
  }
  return data as T;
}

/** Reads are shared within one request: the sidebar, badge and page often ask for the same thing. */
const read = cache((url: string, token: string, cooName: string, path: string) =>
  request<unknown>(url, token, cooName, "GET", path),
);

/** A library query as the agent API's parameters. */
function libraryParams(query: LibraryQuery): URLSearchParams {
  const params = new URLSearchParams();
  if (query.q) params.set("q", query.q);
  if (query.sort) params.set("sort", query.sort);
  if (query.dir) params.set("dir", query.dir);
  if (query.archived) params.set("archived", "1");
  if (query.group) params.set("group", query.group);
  if (query.between) params.set("between", query.between.join(","));
  if (query.offset) params.set("offset", String(query.offset));
  if (query.limit) params.set("limit", String(query.limit));
  for (const [k, v] of Object.entries(query.where ?? {})) params.set(`where.${k}`, v);
  return params;
}

export function agentBackend({ url, token, company }: { url: string; token: string; company: Company }): CompanyBackend {
  function call<T>(method: "GET" | "POST", path: string, body?: unknown, timeout?: number): Promise<T> {
    if (method === "GET") return read(url, token, company.cooName, path) as Promise<T>;
    return request<T>(url, token, company.cooName, method, path, body, timeout);
  }

  const id = (value: string) => encodeURIComponent(value);

  return {
    async overview() {
      const o = await call<Overview>("GET", "/v1/overview");
      // Who the company is comes from our database; everything else from the engine.
      return { ...o, company };
    },
    decisions: () => call<Decision[]>("GET", "/v1/decisions"),
    decide: (decisionId, optionId, note) =>
      call<TimelineEvent>("POST", `/v1/decisions/${id(decisionId)}`, note ? { optionId, note } : { optionId }, WRITE_TIMEOUT_MS),
    timeline: (limit = 50) => call<TimelineEvent[]>("GET", `/v1/timeline?limit=${limit}`),
    routines: () => call<Routine[]>("GET", "/v1/routines"),
    async routine(routineId) {
      try {
        return await call<RoutineDetail>("GET", `/v1/routines/${id(routineId)}`);
      } catch (error) {
        if (error instanceof AgentError && error.status === 404) return null;
        throw error;
      }
    },
    async valueRequest(name) {
      try {
        return await call<ValueRequest>("GET", `/v1/values/${id(name)}`);
      } catch (error) {
        if (error instanceof AgentError && error.status === 400) return null;
        throw error;
      }
    },
    async saveValue(name, value) {
      await call("POST", `/v1/values/${id(name)}`, { value }, WRITE_TIMEOUT_MS);
    },
    async setRoutinePaused(routineId, paused) {
      await call("POST", `/v1/routines/${id(routineId)}/paused`, { paused }, WRITE_TIMEOUT_MS);
    },
    async runRoutine(routineId) {
      await call("POST", `/v1/routines/${id(routineId)}/run`, {}, WRITE_TIMEOUT_MS);
    },
    async watchRoutine(routineId, watch) {
      await call("POST", `/v1/routines/${id(routineId)}/watch`, { watch }, WRITE_TIMEOUT_MS);
    },
    async trace(traceId) {
      try {
        // Fresh each time: a watched run's trace grows while it runs.
        return await request<Trace>(url, token, company.cooName, "GET", `/v1/traces/${id(traceId)}`);
      } catch (error) {
        if (error instanceof AgentError && error.status === 404) return null;
        throw error;
      }
    },
    async traceShot(traceId, shot) {
      const res = await fetch(new URL(`/v1/traces/${id(traceId)}/shots/${id(shot)}`, url), {
        headers: { Authorization: `Bearer ${token}` },
        cache: "no-store",
        signal: AbortSignal.timeout(WRITE_TIMEOUT_MS),
      }).catch(() => null);
      if (!res) throw new AgentError(`Can't reach ${company.cooName} right now. Try again in a minute.`, 503);
      if (!res.ok) throw new AgentError("That picture isn't here any more.", res.status);
      return { data: await res.arrayBuffer(), contentType: "image/jpeg", disposition: "inline" };
    },
    library: () => call<LibraryTableSummary[]>("GET", "/v1/library"),
    async libraryTable(tableId, query = {}) {
      const params = libraryParams(query);
      try {
        return await call<LibraryPage>("GET", `/v1/library/tables/${id(tableId)}?${params}`);
      } catch (e) {
        if (e instanceof AgentError && e.status === 404) return null;
        throw e;
      }
    },
    async libraryRow(tableId, rowId) {
      try {
        return await call<LibraryRowDetail>("GET", `/v1/library/tables/${id(tableId)}/rows/${id(rowId)}`);
      } catch (e) {
        if (e instanceof AgentError && e.status === 404) return null;
        throw e;
      }
    },
    saveLibraryRow(tableId, rowId, cells) {
      const path = `/v1/library/tables/${id(tableId)}/rows${rowId ? `/${id(rowId)}` : ""}`;
      return call<LibraryRow>("POST", path, { cells }, WRITE_TIMEOUT_MS);
    },
    saveLibraryView(tableId, viewId, view) {
      return call<LibraryView>("POST", `/v1/library/tables/${id(tableId)}/views${viewId ? `/${id(viewId)}` : ""}`, view, WRITE_TIMEOUT_MS);
    },
    async deleteLibraryView(tableId, viewId) {
      await call("POST", `/v1/library/tables/${id(tableId)}/views/${id(viewId)}/delete`, {}, WRITE_TIMEOUT_MS);
    },
    commentLibraryRow(tableId, rowId, text, ask) {
      return call<LibraryComment>("POST", `/v1/library/tables/${id(tableId)}/rows/${id(rowId)}/comments`, { text, ask }, WRITE_TIMEOUT_MS);
    },
    async exportLibraryTable(tableId, query, format) {
      const params = libraryParams(query);
      params.set("format", format);
      const res = await fetch(new URL(`/v1/library/tables/${id(tableId)}/export?${params}`, url), {
        headers: { Authorization: `Bearer ${token}` },
        cache: "no-store",
        signal: AbortSignal.timeout(WRITE_TIMEOUT_MS),
      }).catch(() => null);
      if (!res) throw new AgentError(`Can't reach ${company.cooName} right now. Try again in a minute.`, 503);
      if (!res.ok) throw new AgentError(((await res.json().catch(() => null))?.error as string) ?? "That table couldn't be exported.", res.status);
      return {
        data: await res.arrayBuffer(),
        contentType: res.headers.get("Content-Type") ?? "application/octet-stream",
        disposition: res.headers.get("Content-Disposition") ?? "attachment",
      };
    },
    async importLibrary(name, data, options = {}) {
      const params = new URLSearchParams({ name });
      if (options.into) params.set("into", options.into);
      if (options.title) params.set("title", options.title);
      const res = await fetch(new URL(`/v1/library/import?${params}`, url), {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/octet-stream" },
        body: data,
        cache: "no-store",
        signal: AbortSignal.timeout(WRITE_TIMEOUT_MS),
      }).catch(() => null);
      if (!res) throw new AgentError(`Can't reach ${company.cooName} right now. Try again in a minute.`, 503);
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new AgentError(typeof body?.error === "string" ? body.error : "That file couldn't be imported.", res.status);
      return body;
    },
    async setLibraryRowArchived(tableId, rowId, archived) {
      await call("POST", `/v1/library/tables/${id(tableId)}/rows/${id(rowId)}/${archived ? "archive" : "restore"}`, {}, WRITE_TIMEOUT_MS);
    },
    plans: () => call<Plan[]>("GET", "/v1/plans"),
    async plan(planId) {
      try {
        return await call<PlanDetail>("GET", `/v1/plans/${id(planId)}`);
      } catch (e) {
        if (e instanceof AgentError && e.status === 404) return null;
        throw e;
      }
    },
    async planVersion(planId, version) {
      try {
        return await call<PlanVersionDetail>("GET", `/v1/plans/${id(planId)}/versions/${Math.trunc(version)}`);
      } catch (e) {
        if (e instanceof AgentError && e.status === 404) return null;
        throw e;
      }
    },
    async savePlan(planId, body, note) {
      await call("POST", `/v1/plans/${id(planId)}`, { body, note }, WRITE_TIMEOUT_MS);
    },
    async restorePlan(planId, version) {
      await call("POST", `/v1/plans/${id(planId)}/restore`, { version }, WRITE_TIMEOUT_MS);
    },
    async removePlan(planId) {
      await call("POST", `/v1/plans/${id(planId)}/delete`, {}, WRITE_TIMEOUT_MS);
    },
    books: () => call<Book[]>("GET", "/v1/books"),
    async book(bookId, q) {
      try {
        return await call<BookDetail>("GET", `/v1/books/${id(bookId)}${q ? `?q=${encodeURIComponent(q)}` : ""}`);
      } catch (e) {
        if (e instanceof AgentError && e.status === 404) return null;
        throw e;
      }
    },
    searchBooks: (q) => call<BookPassage[]>("GET", `/v1/books/search?q=${encodeURIComponent(q)}`),
    teachBook: (fileId, why) => call<Book>("POST", "/v1/books", { file: fileId, why }, WRITE_TIMEOUT_MS),
    async answerBookIdea(bookId, ideaId, approve) {
      await call("POST", `/v1/books/${id(bookId)}/proposals/${id(ideaId)}`, { approve }, WRITE_TIMEOUT_MS);
    },
    async setBookPaused(bookId, paused) {
      await call("POST", `/v1/books/${id(bookId)}/paused`, { paused }, WRITE_TIMEOUT_MS);
    },
    async retryBook(bookId) {
      await call("POST", `/v1/books/${id(bookId)}/retry`, {}, WRITE_TIMEOUT_MS);
    },
    async removeBook(bookId) {
      await call("POST", `/v1/books/${id(bookId)}/delete`, {}, WRITE_TIMEOUT_MS);
    },
    runChanges(runId, query = {}) {
      const params = new URLSearchParams(Object.entries(query).filter(([, v]) => v !== undefined && v !== "").map(([k, v]) => [k, String(v)]));
      return call<RunChanges>("GET", `/v1/runs/${id(runId)}/changes?${params}`);
    },
    todos: () => call<Todo[]>("GET", "/v1/todos"),
    async toggleTodo(todoId) {
      await call("POST", `/v1/todos/${id(todoId)}/toggle`, {}, WRITE_TIMEOUT_MS);
    },
    goals: () => call<Goal[]>("GET", "/v1/goals"),
    chat: () => call<ChatMessage[]>("GET", "/v1/chat"),
    async send(text, files = []) {
      const { reply } = await call<{ reply: ChatMessage | null }>("POST", "/v1/chat", { text, files }, CHAT_TIMEOUT_MS);
      return reply;
    },
    check: (messageId) => call<Check>("GET", `/v1/checks/${id(messageId)}`),
    startCheck: (messageId, kind) => call<Check>("POST", `/v1/checks/${id(messageId)}`, kind ? { kind } : {}, WRITE_TIMEOUT_MS),
    applyCheck: (messageId, editIds) =>
      call<{ plan: string; version: number; applied: string[]; skipped: string[] }>("POST", `/v1/checks/${id(messageId)}/apply`, { edits: editIds }, WRITE_TIMEOUT_MS),
    chatPage(query = {}) {
      const params = new URLSearchParams(Object.entries(query).filter(([, v]) => v !== undefined && v !== "").map(([k, v]) => [k, String(v)]));
      return request<ChatPage>(url, token, company.cooName, "GET", `/v1/chat/page?${params}`);
    },
    searchChat: (query) => request<ChatMessage[]>(url, token, company.cooName, "GET", `/v1/chat/search?q=${encodeURIComponent(query)}`),
    async uploadFile(name, data) {
      const res = await fetch(new URL(`/v1/files?name=${encodeURIComponent(name)}`, url), {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/octet-stream" },
        body: data,
        cache: "no-store",
        signal: AbortSignal.timeout(WRITE_TIMEOUT_MS),
      }).catch(() => null);
      if (!res) throw new AgentError(`Can't reach ${company.cooName} right now. Try again in a minute.`, 503);
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new AgentError(typeof body?.error === "string" ? body.error : "That file didn't upload. Try again.", res.status);
      return body as ChatFile;
    },
    async file(fileId) {
      const res = await fetch(new URL(`/v1/files/${id(fileId)}`, url), {
        headers: { Authorization: `Bearer ${token}` },
        cache: "no-store",
        signal: AbortSignal.timeout(WRITE_TIMEOUT_MS),
      }).catch(() => null);
      if (!res) throw new AgentError(`Can't reach ${company.cooName} right now. Try again in a minute.`, 503);
      if (!res.ok) throw new AgentError("That file isn't here any more.", res.status);
      return {
        data: await res.arrayBuffer(),
        contentType: res.headers.get("Content-Type") ?? "application/octet-stream",
        disposition: res.headers.get("Content-Disposition") ?? "attachment",
      };
    },
    // Always fresh: it's polled while the COO works, from a route, not shared within a page render.
    chatActivity: () => request<ChatActivity>(url, token, company.cooName, "GET", "/v1/chat/activity"),
    status: () => request<BackgroundStatus>(url, token, company.cooName, "GET", "/v1/status"),
    async newConversation() {
      await call("POST", "/v1/chat/new", {}, WRITE_TIMEOUT_MS);
    },
    onboarding: () => call<Onboarding>("GET", "/v1/onboarding"),
    async startOnboarding() {
      const { reply } = await call<{ reply: ChatMessage | null }>("POST", "/v1/onboarding/start", {}, CHAT_TIMEOUT_MS);
      return reply;
    },
  };
}
