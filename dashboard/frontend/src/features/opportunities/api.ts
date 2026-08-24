import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/lib/api-client'

export type Proximity = {
  score: number
  zone: 'red' | 'orange' | 'green'
  conditions: string[]
}

export type Opportunity = {
  ticker: string
  created_at?: string
  current_price?: number
  decision?: string
  decision_category?: string
  judge?: { decision?: string; confidence?: number; side?: string }
  entry_gate?: { decision?: string; confidence?: number; setup_type?: string }
  trade_plan?: {
    plan_action?: string
    setup_type?: string
    trigger?: string
    stop_loss?: number
    take_profit_1?: number
    take_profit_2?: number
    entry_zone_low?: number
    entry_zone_high?: number
  }
  chart_patterns?: { best_pattern_score?: number; pattern_bias?: string; summary?: string }
  opportunity_score?: number | null
  proximity?: Proximity | null
  reason?: string
  setup_type?: string
}

export type OpportunitiesResponse = {
  opportunities: Opportunity[]
  summary: {
    ticker_count: number
    decision_counts: Record<string, number>
    records_scanned: number
  }
}

export function useOpportunities() {
  return useQuery({
    queryKey: ['opportunities'],
    queryFn: async () => (await apiClient.get<OpportunitiesResponse>('/opportunities/latest')).data,
    refetchInterval: 20_000,
  })
}
