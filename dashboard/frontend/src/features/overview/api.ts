import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/lib/api-client'

// These response shapes mirror tools/show_autonomous_live_run_status.py and
// tools/show_full_pipeline_health.py --json output. Both are large,
// free-form, and evolve on the bot side, so we type only the fields this
// screen renders and leave the rest as unknown passthrough.
export type LiveStatus = {
  generated_at?: string
  mode?: string
  run_health?: string
  systemd_service_status?: string
  service_detectable?: boolean
  systemd_pid?: string
  lock_pid?: string
  active_pid?: string
  pid_consistent?: boolean
  stale_lock_detected?: boolean
  read_only?: boolean
  last_full_cycle_time?: string
  last_heartbeat_time?: string
  last_gate_summary?: Record<string, number>
  last_cycle_summary?: Record<string, number>
  open_orders_summary?: Record<string, unknown>
  open_d3_exit_summary?: { count?: number; samples?: unknown[] }
  errors_by_type?: Record<string, number>
  recent_runtime_errors?: unknown[]
  replication_status?: Record<string, unknown>
  market_order_status?: { enabled?: boolean } & Record<string, unknown>
  approved_profile_status?: { hash_valid?: boolean; loaded?: boolean; enabled?: boolean }
  latest_readiness_recommendation?: string
  [key: string]: unknown
}

export type PipelineHealth = {
  generated_at?: string
  phase?: string
  pipeline_health?: string
  do_not_run_bot_yet?: boolean
  safe_to_restart?: boolean
  open_orders?: number
  open_positions?: number
  blockers?: string[]
  operator_action?: string
  operator_checklist?: string[]
  configured_tickers?: string[]
  eligible_tickers?: string[]
  [key: string]: unknown
}

export type TickerHighlight = {
  ticker: string
  decision: string
  reason: string
}

export type RunSummary = {
  generated_at?: string
  cycle_id?: string | null
  cycle_type?: 'full' | 'heartbeat' | 'unknown'
  overall_decision?: string
  market_regime?: string
  summary_lines: string[]
  ticker_highlights: TickerHighlight[]
  notable_guards: string[]
  learning_notes: string[]
  operator_takeaway?: string
}

export function useRunSummary() {
  return useQuery({
    queryKey: ['run-summary'],
    queryFn: async () => (await apiClient.get<RunSummary>('/status/run-summary')).data,
    refetchInterval: 30_000,
  })
}

export function useLiveStatus() {
  return useQuery({
    queryKey: ['status-live'],
    queryFn: async () => (await apiClient.get<LiveStatus>('/status/live')).data,
    refetchInterval: 15_000,
  })
}

export function usePipelineHealth() {
  return useQuery({
    queryKey: ['status-pipeline'],
    queryFn: async () => (await apiClient.get<PipelineHealth>('/status/pipeline')).data,
    refetchInterval: 15_000,
  })
}

export type TrackedTickers = {
  allowed_tickers: string[]
}

// Sourced from state/runtime_ticker_universe.json, written by the actually
// running bot process at startup -- reflects what that process has loaded in
// memory right now, not a fresh re-read of .env (which could differ if .env
// changed since the last restart).
export function useTrackedTickers() {
  return useQuery({
    queryKey: ['status-tickers'],
    queryFn: async () => (await apiClient.get<TrackedTickers>('/status/tickers')).data,
    refetchInterval: 30_000,
  })
}
