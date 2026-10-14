import { bearer, engine } from "../../../../local/extension";

/** The logins the extension keeps in step, and whether they still work: {sites: [{site, name, status}]}. */
export async function GET(request: Request) {
  return engine("status", { token: bearer(request) });
}
