import { SellRecommendations } from './sell-recommendations'

export const dynamic = 'force-dynamic'

export default function SellPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-[20px] font-bold">Sell a Call</h1>
        <p className="text-[12px] text-muted-foreground mt-1">
          Recommendations based on your holdings and backtested strategies.
        </p>
      </div>

      <SellRecommendations />
    </div>
  )
}
