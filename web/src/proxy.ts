import { NextResponse, type NextRequest } from 'next/server'
import { SESSION_COOKIE, configuredUsers, verifySessionToken } from '@/lib/auth'

/*
 * One gate in front of everything.
 *
 * This is `proxy.ts`, not `middleware.ts`: Next 16 deprecated and renamed the
 * middleware file convention (see upgrading/version-16.md §"middleware to
 * proxy"). A file named middleware.ts would still be picked up today as a
 * deprecated alias, but the failure mode when that alias is dropped is the worst
 * one available — the gate silently stops running and every route is public
 * again with no error anywhere. `proxy` runs on the nodejs runtime, not edge,
 * and that is not configurable.
 *
 * Before this existed, /positions, /api/holdings, /api/positions and /api/copilot
 * served a concentrated portfolio's real holdings and open trades to anyone who
 * knew the URL — verified 200-with-data on 2026-08-19. A per-route check would
 * have meant remembering to add it to every future route; default-deny means a
 * new route is protected the moment it exists, and letting something out is the
 * deliberate act.
 */

/*
 * The deliberate holes. Each one is a decision, not an oversight.
 *
 * Trailing slashes are load-bearing. `startsWith('/login')` would also match
 * `/login-history` or `/loginaudit`, so the next page whose name happens to
 * begin with a public prefix would ship unauthenticated with no error anywhere.
 * Exact matches are listed separately from prefixes for that reason.
 */
const PUBLIC_EXACT = new Set([
  '/login',
  // Charles's call, 2026-08-19: the how-it-works page's whole job is to be
  // evidence for a reader who does NOT have a login — Dad before he is set up,
  // and anyone he shows it to. A locked evidence page is a contradiction. What
  // it exposes is liveness timestamps and hypothesis names/verdicts, all of
  // which are already public in this repo.
  '/how-it-works',
  '/api/status',
  '/api/graveyard',
])

const PUBLIC_PREFIXES = [
  '/login/',
  '/api/auth/',   // you cannot log in through the login gate
  '/api/cron/',   // bearer-authenticated with CRON_SECRET; GitHub Actions, the
                  // Hetzner cron, Uptime Kuma and a Cloudflare worker call these
                  // and none of them can hold a browser cookie. Those routes
                  // hard-fail when CRON_SECRET is unset.
]

function isPublicPath(pathname: string): boolean {
  return PUBLIC_EXACT.has(pathname) || PUBLIC_PREFIXES.some((p) => pathname.startsWith(p))
}

export async function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl

  /*
   * Use the Host HEADER, not request.nextUrl. Verified locally: nextUrl is built
   * from the address the server is listening on, not from Host — a request with
   * `Host: options.imprevista.com` still produced a redirect to
   * `http://127.0.0.1:3111/login`. Redirecting a real user to the container's
   * internal address is a broken login, so no redirect below may be built from
   * nextUrl's host.
   *
   * Trusting Host is sound here specifically because Traefik is the only path to
   * this container: it routes on Host(`options.imprevista.com`), and the
   * container publishes no host port (verified `docker port` → 3000/tcp with no
   * host binding). If that ever changes, this needs a Host allowlist.
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

  /*
   * A valid signature is not enough — the account must still exist. Without this
   * check, deleting AUTH_PASSWORD_DAD from Coolify would not log Dad out: his
   * cookie stays valid for its full 30 days and the only revocation lever would
   * be rotating SESSION_SECRET, which signs everyone out. This makes "remove the
   * env var" a working revocation.
   */
  const stillConfigured =
    session !== null && configuredUsers(process.env).some((u) => u.user === session.user)

  if (!stillConfigured) {
    if (pathname.startsWith('/api/')) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    }
    /*
     * Absolute, and built from the Host header — for the same reason as above.
     * Next's proxy layer parses Location as an absolute URL and throws
     * ERR_INVALID_URL on a relative one, which surfaces as a 500 on every
     * protected page (verified locally before this shipped).
     *
     * `next` is a path only, and login/page.tsx re-validates it against the
     * page's own origin before navigating, so it cannot become an open redirect.
     */
    const scheme = isLoopback ? 'http' : 'https'
    const next = pathname !== '/' ? `?next=${encodeURIComponent(pathname + search)}` : ''
    return NextResponse.redirect(`${scheme}://${host}/login${next}`, 307)
  }

  /*
   * CSRF. SameSite=Lax is scoped to the SITE (eTLD+1 = imprevista.com), not the
   * origin, so every other app on *.imprevista.com counts as same-site and can
   * issue a credentialed cross-origin POST to this one. `request.json()` parses
   * a `text/plain` body just as happily as `application/json`, and text/plain is
   * a CORS "simple" request — no preflight, so the write would land. That is a
   * path to fake trades in a real portfolio.
   *
   * Checking Origin closes it. This runs only for authenticated, state-changing
   * requests: an unauthenticated caller has already been rejected above (so the
   * 401 stays a 401), and CSRF is only a threat against a session that exists.
   *
   * Origin rather than SameSite=Strict deliberately: Strict would also drop the
   * cookie when Dad opens a link to this app from a text message, showing him a
   * login page every time. The Origin check gives the same protection without
   * that cost.
   */
  const method = request.method
  if (method !== 'GET' && method !== 'HEAD' && method !== 'OPTIONS') {
    const origin = request.headers.get('origin')
    const expected = `${isLoopback ? 'http' : 'https'}://${host}`
    if (origin !== expected) {
      return NextResponse.json(
        { error: 'Cross-origin request refused' },
        { status: 403 }
      )
    }
  }

  return NextResponse.next()
}

export const config = {
  /*
   * Everything except Next's own static output and the favicon. Matching broadly
   * and carving out exceptions is the safe direction: a route that is
   * accidentally matched 401s (loud), one that is accidentally missed leaks
   * (silent).
   */
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
}
