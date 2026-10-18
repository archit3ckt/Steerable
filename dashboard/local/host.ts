import "server-only";
import { readFileSync } from "node:fs";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { connection } from "next/server";
import { agentBackend } from "../src/backend/agent";
import type { CompanyBackend } from "../src/backend/types";
import type { DashboardHost } from "../src/host";
import * as actions from "./actions";
import { COOKIE, validSession } from "./auth";

/**
 * The dashboard's host when you run it yourself: your companies' engines (start one with
 * `.venv/bin/python scripts/agent_api.py` in a company folder), configured in .env.local, or by
 * docker compose. One space by default (COMPANY_NAME, AGENT_API_URL); more are separate engines,
 * each with its own folder, memory and connections, listed in STEERABLE_SPACES (get.sh
 * --add-space writes it). The owner switches between them; the one they're in is a cookie.
 */

export type Space = {
  id: string;
  name: string;
  cooName: string;
  /** Its engine's agent API. */
  url: string;
  /** Its agent API token, or the file the engine writes it to. */
  token?: string;
  tokenFile?: string;
};

export const SPACE_COOKIE = "steerable_space";

/** Every space: the first from COMPANY_NAME / AGENT_API_*, then STEERABLE_SPACES (JSON). */
export function spaces(): Space[] {
  const first: Space = {
    id: "main",
    name: process.env.COMPANY_NAME || "Your business",
    cooName: process.env.COO_NAME || "Juno",
    url: process.env.AGENT_API_URL || "http://127.0.0.1:8787",
    token: process.env.AGENT_API_TOKEN || undefined,
    tokenFile: process.env.AGENT_API_TOKEN_FILE || undefined,
  };
  let more: Space[] = [];
  try {
    const parsed = JSON.parse(process.env.STEERABLE_SPACES || "[]");
    if (Array.isArray(parsed)) {
      more = parsed
        .filter((s) => s && typeof s.id === "string" && /^[a-z0-9-]{1,30}$/.test(s.id) && s.id !== "main" && typeof s.url === "string")
        .map((s) => ({ id: s.id, name: String(s.name || s.id), cooName: String(s.cooName || "Juno"), url: s.url, token: s.token, tokenFile: s.tokenFile }));
    }
  } catch {
    // a broken list: just the first space
  }
  return [first, ...more];
}

/** The space the owner is in (the cookie, if it names one), else the first. */
export async function currentSpace(): Promise<Space> {
  const all = spaces();
  const chosen = (await cookies()).get(SPACE_COOKIE)?.value;
  return all.find((s) => s.id === chosen) ?? all[0];
}

/** What the screens call the current space and its COO. */
export async function currentCompany() {
  const space = await currentSpace();
  return { id: space.id, name: space.name, cooName: space.cooName, ownerFirstName: process.env.OWNER_NAME || "there" };
}

export async function now(): Promise<number> {
  await connection();
  return Date.now();
}

/** A space's agent API token: given, or (docker compose) the one its engine made, in its token file. */
export function agentToken(space: Space): string | undefined {
  if (space.token) return space.token;
  try {
    return space.tokenFile ? readFileSync(space.tokenFile, "utf8").trim() : undefined;
  } catch {
    return undefined; // the engine hasn't made it yet (first start)
  }
}

/** The current space's backend, for the signed-in owner only. */
export async function backend(): Promise<CompanyBackend> {
  await connection();
  if (!validSession((await cookies()).get(COOKIE)?.value, Date.now())) redirect("/login");
  const space = await currentSpace();
  const token = agentToken(space);
  if (!token) throw new Error("Set AGENT_API_TOKEN in .env.local (the same as in your company folder's .env).");
  return agentBackend({ url: space.url, token, company: await currentCompany() });
}

export const host: DashboardHost = { backend, now, actions, connections: true, chatActivityUrl: "/api/chat/activity", statusUrl: "/api/status", chatFilesUrl: "/api/chat/files", chatPageUrl: "/api/chat/page", runChangesUrl: "/api/runs/changes", plansUrl: "/api/plans", checksUrl: "/api/checks", tracesUrl: "/api/traces", libraryFilesUrl: "/api/library/files" };
