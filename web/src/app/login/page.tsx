'use client'

import { Suspense, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { Button } from '@/components/ui/button'
import { Lock } from 'lucide-react'

/*
 * One field. The password identifies the person, so there is nothing else to
 * type — on a phone that is the difference between "just works" and "which
 * username did I use".
 */

/**
 * Only ever navigate to a path on this origin.
 *
 * Do NOT hand-roll this as a string test. A `startsWith('/')` + `startsWith('//')`
 * check looks airtight and is not: browsers normalise a backslash to a slash in
 * the authority position, and strip raw TAB/LF/CR before parsing. All three of
 * `/\evil.com`, `/<TAB>/evil.com` and `/<LF>/evil.com` pass that test and resolve
 * to https://evil.com/.
 *
 * That is the highest-value open redirect available against this app: send Dad a
 * link on the real domain, he sees the real login page, types the real password,
 * and lands on a clone that asks him to "confirm" it.
 *
 * Resolving against the real origin and comparing origins is the check the URL
 * parser already implements correctly.
 */
function safeNext(raw: string | null): string {
  if (!raw) return '/positions'
  try {
    const url = new URL(raw, window.location.origin)
    if (url.origin !== window.location.origin) return '/positions'
    return url.pathname + url.search
  } catch {
    return '/positions'
  }
}

function LoginForm() {
  const router = useRouter()
  const params = useSearchParams()
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
      })
      if (res.ok) {
        const dest = safeNext(params.get('next'))
        // Full navigation, not router.push — the new cookie has to be attached
        // to a fresh request or the middleware still sees the logged-out state.
        window.location.assign(dest)
        return
      }
      const body = await res.json().catch(() => ({}))
      setError(body?.error ?? 'Could not sign in.')
    } catch {
      setError('Could not reach the server.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="space-y-2">
        <label htmlFor="password" className="block text-[13px] font-medium text-foreground">
          Password
        </label>
        <input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          autoFocus
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full rounded-lg border bg-background px-3 py-2 text-[15px] outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        />
      </div>

      {error && (
        <p role="alert" className="text-[13px] text-destructive">
          {error}
        </p>
      )}

      <Button type="submit" disabled={busy || password.length === 0} className="w-full">
        {busy ? 'Signing in…' : 'Sign in'}
      </Button>
    </form>
  )
}

export default function LoginPage() {
  return (
    <main className="min-h-[80vh] flex items-center justify-center px-6">
      <div className="w-full max-w-sm rounded-xl border bg-card p-6 shadow-sm shadow-black/[0.04]">
        <div className="mb-5 flex items-center gap-2">
          <div className="h-8 w-8 rounded-lg bg-primary flex items-center justify-center">
            <Lock className="h-4 w-4 text-primary-foreground" />
          </div>
          <div>
            <h1 className="text-[15px] font-semibold tracking-tight">Covered Call Copilot</h1>
            <p className="text-[12px] text-muted-foreground">Private. Sign in to continue.</p>
          </div>
        </div>
        <Suspense fallback={null}>
          <LoginForm />
        </Suspense>
      </div>
    </main>
  )
}
