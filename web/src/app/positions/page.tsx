import { PositionsList } from './positions-list'
import { TradeHistory } from './trade-history'

export const dynamic = 'force-dynamic'

export default function PositionsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-[20px] font-bold">My Positions</h1>
        <p className="text-[12px] text-muted-foreground">
          Real-time alerts for your open covered calls.
        </p>
      </div>

      <PositionsList />

      <TradeHistory />
    </div>
  )
}
