'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { cn } from '@/lib/utils'

const links = [
  { href: '/positions', label: 'My Positions' },
  { href: '/sell', label: 'Sell a Call' },
  { href: '/how-it-works', label: 'How It Works' },
]

export function Nav() {
  const pathname = usePathname()

  return (
    <header className="sticky top-0 z-50 border-b bg-white/80 dark:bg-neutral-900/80 backdrop-blur-lg">
      <div className="mx-auto flex h-12 max-w-7xl items-center gap-1 px-4">
        <Link
          href="/positions"
          className="mr-4 text-[15px] font-semibold text-foreground"
        >
          Covered Call Copilot
        </Link>

        <nav className="flex items-center gap-0.5">
          {links.map(({ href, label }) => {
            const isActive = pathname.startsWith(href)
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  'rounded-lg px-3 py-1.5 text-[13px] font-medium transition-colors',
                  isActive
                    ? 'bg-primary/8 text-primary'
                    : 'text-muted-foreground hover:bg-accent hover:text-foreground'
                )}
              >
                {label}
              </Link>
            )
          })}
        </nav>
      </div>
    </header>
  )
}
