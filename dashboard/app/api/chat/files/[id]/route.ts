import { fileResponse } from "../../../../../src/file-routes";
import { backend } from "../../../../../local/host";

/** A file attached in the chat: pictures show inline, the rest download. */
export async function GET(_: Request, ctx: RouteContext<"/api/chat/files/[id]">) {
  return fileResponse(backend, (await ctx.params).id);
}
