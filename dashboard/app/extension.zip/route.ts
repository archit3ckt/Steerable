import { extensionZipResponse } from "../../src/extension-zip";

/** The browser extension, for the signed-in owner to download (Connections). */
export function GET() {
  return extensionZipResponse();
}
