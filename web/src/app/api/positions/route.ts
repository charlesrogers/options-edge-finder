import { supabase } from '@/lib/supabase'

export const dynamic = 'force-dynamic'

export async function GET() {
  const { data, error } = await supabase
    .from('trades')
    .select('*')
    .eq('status', 'open')
    .order('opened_at', { ascending: false })

  if (error) {
    return Response.json({ error: error.message }, { status: 500 })
  }
  return Response.json(data)
}

export async function POST(request: Request) {
  const body = await request.json()

  const { data, error } = await supabase
    .from('trades')
    .insert({
      ticker: body.ticker,
      strike: body.strike,
      expiry: body.expiry,
      sold_price: body.soldPrice,
      contracts: body.contracts ?? 1,
      status: 'open',
      opened_at: new Date().toISOString(),
    })
    .select()
    .single()

  if (error) {
    return Response.json({ error: error.message }, { status: 500 })
  }
  return Response.json(data, { status: 201 })
}
