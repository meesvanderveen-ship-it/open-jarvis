import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/lib/api-client'

export type PositionRow = {
  ticker: string
  is_open: boolean
  entry_price?: string
  close_price?: string
  close_reason?: string
  invalidation_price?: string
  position_risk_incomplete?: boolean
  d2_plan_status?: string
  d3_exit_status?: string
  last_heartbeat_status?: string
  [key: string]: unknown
}

export type PositionsResponse = {
  positions: PositionRow[]
  summary: {
    total: number
    open_count: number
    open_risk_incomplete_count: number
    open_risk_incomplete_tickers: string[]
    closed_risk_incomplete_count: number
    closed_risk_incomplete_tickers: string[]
  }
}

export type OrderRow = {
  order_key: string
  ticker?: string
  product_id?: string
  side?: string
  status?: string
  is_open: boolean
  client_order_id?: string
  exchange_order_id?: string
  limit_price?: string
  remaining_size?: string
  filled_base?: string
  avg_fill_price?: string
  linked_position_id?: string
  phase?: string
  [key: string]: unknown
}

export type OrdersResponse = {
  orders: OrderRow[]
  summary: {
    total: number
    open_count: number
    open_d3_exit_count: number
    tool_summary?: Record<string, unknown>
  }
}

export function usePositions() {
  return useQuery({
    queryKey: ['positions'],
    queryFn: async () => (await apiClient.get<PositionsResponse>('/positions')).data,
    refetchInterval: 20_000,
  })
}

export function useOrders() {
  return useQuery({
    queryKey: ['orders'],
    queryFn: async () => (await apiClient.get<OrdersResponse>('/orders')).data,
    refetchInterval: 20_000,
  })
}
