/*
 * Session auth for a two-person app.
 *
 * Why this and not Supabase Auth: the only thing this app needs to decide is
 * "is this Charles or Dad, or is it a stranger". Supabase Auth brings a users
 * table, email delivery, password-reset flows, a JWT refresh loop and a second
 * source of truth for identity — all of it for two people who will never
 * self-serve a signup. An HMAC-signed cookie is ~120 lines, has no runtime
 * dependency, no network call on the hot path, and fails closed when its secret
 * is missing. Every route already runs server-side, so there is nothing for a
 * client-side auth SDK to do.
 *
 * The rules that matter:
 *   - FAIL CLOSED. An unset SESSION_SECRET denies everyone rather than letting
 *     everyone through. This is the same bug class that made `CRON_SECRET && ...`
 *     silently disable cron auth (see api/cron/health/route.ts).
 *   - The cookie is signed, not encrypted. It carries no secret — just who you
 *     are and when the session dies — and it cannot be forged without the key.
 *   - Everything here is Web Crypto only (global in Node 18+), so the same code
 *     runs in proxy.ts and in the Node route handlers with no duplicate logic.
 */

export const SESSION_COOKIE = 'cc_session'

/** 30 days — Dad should not be asked to log in again on a normal cadence. */
export const SESSION_MAX_AGE_SECONDS = 30 * 24 * 60 * 60

export interface Session {
  /** Which of the two people this is. */
  user: string
  /** Expiry, epoch seconds. */
  exp: number
}

/* ── base64url, Buffer-free so it works on the edge runtime ── */

function bytesToB64Url(bytes: Uint8Array): string {
  let bin = ''
  for (const b of bytes) bin += String.fromCharCode(b)
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function b64UrlToBytes(s: string): Uint8Array {
  const b64 = s.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (s.length % 4)) % 4)
  const bin = atob(b64)
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out
}

/**
 * Constant-time comparison. A normal `===` on a signature leaks, through timing,
 * how many leading bytes an attacker guessed right, which turns forging a cookie
 * into a byte-at-a-time search instead of a 2^256 one.
 */
export function timingSafeEqual(a: string, b: string): boolean {
  const ab = new TextEncoder().encode(a)
  const bb = new TextEncoder().encode(b)
  // Fold the length difference into the result instead of returning early.
  let diff = ab.length ^ bb.length
  const n = Math.max(ab.length, bb.length)
  for (let i = 0; i < n; i++) diff |= (ab[i] ?? 0) ^ (bb[i] ?? 0)
  return diff === 0
}

/* ── signing ── */

async function hmacKey(secret: string): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign']
  )
}

async function sign(payload: string, secret: string): Promise<string> {
  const key = await hmacKey(secret)
  const sig = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(payload))
  return bytesToB64Url(new Uint8Array(sig))
}

/** Build a signed session token. Returns `<payload>.<signature>`, both base64url. */
export async function createSessionToken(user: string, secret: string, now = Date.now()): Promise<string> {
  const session: Session = {
    user,
    exp: Math.floor(now / 1000) + SESSION_MAX_AGE_SECONDS,
  }
  const payload = bytesToB64Url(new TextEncoder().encode(JSON.stringify(session)))
  return `${payload}.${await sign(payload, secret)}`
}

/**
 * Verify a session token. Returns the session, or null for anything wrong:
 * missing secret, malformed token, bad signature, or expired.
 *
 * Never throws — a thrown error inside middleware is an unhandled 500 on every
 * request, which is its own outage.
 */
export async function verifySessionToken(
  token: string | undefined,
  secret: string | undefined,
  now = Date.now()
): Promise<Session | null> {
  if (!secret || !token) return null
  const dot = token.indexOf('.')
  if (dot <= 0) return null
  const payload = token.slice(0, dot)
  const provided = token.slice(dot + 1)

  let expected: string
  try {
    expected = await sign(payload, secret)
  } catch {
    return null
  }
  if (!timingSafeEqual(provided, expected)) return null

  try {
    const session = JSON.parse(new TextDecoder().decode(b64UrlToBytes(payload))) as Session
    if (typeof session.exp !== 'number' || typeof session.user !== 'string') return null
    if (session.exp * 1000 <= now) return null
    return session
  } catch {
    return null
  }
}

/* ── who is allowed in ── */

/**
 * The two accounts, read from server-only env. Passwords are never compared
 * with `===` (see timingSafeEqual) and are never sent to the client.
 *
 * Login is password-only on purpose: the password is the secret, a username is
 * not, and one field is one fewer thing for Dad to get wrong on a phone. The
 * password that matches determines who you are.
 */
export function configuredUsers(env: Record<string, string | undefined>): Array<{ user: string; password: string }> {
  const out: Array<{ user: string; password: string }> = []
  for (const [name, key] of [
    ['charles', 'AUTH_PASSWORD_CHARLES'],
    ['bryan', 'AUTH_PASSWORD_DAD'],
  ] as const) {
    const password = env[key]
    if (password) out.push({ user: name, password })
  }
  return out
}

/**
 * Returns the matching user's name, or null.
 *
 * Checks every configured account even after a match so the work done — and so
 * the time taken — does not depend on which account matched or whether any did.
 */
export function authenticate(
  password: string,
  env: Record<string, string | undefined>
): string | null {
  let matched: string | null = null
  for (const { user, password: expected } of configuredUsers(env)) {
    if (timingSafeEqual(password, expected)) matched = matched ?? user
  }
  return matched
}
