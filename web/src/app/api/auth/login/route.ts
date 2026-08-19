import { NextResponse, type NextRequest } from 'next/server'
import {
  SESSION_COOKIE,
  SESSION_MAX_AGE_SECONDS,
  authenticate,
  configuredUsers,
  createSessionToken,
} from '@/lib/auth'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

/*
 * Rate limiting, keyed on the LAST X-Forwarded-For hop.
 *
 * The obvious `xff.split(',')[0]` is wrong and dangerous. Traefik APPENDS the
 * peer address to X-Forwarded-For rather than replacing the header, so the first
 * element is whatever the caller typed. Demonstrated against a real build: 8
 * failed logins with a rotating `X-Forwarded-For: 9.9.9.$i` never tripped the
 * limiter at all, and 12 requests spoofing a victim's address then locked that
 * victim out using their own correct password. Simultaneously bypassable by the
 * attacker and a denial-of-service against the real user.
 *
 * The LAST element is the one the trusted proxy appended, so it cannot be
 * spoofed. It is also correct if a proxy ever *replaces* the header instead of
 * appending — then there is one element and the last is it — so this does not
 * depend on knowing which of the two Traefik does.
 *
 * Keyed rather than global on purpose. A single global counter would be
 * unspoofable too, but it hands any stranger a way to lock Charles and Dad out
 * of the tool for fifteen minutes at a time — and the moment that matters most
 * is exactly when a position needs managing. Per-address, an attacker can only
 * lock out themselves.
 */
const WINDOW_MS = 15 * 60 * 1000
const MAX_ATTEMPTS = 10
/** Hard ceiling on distinct keys, so a rotating source cannot grow this without bound. */
const MAX_TRACKED = 1000
const attempts = new Map<string, { count: number; resetAt: number }>()

/** Every failure costs the caller this long, so guessing is rate-bound even under the cap. */
const FAILURE_DELAY_MS = 400

function clientKey(request: NextRequest): string {
  const xff = request.headers.get('x-forwarded-for')
  if (xff) {
    const hops = xff.split(',').map((h) => h.trim()).filter(Boolean)
    if (hops.length > 0) return hops[hops.length - 1]
  }
  return request.headers.get('x-real-ip') ?? 'direct'
}

/** Drop expired entries. Without this the Map only ever grows. */
function sweep(now: number): void {
  for (const [k, v] of attempts) {
    if (now > v.resetAt) attempts.delete(k)
  }
}

function tooManyAttempts(key: string, now: number): boolean {
  const rec = attempts.get(key)
  if (!rec || now > rec.resetAt) return false
  return rec.count >= MAX_ATTEMPTS
}

function recordFailure(key: string, now: number): void {
  const rec = attempts.get(key)
  if (rec && now <= rec.resetAt) {
    rec.count += 1
    return
  }
  sweep(now)
  // If the sweep did not get us under the ceiling, stop tracking new keys rather
  // than growing memory in a container that has a hard limit.
  if (attempts.size >= MAX_TRACKED) return
  attempts.set(key, { count: 1, resetAt: now + WINDOW_MS })
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

export async function POST(request: NextRequest) {
  const secret = process.env.SESSION_SECRET
  /*
   * Fail closed, loudly. If SESSION_SECRET is missing, nobody can be issued a
   * session — and we say so rather than pretending the password was wrong,
   * because a misconfigured deploy that looks like "wrong password" is how you
   * spend an hour typing the right password.
   */
  if (!secret) {
    return NextResponse.json(
      { error: 'SESSION_SECRET unset — refusing to issue sessions' },
      { status: 500 }
    )
  }
  if (configuredUsers(process.env).length === 0) {
    return NextResponse.json(
      { error: 'No AUTH_PASSWORD_* configured — refusing to issue sessions' },
      { status: 500 }
    )
  }

  const now = Date.now()
  const key = clientKey(request)
  if (tooManyAttempts(key, now)) {
    return NextResponse.json(
      { error: 'Too many attempts. Try again in a few minutes.' },
      { status: 429 }
    )
  }

  let password = ''
  try {
    const body = await request.json()
    password = typeof body?.password === 'string' ? body.password : ''
  } catch {
    password = ''
  }

  const user = password ? authenticate(password, process.env) : null
  if (!user) {
    recordFailure(key, now)
    await sleep(FAILURE_DELAY_MS)
    // Never say which part was wrong, and never echo the attempt back.
    return NextResponse.json({ error: 'Incorrect password.' }, { status: 401 })
  }

  attempts.delete(key)

  const token = await createSessionToken(user, secret, now)
  const response = NextResponse.json({ ok: true, user })
  response.cookies.set(SESSION_COOKIE, token, {
    httpOnly: true,   // no script can read it, so an XSS cannot steal the session
    secure: true,     // middleware redirects http -> https, so this always travels encrypted
    // Lax, not Strict, on purpose: Strict would drop the cookie when Dad opens a
    // link to this app from a text message, showing him a login page every time.
    // Lax alone is NOT enough — it is scoped to the site (imprevista.com), so a
    // sibling subdomain counts as same-site — so proxy.ts additionally requires a
    // matching Origin on every authenticated state-changing request.
    sameSite: 'lax',
    path: '/',
    maxAge: SESSION_MAX_AGE_SECONDS,
  })
  return response
}
