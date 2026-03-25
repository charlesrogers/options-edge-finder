import { supabase } from '@/lib/supabase'
import type { NextRequest } from 'next/server'

export const dynamic = 'force-dynamic'

export async function DELETE(
  _req: NextRequest,
  ctx: RouteContext<'/api/positions/[id]'>
) {
  const { id } = await ctx.params

  const { error } = await supabase.from('trades').delete().eq('id', id)

  if (error) {
    return Response.json({ error: error.message }, { status: 500 })
  }
  return new Response(null, { status: 204 })
}

export async function PATCH(
  request: NextRequest,
  ctx: RouteContext<'/api/positions/[id]'>
) {
  const { id } = await ctx.params
  const body = await request.json()

  const update: Record<string, unknown> = {}
  if (body.closePrice !== undefined) {
    update.close_price = body.closePrice
    update.status = 'closed'
    update.closed_at = new Date().toISOString()
  }
  if (body.status !== undefined) {
    update.status = body.status
  }

  const { data, error } = await supabase
    .from('trades')
    .update(update)
    .eq('id', id)
    .select()
    .single()

  if (error) {
    return Response.json({ error: error.message }, { status: 500 })
  }
  return Response.json(data)
}
