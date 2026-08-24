import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/lib/api-client'

export type TrailingStop = {
  active: boolean
  trigger_pct: number | null
  distance_pct: number | null
  highest_price_seen: number | null
}

export type EntryPlan = {
  plan_action: string | null
  valid_new_entry_plan: boolean
  condition_text: string
  entry_zone_low: number | null
  entry_zone_high: number | null
  trigger_price: number | null
  do_not_chase_above: number | null
  preferred_limit_price: number | null
}

export type PositionSnapshot = {
  entry_price: number | null
  entry_time: string | null
  entry_reason: string | null
  size_base: number | null
  size_quote_usdc: number | null
  close_price: number | null
  close_time: string | null
  close_reason: string | null
  realized_pnl: number | null
}

export type TickerThesis = {
  ticker: string
  status: 'open' | 'closed' | 'watching'
  as_of: string | null
  current_price: number | null
  setup_type: string | null
  entry_plan: EntryPlan
  thesis_reasons: string[]
  monitoring_rules: string[]
  must_reject_if: string[]
  judge_confidence: number | null
  judge_decision: string | null
  take_profit_price: number | null
  take_profit_2_price: number | null
  stop_loss_price: number | null
  invalidation_price: number | null
  trailing_stop: TrailingStop
  position: PositionSnapshot | null
  analysis_available: boolean
}

export type ThesisResponse = {
  tickers: TickerThesis[]
  summary: {
    open_count: number
    closed_count: number
    watching_count: number
  }
}

export function useThesisReport() {
  return useQuery({
    queryKey: ['thesis'],
    queryFn: async () => (await apiClient.get<ThesisResponse>('/thesis')).data,
    refetchInterval: 20_000,
  })
}
