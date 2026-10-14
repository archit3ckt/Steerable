import { forward } from "../../../../../local/sites";

/** Where the page is now: {url, title}. */
export async function GET(_request: Request, { params }: RouteContext<"/api/sites/sessions/[id]">) {
  return forward("GET", `/sessions/${encodeURIComponent((await params).id)}`);
}

/** Close it without saving. */
export async function DELETE(_request: Request, { params }: RouteContext<"/api/sites/sessions/[id]">) {
  return forward("POST", `/sessions/${encodeURIComponent((await params).id)}/cancel`);
}
