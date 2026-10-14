import { bodyOf, forward } from "../../../../local/sites";

/** Open a live login at {url}; with {account}, the sign-up (or a new login) for one of the COO's own accounts. */
export async function POST(request: Request) {
  const { url, account } = await bodyOf(request);
  return forward("POST", "/sessions", { url, account: typeof account === "string" ? account : undefined });
}
