import { bearer, engine } from "../../../../local/extension";

/** A login from the owner's own browser: {startUrl, name, cookies}, for a site they switched on. */
export async function POST(request: Request) {
  const { startUrl, name, cookies } = (await request.json().catch(() => ({}))) as Record<string, unknown>;
  return engine("logins", { token: bearer(request), startUrl, name, cookies });
}
