import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/lib/api-client'

export type GuardRow = {
  guard: string
  category: string
  value: unknown
  status: 'safe' | 'warning' | 'danger' | 'info'
  source: string
  note?: string
}

export type AnnotatedBlocker = {
  blocker: string
  tone: 'safe' | 'warning' | 'danger' | 'info'
  detail: string
}

export type RuntimeLockAssessment = {
  status: 'held_by_running_service' | 'held_possibly_stale' | 'unverifiable' | 'not_held'
  tone: 'safe' | 'warning' | 'danger' | 'info'
  detail: string
  path?: string
}

export type OperationalHealth = {
  tone: 'safe' | 'warning' | 'danger' | 'info'
  reasons: string[]
}

export type RiskGuardsResponse = {
  guards: GuardRow[]
  danger_count: number
  operational_health: OperationalHealth
  pipeline_health?: string
  blockers: string[]
  annotated_blockers: AnnotatedBlocker[]
  runtime_lock_assessment: RuntimeLockAssessment
  operator_checklist: string[]
  operator_action?: string
  readiness?: Record<string, unknown>
  latest_readiness_recommendation?: string
  market_order_flags_enabled?: string[]
  replication_status?: Record<string, unknown>
}

export function useRiskGuards() {
  return useQuery({
    queryKey: ['risk-guards'],
    queryFn: async () => (await apiClient.get<RiskGuardsResponse>('/risk/guards')).data,
    refetchInterval: 20_000,
  })
}
