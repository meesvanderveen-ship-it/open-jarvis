import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/lib/api-client'

export type LlmCostGroupStats = {
  calls: number
  estimated_cost_usd: number
  avg_tokens_per_call: number
  no_action_calls: number
  error_calls: number
}

export type LlmTopExpensiveCall = {
  timestamp?: string
  cycle_id?: string
  ticker?: string
  agent?: string
  model?: string
  estimated_cost_usd?: number
  total_tokens?: number
  decision_result?: string
  was_call_necessary?: string
}

export type LlmCostBreakdown = {
  generated_at?: string
  read_only?: boolean
  since?: string
  total_calls: number
  total_estimated_cost_usd: number
  avg_cost_per_call_usd: number
  calls_per_cycle: number
  no_action_calls: number
  no_action_cost_usd: number
  no_action_cost_pct: number
  error_calls: number
  retried_attempts: number
  cache_hit_calls: number
  skipped_due_budget_calls: number
  by_model: Record<string, LlmCostGroupStats>
  by_agent: Record<string, LlmCostGroupStats>
  by_ticker: Record<string, LlmCostGroupStats>
  by_cycle: Record<string, LlmCostGroupStats>
  top_10_expensive_calls: LlmTopExpensiveCall[]
  recommendations: string[]
  [key: string]: unknown
}

export function useLlmCost24h() {
  return useQuery({
    queryKey: ['llm-cost-24h'],
    queryFn: async () => (await apiClient.get<LlmCostBreakdown>('/llm/cost')).data,
    refetchInterval: 30_000,
  })
}

export function useLlmCost7d() {
  return useQuery({
    queryKey: ['llm-cost-7d'],
    queryFn: async () => (await apiClient.get<LlmCostBreakdown>('/llm/cost/7d')).data,
    refetchInterval: 60_000,
  })
}

export type MultiAgentLayer = {
  name: string
  label: string
  is_llm: boolean
  provider?: string
  invoked_from: string
  prompt?: string | null
  skip_conditions: string
}

export type MultiAgentAudit = {
  generated_at?: string
  live_orchestrator?: string
  llm_layer_count: number
  deterministic_layer_count: number
  layers: MultiAgentLayer[]
  findings: { finding: string; severity: string; description: string }[]
  prompt_inventory: {
    prompts: { name: string; length_chars: number }[]
    secrets_in_prompts_conclusion: string
  }
  workflow_efficiency: Record<string, unknown>
  conclusion: {
    multi_agent_system_correctness: string
    active_llm_agents: string[]
    primary_cost_driver: string
    secondary_cost_driver: string
  }
  [key: string]: unknown
}

export function useMultiAgentAudit() {
  return useQuery({
    queryKey: ['multi-agent-prompt-audit'],
    queryFn: async () => (await apiClient.get<MultiAgentAudit>('/llm/multi-agent-audit')).data,
    refetchInterval: 60_000,
  })
}
