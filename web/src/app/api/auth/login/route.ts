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
 * Rate limiting lives in module scope. That is a single-container in-memory
 * counter, which is exactly right here: there is one container, and the thing
 * being defended is two passwords against online guessing, not a distributed
 * credential-stuffing campaign. A Redis dependency for two users would be cost
 * and moving parts bought with nothing.
 *
 * It resets on redeploy. An attacker who can time their guessing to our deploys
 * gets ~10 extra attempts; the fixed delay below is what actually bounds the
 * guess rate.
 */
const WINDOW_MS = 15 * 60 * 1000
const MAX_ATTEMPTS = 10
const attempts = new Map<string, { count: number; resetAt: number }>()

/** Every failure costs the caller this long, so guessing is rate-bound even under the cap. */
const FAILURE_DELAY_MS = 400

function clientKey(request: NextRequest): string {
  // Traefik sets x-forwarded-for. First hop is the real client.
  const xff = request.headers.get('x-forwarded-for')
  if (xff) return xff.split(',')[0].trim()
  return request.headers.get('x-real-ip') ?? 'unknown'
}

function tooManyAttempts(key: string, now: number): boolean {
  const rec = attempts.get(key)
  if (!rec || now > rec.resetAt) return false
  return rec.count >= MAX_ATTEMPTS
}

function recordFailure(key: string, now: number): void {
  const rec = attempts.get(key)
  if (!rec || now > rec.resetAt) {
    attempts.set(key, { count: 1, resetAt: now + WINDOW_MS })
    return
  }
  rec.count += 1
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
    sameSite: 'lax',  // survives a normal link-click into the app; blocks cross-site POSTs
    path: '/',
    maxAge: SESSION_MAX_AGE_SECONDS,
  })
  return response
}
