import { NextRequest, NextResponse } from "next/server";

/**
 * Optimistic, cookie-presence-only redirect to /who (PRD section 10.3:
 * "Any unauthenticated request redirects here"). Next.js 16 renamed
 * Middleware to Proxy; functionality is unchanged
 * (node_modules/next/dist/docs/01-app/01-getting-started/16-proxy.md).
 *
 * Per the Next.js authentication guide's "Optimistic checks with Proxy"
 * section, Proxy runs on every route (including prefetches) so it must
 * only read the cookie, never hit the database — that's what get_current_user
 * in api/auth.py is for. A cookie that exists but is expired or unknown
 * still reaches the app; the (app) layout's SessionProvider calls
 * GET /auth/me and redirects client-side if that 401s, as the real check.
 */

const COOKIE_NAME = "ripple_session";

export default function proxy(req: NextRequest) {
  const { pathname } = req.nextUrl;

  if (pathname === "/who") {
    return NextResponse.next();
  }

  if (!req.cookies.has(COOKIE_NAME)) {
    const url = req.nextUrl.clone();
    url.pathname = "/who";
    url.search = "";
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
