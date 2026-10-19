"use server";

import { refresh } from "next/cache";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { COOKIE, validSession } from "./auth";
import { SPACE_COOKIE, spaces } from "./host";
import { service, SpacesError } from "./spaces";

/** Opens another space (one of STEERABLE_SPACES), for the signed-in owner. */
export async function switchSpace(id: string): Promise<void> {
  const jar = await cookies();
  if (!validSession(jar.get(COOKIE)?.value, Date.now())) redirect("/login");
  if (spaces().some((s) => s.id === id)) {
    jar.set(SPACE_COOKIE, id, { httpOnly: true, sameSite: "lax", secure: process.env.NODE_ENV === "production", path: "/", maxAge: 365 * 24 * 60 * 60 });
  }
  redirect("/today");
}

/** Deletes a space (not the first): its COO, and everything in it. `confirm` must be its name. */
export async function deleteSpace(id: string, confirm: string): Promise<{ error?: string }> {
  const jar = await cookies();
  if (!validSession(jar.get(COOKIE)?.value, Date.now())) redirect("/login");
  const space = spaces().find((s) => s.id === id);
  if (!space || space.id === "main") return { error: "That space can't be deleted here." };
  if (confirm.trim() !== space.name) return { error: `Type ${space.name} exactly to confirm.` };
  try {
    await service("DELETE", `/spaces/${space.id}`);
  } catch (error) {
    if (error instanceof SpacesError) return { error: error.message };
    throw error;
  }
  if (jar.get(SPACE_COOKIE)?.value === space.id) jar.delete(SPACE_COOKIE);
  refresh();
  return {};
}
