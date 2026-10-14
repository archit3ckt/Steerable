"use server";

import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import { COOKIE, checkPassword, newSession, passwordSet } from "./auth";

const tries: number[] = [];

export async function signIn(_prev: { error?: string }, form: FormData): Promise<{ error?: string }> {
  if (!passwordSet()) return { error: "Set DASHBOARD_PASSWORD (8+ characters) in .env.local, then restart." };
  // A few tries a minute, for everyone: there's one owner.
  const now = Date.now();
  while (tries.length && tries[0] < now - 60_000) tries.shift();
  if (tries.length >= 5) return { error: "Too many tries. Wait a minute." };
  tries.push(now);
  if (!checkPassword(String(form.get("password") ?? ""))) return { error: "That's not the passphrase." };
  const session = newSession(now);
  (await cookies()).set(COOKIE, session.value, {
    httpOnly: true,
    sameSite: "lax",
    // Only over HTTPS: browsers drop "secure" cookies on plain http (other than localhost).
    secure: (await headers()).get("origin")?.startsWith("https://") ?? false,
    path: "/",
    maxAge: session.maxAge,
  });
  redirect("/today");
}

export async function signOut() {
  (await cookies()).delete(COOKIE);
  redirect("/login");
}
