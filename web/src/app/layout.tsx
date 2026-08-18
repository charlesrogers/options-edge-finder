import type { Metadata } from 'next'
import { Geist, Geist_Mono } from 'next/font/google'
import { ThemeProvider } from 'next-themes'
import { Nav } from '@/components/nav'
import './globals.css'

const geistSans = Geist({
  variable: '--font-geist-sans',
  subsets: ['latin'],
})

const geistMono = Geist_Mono({
  variable: '--font-geist-mono',
  subsets: ['latin'],
})

export const metadata: Metadata = {
  title: 'Covered Call Copilot',
  // "Never lose money" was not a slogan, it was a claim, and it is false: on the
  // corrected engine 9% of AAPL trades lose and the worst single trade in the
  // window was -$971 (Exp 022). Assignment-avoidance is what the copilot is
  // actually for, and that is what this now says.
  description: 'Covered call sizing and exit alerts for a concentrated, low-basis portfolio. Avoid assignment; keep the shares.',
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <Nav />
          {children}
        </ThemeProvider>
      </body>
    </html>
  )
}
