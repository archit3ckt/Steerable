import { NextResponse, type NextRequest } from "next/server";
import { agent, ToolsError, type ConnectedTool } from "../../../local/tools";

/** The browser comes back here from signing in to a service; the engine finishes the connection. */
export async function GET(request: NextRequest) {
  const q = request.nextUrl.searchParams;
  const back = new URL("/connections", request.url);
  const state = q.get("state");
  const code = q.get("code");
  if (!state || !code) {
    back.searchParams.set("error", q.get("error") === "access_denied" ? "You didn't allow it, so nothing was connected." : "The sign-in didn't finish. Try again.");
    return NextResponse.redirect(back);
  }
  try {
    const { connected } = await agent<{ connected: ConnectedTool }>("POST", "/v1/tools/callback", { state, code });
    back.searchParams.set("connected", connected.name);
  } catch (error) {
    if (!(error instanceof ToolsError)) throw error;
    back.searchParams.set("error", error.message);
  }
  return NextResponse.redirect(back);
}
