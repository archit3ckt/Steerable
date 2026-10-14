import "server-only";
import { createHash, createHmac, timingSafeEqual } from "node:crypto";

/**
 * Self-hosted sign-in: one owner, one passphrase (DASHBOARD_PASSWORD). Signing in sets a cookie
 * holding an expiry and an HMAC of it, keyed from the passphrase, so changing the passphrase
 * signs everyone out.
 */

export const COOKIE = "steerable_owner";
const DAYS = 30;

const key = () => createHash("sha256").update(`steerable-dashboard:${process.env.DASHBOARD_PASSWORD ?? ""}`).digest();
const sign = (expires: number) => createHmac("sha256", key()).update(String(expires)).digest("base64url");

export function passwordSet(): boolean {
  return (process.env.DASHBOARD_PASSWORD ?? "").length >= 8;
}

export function checkPassword(given: string): boolean {
  if (!passwordSet()) return false;
  const a = createHash("sha256").update(given).digest();
  const b = createHash("sha256").update(process.env.DASHBOARD_PASSWORD ?? "").digest();
  return timingSafeEqual(a, b);
}

/** A new session cookie value and its lifetime in seconds. */
export function newSession(now: number): { value: string; maxAge: number } {
  const expires = now + DAYS * 86_400_000;
  return { value: `${expires}.${sign(expires)}`, maxAge: DAYS * 86_400 };
}

export function validSession(value: string | undefined, now: number): boolean {
  if (!value || !passwordSet()) return false;
  const [expires, mac] = value.split(".");
  if (!expires || !mac || Number(expires) < now) return false;
  const expected = Buffer.from(sign(Number(expires)));
  const given = Buffer.from(mac);
  return given.length === expected.length && timingSafeEqual(given, expected);
}
