import { chatPageResponse } from "../../../../src/chat-routes";
import { backend } from "../../../../local/host";

/** A page of the conversation: earlier messages as the owner scrolls up, new ones while waiting. */
export const GET = (request: Request) => chatPageResponse(backend, request);
