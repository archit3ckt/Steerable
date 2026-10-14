"use server";

import { refresh } from "next/cache";
import { redirect } from "next/navigation";
import { chatFiles, chatText, dashboardAction, libraryCells, libraryViewInput } from "../src/host";
import { backend } from "./host";

// The owner's actions. backend() checks the session first.

export async function decide(decisionId: string, optionId: string, note?: string) {
  let next: string | undefined;
  const result = await dashboardAction(backend, async (b) => {
    next = (await b.decide(decisionId, optionId, typeof note === "string" ? note.slice(0, 2000) : undefined)).next;
  });
  refresh();
  if (next?.startsWith("/")) redirect(next);
  return result;
}

export async function runRoutine(routineId: string) {
  const result = await dashboardAction(backend, (b) => b.runRoutine(routineId));
  refresh();
  return result;
}

export async function watchRoutine(routineId: string, watch: boolean) {
  const result = await dashboardAction(backend, (b) => b.watchRoutine(routineId, watch === true));
  refresh();
  return result;
}

export async function setRoutinePaused(routineId: string, paused: boolean) {
  const result = await dashboardAction(backend, (b) => b.setRoutinePaused(routineId, paused));
  refresh();
  return result;
}

export async function toggleTodo(todoId: string) {
  const result = await dashboardAction(backend, (b) => b.toggleTodo(todoId));
  refresh();
  return result;
}

export async function startOnboarding() {
  const result = await dashboardAction(backend, (b) => b.startOnboarding());
  refresh();
  return result;
}

export async function newConversation() {
  const result = await dashboardAction(backend, (b) => b.newConversation());
  refresh();
  return result;
}

export async function sendMessage(text: string, files: string[] = []) {
  const message = chatText(text) ?? "";
  const ids = chatFiles(files);
  if (!message && ids.length === 0) return {};
  const result = await dashboardAction(backend, (b) => b.send(message, ids));
  refresh();
  return result;
}

export async function saveValue(name: string, value: string) {
  const result = await dashboardAction(backend, (b) => b.saveValue(name, value));
  refresh();
  return result;
}

export async function saveLibraryRow(tableId: string, rowId: string | null, cells: Record<string, unknown>) {
  let id: string | undefined;
  const result = await dashboardAction(backend, async (b) => {
    id = (await b.saveLibraryRow(String(tableId), rowId ? String(rowId) : null, libraryCells(cells))).id;
  });
  refresh();
  return { ...result, id };
}

export async function setLibraryRowArchived(tableId: string, rowId: string, archived: boolean) {
  const result = await dashboardAction(backend, (b) => b.setLibraryRowArchived(String(tableId), String(rowId), archived === true));
  refresh();
  return result;
}

export async function saveLibraryView(tableId: string, viewId: string | null, view: unknown) {
  let id: string | undefined;
  const result = await dashboardAction(backend, async (b) => {
    id = (await b.saveLibraryView(String(tableId), viewId ? String(viewId) : null, libraryViewInput(view))).id;
  });
  refresh();
  return { ...result, id };
}

export async function deleteLibraryView(tableId: string, viewId: string) {
  const result = await dashboardAction(backend, (b) => b.deleteLibraryView(String(tableId), String(viewId)));
  refresh();
  return result;
}

export async function commentLibraryRow(tableId: string, rowId: string, text: string, ask: boolean) {
  const result = await dashboardAction(backend, (b) => b.commentLibraryRow(String(tableId), String(rowId), String(text).slice(0, 5000), ask === true));
  refresh();
  return result;
}

const bookId = (x: unknown) => (typeof x === "string" && /^[bp][0-9a-f]{4,20}$/.test(x) ? x : "");

export async function teachBook(fileId: string, why: string) {
  let id: string | undefined;
  const result = await dashboardAction(backend, async (b) => {
    id = (await b.teachBook(String(fileId).slice(0, 40), String(why ?? "").slice(0, 2000))).id;
  });
  refresh();
  return { ...result, id };
}

export async function answerBookIdea(book: string, idea: string, approve: boolean) {
  const result = await dashboardAction(backend, (b) => b.answerBookIdea(bookId(book), bookId(idea), approve === true));
  refresh();
  return result;
}

export async function setBookPaused(book: string, paused: boolean) {
  const result = await dashboardAction(backend, (b) => b.setBookPaused(bookId(book), paused === true));
  refresh();
  return result;
}

export async function retryBook(book: string) {
  const result = await dashboardAction(backend, (b) => b.retryBook(bookId(book)));
  refresh();
  return result;
}

export async function removeBook(book: string) {
  const result = await dashboardAction(backend, (b) => b.removeBook(bookId(book)));
  if (!result.error) redirect("/library");
  return result;
}
