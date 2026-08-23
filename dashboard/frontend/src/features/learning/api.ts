import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/lib/api-client'

export type LearningStatus = {
  generated_at?: string
  phase?: string
  episode_count?: number
  memory_total?: number
  new_memory_episodes?: number
  river_available?: boolean
  river_backend?: string
  river_dependency_status?: Record<string, unknown>
  product_readiness?: Record<string, boolean>
  product_readiness_blockers?: string[]
  next_operator_action?: string
  proposal_count?: number
  blocked_proposal_count?: number
  learning_data_contract?: {
    coverage?: {
      known_market_regime_pct?: number
      nonempty_feature_state_pct?: number
      observed_nonzero_reward_pct?: number
      parameter_hint_count?: number
    }
    episode_count?: number
    promotion_blockers?: string[]
    source_counts?: Record<string, number>
  }
  regime_evidence?: {
    known_regime_coverage_pct?: number
    known_regime_episode_count?: number
    unknown_or_non_market_regime_episode_count?: number
  }
  stabilization_readiness?: {
    ready?: boolean
    real_blockers?: { blocker: string; category?: string; self_resolves_with_more_live_episodes?: boolean }[]
    next_safe_action?: string
  }
  [key: string]: unknown
}

export function useLearningStatus() {
  return useQuery({
    queryKey: ['learning-status'],
    queryFn: async () => (await apiClient.get<LearningStatus>('/status/learning')).data,
    refetchInterval: 30_000,
  })
}

// --- Adaptive Learning Intelligence (deeper, evidence-tier layer) ---------

export type ParameterEvidence = {
  parameter: string
  category: string
  unit?: string
  loosen_change?: string
  safety_class?: string
  evidence_source: string
  current_value: number | null
  proposed_value: number | null
  direction: 'loosen' | 'tighten' | 'keep' | 'mixed' | 'no_signal' | string
  tier:
    | 'observed_signal'
    | 'shadow_candidate'
    | 'backtest_candidate'
    | 'walk_forward_candidate'
    | 'operator_review_candidate'
    | 'apply_ready_candidate'
    | string
  confidence: number
  proposal_score: number
  evidence_count: number
  loosen_signal_count: number
  tighten_signal_count: number
  keep_signal_count: number
  effect_size: number | null
  regimes_seen: string[]
  tickers_seen: string[]
  regime_coverage_pct: number
  overfit_risk: 'low' | 'medium' | 'high' | string
  overfit_reasons: string[]
  risk_impact: string
  expected_effect: string
  why: string
  why_not_apply_ready: string
  next_data_needed: string
}

export type LearningIntelligence = {
  generated_at?: string
  parameter_evidence: ParameterEvidence[]
  proposal_maturity_funnel: Record<string, number>
  overfit_risk_monitor: { low: number; medium: number; high: number; high_risk_parameters: string[] }
  wait_decision_quality: {
    resolved_wait_like_decisions: number
    correct_count: number
    missed_opportunity_count: number
    wait_decision_quality_pct: number | null
    interpretation: string
  }
  missed_opportunity_learning: {
    missed_opportunity_count: number
    by_ticker: Record<string, number>
    by_setup_type: Record<string, number>
    recent_samples: {
      ticker: string
      created_at: string
      price_change_pct: number | null
      setup_type: string | null
      reason_recorded: string
    }[]
  }
  learning_depth: {
    decision_outcomes_resolved: number
    decision_outcomes_pending: number
    execution_outcomes_count: number
    trade_reflections_count: number
    total_evidence_records: number
    regime_coverage: { coverage_pct: number; distinct_known: number; known_regimes_seen: string[] }
    ticker_coverage: { distinct_known: number; tickers_seen: string[] }
  }
  [key: string]: unknown
}

export function useLearningIntelligence() {
  return useQuery({
    queryKey: ['learning-intelligence'],
    queryFn: async () => (await apiClient.get<LearningIntelligence>('/learning/intelligence')).data,
    refetchInterval: 30_000,
  })
}

// --- Parameter Proposal Funnel --------------------------------------------

export type ParameterProposalFunnelRow = {
  parameter: string
  category: string
  direction: string
  confidence: number
  proposal_score: number
  evidence_count: number
  overfit_risk: string
  regimes_seen: string[]
  tickers_seen: string[]
  why_no_proposal: string
}

export type ParameterProposalFunnel = {
  generated_at?: string
  tier_order: string[]
  funnel: Record<string, ParameterProposalFunnelRow[]>
  funnel_counts: Record<string, number>
  total_parameters: number
  apply_ready_policy: string
}

export function useParameterProposalFunnel() {
  return useQuery({
    queryKey: ['parameter-proposal-funnel'],
    queryFn: async () =>
      (await apiClient.get<ParameterProposalFunnel>('/parameters/proposal-funnel')).data,
    refetchInterval: 30_000,
  })
}

// --- Shadow Outcome Accelerator -------------------------------------------

export type ShadowEvaluationSlot = {
  status?: string
  evidence_quality?: string
  evidence_usable?: boolean
  price_move_pct?: number | null
  bad_trade_avoided_label?: string | null
  missed_opportunity_label?: string | null
} | null

export type ShadowRecentRecord = {
  shadow_id?: string
  ticker?: string
  timestamp?: string
  decision?: string
  status?: string
  market_regime?: string
  setup_type?: string | null
  bull_score?: number | null
  bear_score?: number | null
  synth_confidence?: number | null
  mid_price?: number | null
  evaluations?: Record<string, ShadowEvaluationSlot>
  due_at?: Record<string, string>
}

export type ShadowOutcomesStatus = {
  generated_at?: string | null
  schema_version?: string
  total_shadow_decisions: number
  status_counts: Record<string, number>
  evaluations_by_horizon: Record<string, { pending: number; complete: number; insufficient_data: number }>
  usable_evidence_count: number
  evidence_quality_score: number
  by_ticker: Record<string, number>
  by_regime: Record<string, number>
  top_missed_opportunity_patterns: { setup_type: string; count: number }[]
  top_bad_trade_avoided_patterns: { decision: string; count: number }[]
  quality_distribution: Record<string, number>
  sufficient_for_optimization: boolean
  sufficiency_note: string
  learning_policy: string
  no_live_orders: boolean
  no_coinbase_calls: boolean
  no_parameter_mutation: boolean
  source?: string
}

export type ShadowOutcomesRecent = {
  total_records: number
  returned: number
  limit: number
  records: ShadowRecentRecord[]
}

export function useShadowOutcomesStatus() {
  return useQuery({
    queryKey: ['shadow-outcomes-status'],
    queryFn: async () =>
      (await apiClient.get<ShadowOutcomesStatus>('/shadow-outcomes/status')).data,
    refetchInterval: 30_000,
  })
}

export function useShadowOutcomesRecent(limit = 10) {
  return useQuery({
    queryKey: ['shadow-outcomes-recent', limit],
    queryFn: async () =>
      (await apiClient.get<ShadowOutcomesRecent>(`/shadow-outcomes/recent?limit=${limit}`)).data,
    refetchInterval: 30_000,
  })
}
