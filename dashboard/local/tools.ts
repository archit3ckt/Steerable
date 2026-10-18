import "server-only";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { connection } from "next/server";
import { COOKIE, validSession } from "./auth";
import type { ExtensionStatus } from "../src/extension-card";
import { agentToken, currentSpace } from "./host";

/**
 * The services the owner connects themselves (the engine's scripts/tools.py), through the agent
 * API's /v1/tools. Only the self-hosted app has these: Steerable Cloud connects services for you.
 */

export type CatalogItem = {
  id: string;
  name: string;
  description: string;
  category: string;
  uses: string[];
  auth: { type: "mcp-oauth" | "apikey"; keyLabel?: string; keyHint?: string; optional?: boolean };
  /** When we connected it with a real account and saw it work (YYYY-MM-DD); without it, it's shown as Beta. */
  tested?: string;
  /** Shown first, in this order, under Popular (the services most owners use). */
  popular?: number;
};

export type ConnectedTool = { id: string; name: string; url: string; custom: boolean; connectedAt: string; tools: number; readOnly: string[] };

export type ToolsOverview = {
  catalog: CatalogItem[];
  connected: ConnectedTool[];
  alwaysAllowed: { tool: string; service: string; what: string }[];
  /** Claude Code is signed in with a Claude account, so the owner's claude.ai connectors work too. */
  claudeAccount: boolean;
  /** Connected to Steerable Cloud, which brings its own connected services. */
  throughSteerable: boolean;
};

export class ToolsError extends Error {}

export async function signedIn(): Promise<void> {
  await connection();
  if (!validSession((await cookies()).get(COOKIE)?.value, Date.now())) redirect("/login");
}

export async function agent<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
  await signedIn();
  const space = await currentSpace();
  let res: Response;
  try {
    res = await fetch(new URL(path, space.url), {
      method,
      headers: { Authorization: `Bearer ${agentToken(space) ?? ""}`, "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
      signal: AbortSignal.timeout(60_000),
    });
  } catch {
    throw new ToolsError(`Can't reach ${space.cooName} right now. Try again in a minute.`);
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ToolsError(typeof data?.error === "string" ? data.error : "Something went wrong. Try again.");
  return data as T;
}

export const toolsOverview = () => agent<ToolsOverview>("GET", "/v1/tools");

/** How the COO reaches its AI (the engine's scripts/ai_access.py). */
export type AiStatus = {
  claude: {
    /** account: the owner's Claude account. key: an API key in the server's settings. steerable: through Steerable Cloud. */
    method: "account" | "key" | "steerable" | "none";
    email: string | null;
    /** A sign-in is waiting for the code Claude shows the owner. */
    signingIn: boolean;
    url: string | null;
  };
  jev: { on: boolean; ownKey: boolean; fromSettings: boolean };
};

export const aiStatus = () => agent<AiStatus>("GET", "/v1/ai");

/** The owner's own Telegram bot (the engine's scripts/telegram.py). */
export type TelegramStatus = {
  connected: boolean;
  bot: string | null;
  linked: boolean;
  /** A one-time link that binds the chat that opens it, while one is waiting. */
  linkUrl: string | null;
  /** The token comes from the server's settings (TELEGRAM_BOT_TOKEN), not this page. */
  fromSettings: boolean;
};

export const telegramStatus = () => agent<TelegramStatus>("GET", "/v1/telegram");

/** Website logins saved on the engine (scripts/sites.py), never the sessions themselves. */
export type SavedSite = {
  site: string;
  name: string;
  startUrl: string;
  savedAt: string;
  status: "ACTIVE" | "EXPIRED";
  /** "browser": the owner's own browser keeps it in step (the extension). "live": logged in on the dashboard. */
  source: "live" | "browser";
};

/** The browser extension (dashboard/extension/): whether a browser is paired. */
export type { ExtensionStatus } from "../src/extension-card";

export const extensionStatus = () => agent<ExtensionStatus>("GET", "/v1/extension");

export const savedSites = () => agent<SavedSite[]>("GET", "/v1/sites");

/** An account the COO has of its own (the engine's scripts/accounts.py), never its password. */
export type CooAccount = {
  site: string;
  name: string;
  why: string;
  signupUrl: string;
  loginUrl: string | null;
  email: string | null;
  status: "PROPOSED" | "APPROVED" | "ACTIVE";
  proposedAt: string;
  createdAt: string | null;
  lastUsed: string | null;
};

/** The COO's mailbox: its own (self-hosted) or one Steerable gives it. */
export type Mailbox = { address: string | null; provider: "own" | "steerable" | null };

export type AccountsOverview = { accounts: CooAccount[]; mailbox: Mailbox; phone: string; cooName: string };

export const accountsOverview = () => agent<AccountsOverview>("GET", "/v1/accounts");
export const cooAccount = (site: string) => agent<CooAccount>("GET", `/v1/accounts/${encodeURIComponent(site)}`);
