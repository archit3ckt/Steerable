import { engine } from "../../../../local/extension";

/** The extension trades the pairing code shown on Connections for its token: {code, browser} → {token, cooName}. */
export async function POST(request: Request) {
  const { code, browser } = (await request.json().catch(() => ({}))) as { code?: string; browser?: string };
  return engine("pair", { code, browser });
}
