import "server-only";
import { cookies } from "next/headers";
import { COOKIE, validSession } from "./auth";

/**
 * The spaces service (container/spaces.py): the only part of Steerable with Docker access. It
 * makes a space (another engine, with its own data) and deletes one; the dashboard asks it with
 * SPACES_TOKEN, over a network only the two of them share.
 */

export class SpacesError extends Error {}

export function spacesAvailable(): boolean {
  return Boolean(process.env.SPACES_URL && (process.env.SPACES_TOKEN ?? "").length >= 16);
}

export async function signedIn(): Promise<boolean> {
  return validSession((await cookies()).get(COOKIE)?.value, Date.now());
}

export async function service(method: "POST" | "DELETE", path: string, body?: ArrayBuffer): Promise<Record<string, unknown>> {
  if (!spacesAvailable()) throw new SpacesError("New spaces need the spaces service: update Steerable (run get.sh again).");
  const res = await fetch(new URL(path, process.env.SPACES_URL), {
    method,
    headers: { Authorization: `Bearer ${process.env.SPACES_TOKEN}`, ...(body ? { "Content-Type": "application/octet-stream" } : {}) },
    body: body && body.byteLength ? body : undefined,
    cache: "no-store",
    signal: AbortSignal.timeout(300_000),
  }).catch(() => null);
  if (!res) throw new SpacesError("The spaces service didn't answer. Is it running? (docker compose ps)");
  const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
  if (!res.ok) throw new SpacesError(typeof data.error === "string" ? data.error : "That didn't work. Try again in a minute.");
  return data;
}
