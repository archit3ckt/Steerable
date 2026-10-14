import { backend } from "../../../../local/host";

/** What the COO is doing for the reply it's working on. The chat polls it while the owner waits. */
export async function GET() {
  const activity = await backend()
    .then((b) => b.chatActivity())
    .catch(() => ({ working: false, steps: [] })); // signed out, or the engine is away: nothing to show
  return Response.json(activity, { headers: { "Cache-Control": "no-store" } });
}
