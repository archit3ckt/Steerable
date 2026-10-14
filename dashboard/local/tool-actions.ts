"use server";

import { refresh } from "next/cache";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { agent, ToolsError, type ConnectedTool, type TelegramStatus } from "./tools";

export type ConnectState = { error?: string; connected?: string };

/** Where a sign-in comes back to: this dashboard, at the address the owner is using. */
async function callbackUrl(): Promise<string> {
  const h = await headers();
  const host = h.get("x-forwarded-host") ?? h.get("host") ?? "localhost:3100";
  const proto = h.get("x-forwarded-proto") ?? (host.startsWith("localhost") || host.startsWith("127.") ? "http" : "https");
  return `${proto}://${host}/connections/callback`;
}

/** Connect a service from the list (`id`) or the owner's own server (`url`, `name`), with an optional key. */
export async function connectTool(_prev: ConnectState, form: FormData): Promise<ConnectState> {
  const field = (name: string) => String(form.get(name) ?? "").trim() || undefined;
  let result: { authorizeUrl?: string; connected?: ConnectedTool };
  try {
    result = await agent("POST", "/v1/tools/connect", {
      id: field("id"),
      url: field("url"),
      name: field("name"),
      key: field("key"),
      redirectUri: await callbackUrl(),
    });
  } catch (error) {
    if (error instanceof ToolsError) return { error: error.message };
    throw error;
  }
  if (result.authorizeUrl) redirect(result.authorizeUrl);
  refresh();
  return { connected: result.connected?.name };
}

export async function disconnectTool(id: string): Promise<{ error?: string }> {
  try {
    await agent("POST", `/v1/tools/${encodeURIComponent(id)}/disconnect`);
  } catch (error) {
    if (error instanceof ToolsError) return { error: error.message };
    throw error;
  }
  refresh();
  return {};
}

export async function stopAlwaysAllowing(tool: string): Promise<{ error?: string }> {
  try {
    await agent("POST", "/v1/tools/always", { tool });
  } catch (error) {
    if (error instanceof ToolsError) return { error: error.message };
    throw error;
  }
  refresh();
  return {};
}

// ---------- the COO's AI: Claude account and Jev ----------

async function ai(path: string, body?: unknown): Promise<{ error?: string }> {
  try {
    await agent("POST", `/v1/ai/${path}`, body);
  } catch (error) {
    if (error instanceof ToolsError) return { error: error.message };
    throw error;
  }
  refresh();
  return {};
}

export async function startClaudeSignIn(): Promise<{ error?: string }> {
  return ai("claude/login");
}

export async function finishClaudeSignIn(_prev: { error?: string }, form: FormData): Promise<{ error?: string }> {
  return ai("claude/code", { code: String(form.get("code") ?? "") });
}

export async function cancelClaudeSignIn(): Promise<{ error?: string }> {
  return ai("claude/cancel");
}

export async function signOutOfClaude(): Promise<{ error?: string }> {
  return ai("claude/logout");
}

export async function saveJevKey(_prev: { error?: string }, form: FormData): Promise<{ error?: string }> {
  return ai("jev", { key: String(form.get("key") ?? "") });
}

export async function removeJevKey(): Promise<{ error?: string }> {
  return ai("jev/remove");
}

// ---------- Telegram ----------

async function telegram(path: string, body?: unknown): Promise<{ error?: string }> {
  try {
    await agent<TelegramStatus>("POST", `/v1/telegram/${path}`, body);
  } catch (error) {
    if (error instanceof ToolsError) return { error: error.message };
    throw error;
  }
  refresh();
  return {};
}

export async function connectTelegram(_prev: { error?: string }, form: FormData): Promise<{ error?: string }> {
  return telegram("token", { token: String(form.get("token") ?? "") });
}

export async function newTelegramLink(): Promise<{ error?: string }> {
  return telegram("link");
}

export async function disconnectTelegram(): Promise<{ error?: string }> {
  return telegram("disconnect");
}

// ---------- website logins ----------

export async function removeSite(site: string): Promise<{ error?: string }> {
  try {
    await agent("POST", `/v1/sites/${encodeURIComponent(site)}/remove`);
  } catch (error) {
    if (error instanceof ToolsError) return { error: error.message };
    throw error;
  }
  refresh();
  return {};
}

/** The COO's own mailbox (self-hosted): its address and IMAP details, checked before they're kept. */
export async function connectMailbox(_prev: { error?: string }, form: FormData): Promise<{ error?: string }> {
  const field = (name: string) => String(form.get(name) ?? "").trim();
  try {
    await agent("POST", "/v1/mailbox", {
      address: field("address"),
      imapHost: field("imapHost"),
      imapPort: Number(field("imapPort")) || 993,
      user: field("user"),
      password: String(form.get("password") ?? ""),
    });
  } catch (error) {
    if (error instanceof ToolsError) return { error: error.message };
    throw error;
  }
  refresh();
  return {};
}

export async function disconnectMailbox(): Promise<{ error?: string }> {
  return run(() => agent("POST", "/v1/mailbox/disconnect"));
}

export async function setPhone(_prev: { error?: string; saved?: boolean }, form: FormData): Promise<{ error?: string; saved?: boolean }> {
  const result = await run(() => agent("POST", "/v1/accounts/phone", { phone: String(form.get("phone") ?? "") }));
  return result.error ? result : { saved: true };
}

/** An account's password, for the owner to see or copy. */
export async function accountPassword(site: string): Promise<{ error?: string; password?: string }> {
  try {
    return await agent<{ password: string }>("POST", `/v1/accounts/${encodeURIComponent(site)}/password`);
  } catch (error) {
    if (error instanceof ToolsError) return { error: error.message };
    throw error;
  }
}

export async function removeAccount(site: string): Promise<{ error?: string }> {
  return run(() => agent("POST", `/v1/accounts/${encodeURIComponent(site)}/remove`));
}

async function run(work: () => Promise<unknown>): Promise<{ error?: string }> {
  try {
    await work();
  } catch (error) {
    if (error instanceof ToolsError) return { error: error.message };
    throw error;
  }
  refresh();
  return {};
}

/** A one-time code for pairing the browser extension, to type into it. */
export async function newExtensionCode(): Promise<{ error?: string; code?: string; minutes?: number }> {
  try {
    return await agent<{ code: string; minutes: number }>("POST", "/v1/extension/code");
  } catch (error) {
    if (error instanceof ToolsError) return { error: error.message };
    throw error;
  }
}

export async function unpairExtension(): Promise<{ error?: string }> {
  return run(() => agent("POST", "/v1/extension/unpair"));
}
