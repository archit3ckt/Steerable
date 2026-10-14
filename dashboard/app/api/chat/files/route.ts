import { uploadResponse } from "../../../../src/file-routes";
import { backend } from "../../../../local/host";

/** A picture or file the owner attaches in the chat. */
export const POST = (request: Request) => uploadResponse(backend, request);
