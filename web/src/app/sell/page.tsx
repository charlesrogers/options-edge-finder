import { SellRecommendations } from './sell-recommendations'
import { PaperTradeScorecard } from './paper-trade-scorecard'

export const dynamic = 'force-dynamic'

export default function SellPage() {
  return (
    <div className="max-w-7xl mx-auto px-6 py-8 space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Sell a Call</h1>
        <p className="text-[13px] text-muted-foreground mt-1 leading-relaxed">
          Backtested recommendations for your holdings. Sorted by expected P&L.
        </p>
      </div>

      <PaperTradeScorecard />
      <SellRecommendations />
    </div>
  )
}
