import { service, signedIn, SpacesError } from "../../../local/spaces";

/** A new space: ?name=&coo=, and a company archive as the body to start from one (optional). */
export async function POST(request: Request) {
  if (!(await signedIn())) return Response.json({ error: "Sign in first." }, { status: 401 });
  const url = new URL(request.url);
  const params = new URLSearchParams({ name: url.searchParams.get("name") ?? "", coo: url.searchParams.get("coo") ?? "" });
  try {
    const data = await service("POST", `/spaces?${params}`, await request.arrayBuffer());
    return Response.json(data, { status: 201 });
  } catch (error) {
    if (!(error instanceof SpacesError)) throw error;
    return Response.json({ error: error.message }, { status: 400 });
  }
}
