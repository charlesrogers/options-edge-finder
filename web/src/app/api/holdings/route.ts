import { supabase } from '@/lib/supabase'

export const dynamic = 'force-dynamic'

export async function GET() {
  const { data, error } = await supabase
    .from('portfolio_holdings')
    .select('*')
    .order('ticker', { ascending: true })

  if (error) {
    return Response.json({ error: error.message }, { status: 500 })
  }
  return Response.json(data)
}

export async function POST(request: Request) {
  const body = await request.json()

  // Upsert by ticker
  const { data, error } = await supabase
    .from('portfolio_holdings')
    .upsert(
      {
        ticker: body.ticker,
        shares: body.shares,
        cost_basis: body.costBasis ?? null,
        updated_at: new Date().toISOString(),
      },
      { onConflict: 'ticker' }
    )
    .select()
    .single()

  if (error) {
    return Response.json({ error: error.message }, { status: 500 })
  }
  return Response.json(data, { status: 201 })
}
