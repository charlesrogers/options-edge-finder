import { NextResponse } from 'next/server'
import { SESSION_COOKIE } from '@/lib/auth'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

/*
 * POST, not GET. A GET logout can be fired by any <img> tag on any page Dad
 * happens to open, which is a nuisance rather than a breach, but there is no
 * reason to accept it.
 */
export async function POST() {
  const response = NextResponse.json({ ok: true })
  response.cookies.set(SESSION_COOKIE, '', {
    httpOnly: true,
    secure: true,
    sameSite: 'lax',
    path: '/',
    maxAge: 0,
  })
  return response
}
