import { PositionsList } from './positions-list'
import { TradeHistory } from './trade-history'

export const dynamic = 'force-dynamic'

export default function PositionsPage() {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-[20px] font-bold text-foreground">My Positions</h1>
        <p className="text-[13px] text-muted-foreground mt-1">
          Real-time copilot alerts for your open covered calls.
        </p>
      </div>

      <PositionsList />

      <TradeHistory />
    </div>
  )
}
