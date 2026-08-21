import { HealthBoard } from './health-board'

export const dynamic = 'force-dynamic'

/*
 * The paper engine's single decision surface. Three bands, in this order,
 * because that is the order the questions have to be answered in:
 *
 *   1. Engine integrity — can we trust the numbers on this page at all?
 *   2. Strategy health  — the Goldman-auditable table.
 *   3. Pre-registration — what we committed to before the data existed.
 *
 * Band 1 comes first on purpose. A P&L number sitting above a broken collector
 * is worse than no number, because it reads as a result.
 *
 * NOT in proxy.ts's public list, and must never be added to it: arm-level P&L
 * at Dad's size is effectively a holdings disclosure.
 */
export default function PaperEnginePage() {
  return (
    <div className="max-w-7xl mx-auto px-6 py-8 space-y-6">
      <HealthBoard />
    </div>
  )
}
