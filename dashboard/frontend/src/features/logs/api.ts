import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/lib/api-client'

export type LogFileInfo = { name: string; size_bytes: number; modified_at: number }

export type LogsResponse = {
  available_logs: LogFileInfo[]
  entries: Record<string, unknown>[]
  total_scanned?: number
  truncated?: boolean
}

export function useLogs(params: { type: string | null; ticker?: string; q?: string; limit?: number }) {
  return useQuery({
    queryKey: ['logs', params],
    queryFn: async () =>
      (
        await apiClient.get<LogsResponse>('/logs', {
          params: { type: params.type ?? undefined, ticker: params.ticker || undefined, q: params.q || undefined, limit: params.limit },
        })
      ).data,
  })
}
