/*
 * Auth primitives, exercised against the real Web Crypto implementation.
 *
 * These are financial-access-control decisions — a wrong comparison here is the
 * difference between "only Charles and Dad" and "anyone". They run in CI
 * (test.yml) with no network and no database.
 *
 * Run: node web/scripts/check_auth.mjs
 */
import assert from 'node:assert/strict'
import {
  timingSafeEqual,
  createSessionToken,
  verifySessionToken,
  authenticate,
  configuredUsers,
  SESSION_MAX_AGE_SECONDS,
} from '../src/lib/auth.ts'

/*
 * Imported straight from the TypeScript source via Node's native type
 * stripping, so this exercises the exact code the middleware runs — not a
 * transpiled copy that could drift from it.
 */
const A = {
  timingSafeEqual,
  createSessionToken,
  verifySessionToken,
  authenticate,
  configuredUsers,
  SESSION_MAX_AGE_SECONDS,
}

let failures = 0
async function check(name, fn) {
  try {
    await fn()
    console.log(`  ok    ${name}`)
  } catch (err) {
    failures++
    console.log(`  FAIL  ${name}\n        ${err.message}`)
  }
}

console.log('auth primitives')

const SECRET = 'test-secret-not-a-real-one'

await check('timingSafeEqual: equal strings match', () => {
  assert.equal(A.timingSafeEqual('hunter2', 'hunter2'), true)
})
await check('timingSafeEqual: different strings do not match', () => {
  assert.equal(A.timingSafeEqual('hunter2', 'hunter3'), false)
})
await check('timingSafeEqual: a prefix is not a match (length is folded in)', () => {
  assert.equal(A.timingSafeEqual('hunter', 'hunter2'), false)
  assert.equal(A.timingSafeEqual('hunter2', 'hunter'), false)
})
await check('timingSafeEqual: empty vs empty matches, empty vs value does not', () => {
  assert.equal(A.timingSafeEqual('', ''), true)
  assert.equal(A.timingSafeEqual('', 'x'), false)
})

await check('round trip: a freshly signed token verifies', async () => {
  const t = await A.createSessionToken('charles', SECRET)
  const s = await A.verifySessionToken(t, SECRET)
  assert.equal(s.user, 'charles')
})

await check('a token signed with another secret is rejected', async () => {
  const t = await A.createSessionToken('charles', 'other-secret')
  assert.equal(await A.verifySessionToken(t, SECRET), null)
})

await check('tampering with the payload invalidates the signature', async () => {
  const t = await A.createSessionToken('bryan', SECRET)
  const [payload, sig] = t.split('.')
  // Re-encode the payload as charles, keep dad's signature.
  const forged = Buffer.from(JSON.stringify({ user: 'charles', exp: 4102444800 }))
    .toString('base64url')
  assert.equal(await A.verifySessionToken(`${forged}.${sig}`, SECRET), null)
  // sanity: the untampered one still works
  assert.ok(await A.verifySessionToken(`${payload}.${sig}`, SECRET))
})

await check('an expired token is rejected', async () => {
  const t = await A.createSessionToken('charles', SECRET, Date.now())
  const wayLater = Date.now() + (A.SESSION_MAX_AGE_SECONDS + 60) * 1000
  assert.equal(await A.verifySessionToken(t, SECRET, wayLater), null)
})

await check('a token one minute before expiry is still accepted', async () => {
  const t = await A.createSessionToken('charles', SECRET, Date.now())
  const justBefore = Date.now() + (A.SESSION_MAX_AGE_SECONDS - 60) * 1000
  assert.ok(await A.verifySessionToken(t, SECRET, justBefore))
})

await check('FAIL CLOSED: no secret means no valid session, ever', async () => {
  const t = await A.createSessionToken('charles', SECRET)
  assert.equal(await A.verifySessionToken(t, undefined), null)
  assert.equal(await A.verifySessionToken(t, ''), null)
})

await check('garbage tokens are rejected without throwing', async () => {
  for (const bad of ['', 'nodot', '.', 'a.b', '...', 'x'.repeat(500)]) {
    assert.equal(await A.verifySessionToken(bad, SECRET), null, `token: ${JSON.stringify(bad)}`)
  }
  assert.equal(await A.verifySessionToken(undefined, SECRET), null)
})

console.log('password matching')

const ENV = { AUTH_PASSWORD_CHARLES: 'charles-pw', AUTH_PASSWORD_DAD: 'dad-pw' }

await check('the right password identifies the right person', () => {
  assert.equal(A.authenticate('charles-pw', ENV), 'charles')
  assert.equal(A.authenticate('dad-pw', ENV), 'bryan')
})
await check('a wrong password matches nobody', () => {
  assert.equal(A.authenticate('nope', ENV), null)
  assert.equal(A.authenticate('', ENV), null)
  assert.equal(A.authenticate('charles-p', ENV), null)
  assert.equal(A.authenticate('charles-pww', ENV), null)
})
await check('FAIL CLOSED: with no passwords configured, nothing authenticates', () => {
  assert.equal(A.configuredUsers({}).length, 0)
  assert.equal(A.authenticate('anything', {}), null)
  // Critically: the empty string must not match an unset variable.
  assert.equal(A.authenticate('', {}), null)
})
await check('an unset account cannot be logged into with an empty password', () => {
  const partial = { AUTH_PASSWORD_CHARLES: 'charles-pw' }
  assert.equal(A.configuredUsers(partial).length, 1)
  assert.equal(A.authenticate('', partial), null)
  assert.equal(A.authenticate('dad-pw', partial), null)
})


console.log('open-redirect protection (safeNext algorithm)')

/*
 * safeNext lives in a client component and depends on window.location, so the
 * algorithm is restated here against a fixed origin. These are the exact inputs
 * that defeated the previous string-prefix implementation: a browser normalises
 * a backslash to a slash in the authority position and strips raw TAB/LF/CR
 * before parsing, so all three of these resolved to https://evil.com/.
 */
const ORIGIN = 'https://options.imprevista.com'
function safeNext(raw) {
  if (!raw) return '/positions'
  try {
    const u = new URL(raw, ORIGIN)
    if (u.origin !== ORIGIN) return '/positions'
    return u.pathname + u.search
  } catch {
    return '/positions'
  }
}

await check('rejects protocol-relative //evil.com', () => {
  assert.equal(safeNext('//evil.com'), '/positions')
})
await check('rejects backslash authority /\\evil.com', () => {
  assert.equal(safeNext('/\\evil.com'), '/positions')
})
await check('rejects embedded TAB  /\t/evil.com', () => {
  assert.equal(safeNext('/\t/evil.com'), '/positions')
})
await check('rejects embedded LF   /\n/evil.com', () => {
  assert.equal(safeNext('/\n/evil.com'), '/positions')
})
await check('rejects embedded CR   /\r/evil.com', () => {
  assert.equal(safeNext('/\r/evil.com'), '/positions')
})
await check('rejects absolute http(s) to another host', () => {
  assert.equal(safeNext('https://evil.com/x'), '/positions')
  assert.equal(safeNext('http://evil.com/x'), '/positions')
})
await check('rejects javascript: and data:', () => {
  assert.equal(safeNext('javascript:alert(1)'), '/positions')
  assert.equal(safeNext('data:text/html,<script>alert(1)</script>'), '/positions')
})
await check('allows genuine same-origin paths, preserving the query', () => {
  assert.equal(safeNext('/positions'), '/positions')
  assert.equal(safeNext('/sell?ticker=AAPL'), '/sell?ticker=AAPL')
})
await check('an absolute URL on OUR origin is reduced to its path', () => {
  assert.equal(safeNext(ORIGIN + '/positions'), '/positions')
})

console.log(failures === 0 ? '\nall auth checks passed' : `\n${failures} auth check(s) FAILED`)
process.exit(failures === 0 ? 0 : 1)
