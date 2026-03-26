import { PositionsList } from './positions-list'
import { TradeHistory } from './trade-history'

export const dynamic = 'force-dynamic'

export default function PositionsPage() {
  return (
    <div className="space-y-6">
      {/* Dynamic headline — PositionsList handles the full experience:
          headline, stat cards, alert feed, empty state */}
      <PositionsList />
      <TradeHistory />
    </div>
  )
}
