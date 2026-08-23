import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/lib/api-client'

// Vorm volgt bot/credential_status.py (status_report) zoals doorgegeven door
// dashboard/backend/services/setup_status.py. Bevat nooit een secret: alleen
// status, uitleg en vormkenmerken zoals sleuteltype en lengte.
export type CredentialStatus = 'ok' | 'missing' | 'invalid' | 'unknown'

export type SystemState =
  | 'READY'
  | 'SETUP_REQUIRED'
  | 'CONFIGURATION_ERROR'
  | 'UNKNOWN'

export type ProviderCheck = {
  provider: string
  status: CredentialStatus
  ok: boolean
  configured: boolean
  summary: string
  detail?: string
  facts?: Record<string, unknown>
}

export type SetupStatusResponse = {
  state: SystemState
  verified_online?: boolean
  detail?: string
  error_output?: string
  providers: Record<string, ProviderCheck>
  read_only?: boolean
  coinbase_calls_enabled?: boolean
}

export function useSetupStatus() {
  return useQuery({
    queryKey: ['setup-status'],
    queryFn: async (): Promise<SetupStatusResponse> => {
      const { data } = await apiClient.get<SetupStatusResponse>('/setup/status')
      return data
    },
    // De configuratie verandert zelden; te vaak pollen zou onnodig een
    // subprocess op de server starten.
    refetchInterval: 60_000,
  })
}
