import { NextResponse, type NextRequest } from "next/server";
import { COOKIE, validSession } from "./local/auth";

/**
 * Everything but the sign-in page needs the owner's session. The browser extension's calls
 * (api/extension) come with its own token instead, which the engine checks.
 */
export function proxy(request: NextRequest) {
  if (validSession(request.cookies.get(COOKIE)?.value, Date.now())) return NextResponse.next();
  return NextResponse.redirect(new URL("/login", request.url));
}

export const config = {
  matcher: ["/((?!login|api/extension/|_next/|favicon.ico|icon.svg|apple-icon.png).*)"],
};
