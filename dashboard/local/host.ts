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
 * The dashboard's host when you run it yourself: one company, its engine's agent API (start it
 * with `.venv/bin/python scripts/agent_api.py` in your company folder), configured in .env.local.
 */

export const company = {
  id: "local",
  name: process.env.COMPANY_NAME || "Your business",
  cooName: process.env.COO_NAME || "Juno",
  ownerFirstName: process.env.OWNER_NAME || "there",
};

export async function now(): Promise<number> {
  await connection();
  return Date.now();
}

/** AGENT_API_TOKEN, or (docker compose) the token the engine made, in AGENT_API_TOKEN_FILE. */
export function agentToken(): string | undefined {
  if (process.env.AGENT_API_TOKEN) return process.env.AGENT_API_TOKEN;
  const file = process.env.AGENT_API_TOKEN_FILE;
  try {
    return file ? readFileSync(file, "utf8").trim() : undefined;
  } catch {
    return undefined; // the engine hasn't made it yet (first start)
  }
}

/** The company's backend, for the signed-in owner only. */
export async function backend(): Promise<CompanyBackend> {
  await connection();
  if (!validSession((await cookies()).get(COOKIE)?.value, Date.now())) redirect("/login");
  const token = agentToken();
  if (!token) throw new Error("Set AGENT_API_TOKEN in .env.local (the same as in your company folder's .env).");
  return agentBackend({ url: process.env.AGENT_API_URL || "http://127.0.0.1:8787", token, company });
}

export const host: DashboardHost = { backend, now, actions, connections: true, chatActivityUrl: "/api/chat/activity", statusUrl: "/api/status", chatFilesUrl: "/api/chat/files", chatPageUrl: "/api/chat/page", runChangesUrl: "/api/runs/changes", plansUrl: "/api/plans", tracesUrl: "/api/traces", libraryFilesUrl: "/api/library/files" };
