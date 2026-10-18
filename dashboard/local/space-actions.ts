"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { COOKIE, validSession } from "./auth";
import { SPACE_COOKIE, spaces } from "./host";

/** Opens another space (one of STEERABLE_SPACES), for the signed-in owner. */
export async function switchSpace(id: string): Promise<void> {
  const jar = await cookies();
  if (!validSession(jar.get(COOKIE)?.value, Date.now())) redirect("/login");
  if (spaces().some((s) => s.id === id)) {
    jar.set(SPACE_COOKIE, id, { httpOnly: true, sameSite: "lax", secure: process.env.NODE_ENV === "production", path: "/", maxAge: 365 * 24 * 60 * 60 });
  }
  redirect("/today");
}
