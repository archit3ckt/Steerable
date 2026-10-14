import { forward } from "../../../../../../local/sites";

/** A picture of the page now (JPEG). */
export async function GET(_request: Request, { params }: RouteContext<"/api/sites/sessions/[id]/frame">) {
  return forward("GET", `/sessions/${encodeURIComponent((await params).id)}/frame`);
}
