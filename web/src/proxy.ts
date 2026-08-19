import { NextResponse, type NextRequest } from 'next/server'
import { SESSION_COOKIE, verifySessionToken } from '@/lib/auth'

/*
 * One gate in front of everything.
 *
 * This is `proxy.ts`, not `middleware.ts`: Next 16 deprecated and renamed the
 * middleware file convention (node_modules/next/dist/docs/.../upgrading/version-16.md
 * §"middleware to proxy"). A file named middleware.ts would still be picked up
 * today as a deprecated alias, but the failure mode when that alias is dropped
 * is the worst one available — the gate silently stops running and every route
 * is public again with no error anywhere. `proxy` also runs on the nodejs
 * runtime, not edge, and that is not configurable.
 *
 * Before this existed, /positions, /api/holdings, /api/positions and /api/copilot
 * served a concentrated portfolio's real holdings and open trades to anyone who
 * knew the URL — verified 200-with-data on 2026-08-19. A per-route check would
 * have meant remembering to add it to every future route; a default-deny
 * middleware means a new route is protected the moment it exists, and letting
 * something out is the deliberate act.
 *
 * Two things are deliberately NOT behind the session:
 *   - /api/cron/*  — bearer-authenticated with CRON_SECRET, called by GitHub
 *     Actions, the Hetzner cron and (eventually) a Cloudflare worker. None of
 *     them can hold a browser cookie. Those routes already hard-fail when
 *     CRON_SECRET is unset; verified returning 401 unauthenticated.
 *   - /login and /api/auth/*  — you cannot log in through the login gate.
 */

const PUBLIC_PREFIXES = ['/login', '/api/auth/', '/api/cron/']

function isPublicPath(pathname: string): boolean {
  return PUBLIC_PREFIXES.some((p) => pathname === p || pathname.startsWith(p))
}

export async function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl

  /*
   * Force HTTPS first. http://options.imprevista.com served the whole app in
   * plaintext — no redirect existed. A Secure session cookie is simply not sent
   * over http, so without this the login would appear broken on any http hit,
   * and any non-Secure cookie would travel in the clear.
   */
  /*
   * Use the Host HEADER, not request.nextUrl. Verified locally: nextUrl is built
   * from the address the server is listening on, not from Host — a request with
   * `Host: options.imprevista.com` still produced a redirect to
   * `http://127.0.0.1:3111/login`. Redirecting a real user to the container's
   * internal address is a broken login, so no redirect below may be built from
   * nextUrl's host.
   *
   * Trusting Host is sound here specifically because Traefik routes this
   * container on `Host(\`options.imprevista.com\`)` — nothing else reaches it.
   */
  const host = request.headers.get('host') ?? ''
  const hostname = host.split(':')[0]
  const isLoopback = hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '::1'

  // `next start`/`next dev` set x-forwarded-proto: http themselves, so without
  // the loopback carve-out local development would redirect to an https port
  // that is not listening. Only redirect a request that actually arrived over
  // plaintext at a real host — Traefik sets this header from the scheme it
  // terminated.
  const proto = request.headers.get('x-forwarded-proto')
  if (proto === 'http' && !isLoopback && host) {
    return NextResponse.redirect(`https://${host}${pathname}${search}`, 308)
  }

  if (isPublicPath(pathname)) return NextResponse.next()

  const session = await verifySessionToken(
    request.cookies.get(SESSION_COOKIE)?.value,
    process.env.SESSION_SECRET
  )
  if (session) return NextResponse.next()

  // APIs get a status code they can act on; humans get sent somewhere useful.
  if (pathname.startsWith('/api/')) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }

  /*
   * Absolute, and built from the Host header — not from nextUrl.
   *
   * Next's proxy layer parses Location as an absolute URL and throws
   * ERR_INVALID_URL on a relative one, which surfaces as a 500 on every
   * protected page (verified locally before this shipped). And nextUrl carries
   * the listening address, which would send a real user to the container's
   * internal host. Host + scheme is the only combination that is both accepted
   * and correct.
   *
   * `next` is the path only and is re-validated on the client before use, so
   * this cannot be turned into an open redirect to another site.
   */
  const scheme = isLoopback ? 'http' : 'https'
  const next = pathname !== '/' ? `?next=${encodeURIComponent(pathname + search)}` : ''
  return NextResponse.redirect(`${scheme}://${host}/login${next}`, 307)
}

export const config = {
  /*
   * Everything except Next's own static output and the favicon. Matching
   * broadly and carving out exceptions is the safe direction: a route that is
   * accidentally matched 401s (loud), one that is accidentally missed leaks
   * (silent).
   */
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
}
