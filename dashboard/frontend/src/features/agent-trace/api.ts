import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/lib/api-client'

export type TraceStep = {
  step: string
  label: string
  status: string
  summary: unknown
}

export type TickerTrace = {
  ticker: string
  decision_created_at?: string | null
  decision?: string | null
  steps: TraceStep[]
  raw_decision_record: unknown
}

export type PromptTemplate = {
  name: string
  purpose: string
  length: number
  text: string
}

export function useTickerTrace(ticker: string | null) {
  return useQuery({
    queryKey: ['agent-trace', ticker],
    queryFn: async () =>
      (await apiClient.get<TickerTrace>('/agents/latest-trace', { params: { ticker } })).data,
    enabled: !!ticker,
  })
}

export function usePrompts() {
  return useQuery({
    queryKey: ['prompts'],
    queryFn: async () => (await apiClient.get<{ prompts: PromptTemplate[] }>('/prompts')).data,
    staleTime: 5 * 60_000,
  })
}
