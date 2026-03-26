import { HoldingsEditor } from './holdings-editor'
import { PositionsList } from './positions-list'
import { TradeHistory } from './trade-history'

export const dynamic = 'force-dynamic'

export default function PositionsPage() {
  return (
    <div className="max-w-7xl mx-auto px-6 py-8 space-y-6">
      <HoldingsEditor />
      <PositionsList />
      <TradeHistory />
    </div>
  )
}
