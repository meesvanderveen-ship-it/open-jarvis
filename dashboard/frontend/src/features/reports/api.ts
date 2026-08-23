import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/lib/api-client'

// Vorm volgt dashboard/backend/services/reports.py (list_reports / get_report).
export type ReportSummary = {
  id: string
  name: string
  category: string
  extension: string
  size_bytes: number
  modified_at: number
  is_latest: boolean
}

export type ReportListResponse = {
  reports: ReportSummary[]
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
    queryKey: ['reports', category ?? 'all'],
    queryFn: async (): Promise<ReportListResponse> => {
      const { data } = await apiClient.get<ReportListResponse>('/reports', {
        params: category ? { category } : undefined,
      })
      return data
    },
  })
}

export function useReportDetail(reportId: string | null) {
  return useQuery({
    queryKey: ['report', reportId],
    enabled: Boolean(reportId),
    queryFn: async (): Promise<ReportDetail> => {
      const { data } = await apiClient.get<ReportDetail>(`/reports/${reportId}`)
      return data
    },
    // Een ontbrekend rapport is een normale toestand (nog niet gegenereerd),
    // geen fout om eindeloos opnieuw voor te proberen.
    retry: false,
  })
}
