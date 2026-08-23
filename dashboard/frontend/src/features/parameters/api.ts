import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/lib/api-client'

export type ParameterProposal = {
  parameter: string
  category: string
  current_value: unknown
  proposed_value: unknown
  direction: 'loosen' | 'tighten' | 'keep' | string
  reason?: string
  confidence?: number
  evidence_count?: number
  regimes_seen: string[]
  expected_effect?: {
    expected_reward?: number | null
    good_trade_probability?: number | null
    bad_trade_probability?: number | null
    missed_opportunity_probability?: number | null
  }
  risk_impact?: Record<string, string> | null
  safety_status: 'no_active_proposal' | 'blocked' | 'safe_to_activate' | 'needs_more_evidence'
  apply_status: 'no_active_proposal' | 'blocked' | 'ready_for_review' | 'preview_only'
  rollback_plan: string[]
  source: string
  blockers: string[]
  operator_ack_needed: boolean
  activation_route?: string | null
}

export type ProposalsResponse = {
  generated_at?: string
  proposals: ParameterProposal[]
  product_readiness?: Record<string, boolean>
  product_readiness_blockers?: string[]
  next_operator_action?: string
  proposal_count?: number
  blocked_proposal_count?: number
}

export function useParameterProposals() {
  return useQuery({
    queryKey: ['parameter-proposals'],
    queryFn: async () => (await apiClient.get<ProposalsResponse>('/parameters/proposals')).data,
    refetchInterval: 30_000,
  })
}

// --- Full parameter universe -----------------------------------------------

export type FullParameter = {
  name: string
  category: string
  family: string
  description: string
  owner: string
  safety_class: string
  current_value: unknown
  proposed_value: unknown
  proposed_delta: number | null
  direction: string
  confidence: number | null
  evidence_count: number | null
  active_in_runtime: boolean
  consumed_by_runtime: boolean
  visible_in_approved_profile: boolean
  in_governor_allowlist: boolean
  source: string
  status: string
  activation_route: string
  blockers: string[]
  regimes_seen: string[]
  rollback_note: string
  safety_note: string
  last_updated: string | null
  shadow_evidence_total: number
  shadow_evidence_usable: number
  shadow_sufficient: boolean
  governor_is_watching: boolean
  candidate_profile_value: unknown
}

export type FullProposalsResponse = {
  generated_at?: string | null
  parameters: FullParameter[]
  total_parameters: number
  parameters_with_proposal: number
  parameters_blocked: number
  parameters_no_proposal: number
  parameters_in_governor_allowlist: number
  shadow_evidence_total: number
  shadow_evidence_usable: number
  shadow_sufficient_for_optimization: boolean
}

export function useFullParameterProposals() {
  return useQuery({
    queryKey: ['full-parameter-proposals'],
    queryFn: async () =>
      (await apiClient.get<FullProposalsResponse>('/parameters/proposals/full')).data,
    refetchInterval: 30_000,
  })
}
