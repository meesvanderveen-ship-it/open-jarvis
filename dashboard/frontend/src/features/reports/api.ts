import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/lib/api-client'

export type ReportEntry = {
  id: string
  category: string
  name: string
  extension: string
  size_bytes: number
  modified_at: number
  is_latest: boolean
}

export type ReportDetail = {
  id: string
  name: string
  size_bytes: number
  modified_at: number
  truncated: boolean
  content: unknown
}

export function useReportList(category?: string) {
  return useQuery({
    queryKey: ['reports', category],
    queryFn: async () =>
      (await apiClient.get<{ reports: ReportEntry[] }>('/reports', { params: { category } })).data,
  })
}

export function useReportDetail(id: string | null) {
  return useQuery({
    queryKey: ['report-detail', id],
    queryFn: async () => (await apiClient.get<ReportDetail>(`/reports/${id}`)).data,
    enabled: !!id,
  })
}
