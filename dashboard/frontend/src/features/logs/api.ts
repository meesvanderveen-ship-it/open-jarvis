import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/lib/api-client'

export type LogEntry = Record<string, unknown>

export type LogsResponse = {
  available_logs: string[]
  entries: LogEntry[]
  truncated?: boolean
  [key: string]: unknown
}

export type LogQuery = {
  type?: string | null
  ticker?: string
  q?: string
  limit?: number
}

export function useLogs({ type, ticker, q, limit = 100 }: LogQuery) {
  return useQuery({
    queryKey: ['logs', type ?? 'none', ticker ?? '', q ?? '', limit],
    queryFn: async (): Promise<LogsResponse> => {
      const { data } = await apiClient.get<LogsResponse>('/logs', {
        params: {
          ...(type ? { type } : {}),
          ...(ticker ? { ticker } : {}),
          ...(q ? { q } : {}),
          limit,
        },
      })
      return data
    },
  })
}
