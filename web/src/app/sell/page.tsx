import { SellRecommendations } from './sell-recommendations'

export const dynamic = 'force-dynamic'

export default function SellPage() {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-[20px] font-bold text-foreground">Sell a Call</h1>
        <p className="text-[13px] text-muted-foreground mt-1">
          Backtested recommendations for your holdings. Sorted by expected P&L.
        </p>
      </div>

      <SellRecommendations />
    </div>
  )
}
