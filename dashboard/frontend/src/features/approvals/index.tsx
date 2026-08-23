import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { StatusBadge, type StatusTone } from '@/components/status-badge'
import { ThemeSwitch } from '@/components/theme-switch'
import { useLiveStatus, usePipelineHealth } from '@/features/overview/api'
import { useParameterProposals } from '@/features/parameters/api'
import { type RiskGuardsResponse, useRiskGuards } from '@/features/risk/api'

type GatedActionArgs = {
  live: ReturnType<typeof useLiveStatus>['data']
  pipeline: ReturnType<typeof usePipelineHealth>['data']
  riskGuards: RiskGuardsResponse | undefined
  blockedProposals?: number
}

type GatedAction = {
  action: string
  risk: 'high' | 'medium'
  ackNeeded: boolean
  currentStatus: (args: GatedActionArgs) => { label: string; tone: StatusTone }
  why: string
}

const GATED_ACTIONS: GatedAction[] = [
  {
    action: 'Restart the trading service',
    risk: 'high',
    ackNeeded: true,
    // Deliberately NOT a blind safe_to_restart->danger mapping: a healthy,
    // actively running bot always reports "not safe to restart" (it's
    // already running) — that's expected, not a danger signal. No restart
    // has actually been requested, so this must not read as an alarm.
    // Reuses the backend's runtime_lock_assessment, the same fix applied to
    // Overview and Risk & Safety, so this card can't regress to the old
    // behavior. Only an inconsistent/stuck service escalates to danger.
    currentStatus: ({ pipeline, riskGuards }) => {
      if (pipeline?.safe_to_restart) {
        return { label: 'would be allowed', tone: 'safe' }
      }
      const assessment = riskGuards?.runtime_lock_assessment
      if (assessment?.status === 'held_by_running_service') {
        return { label: 'not applicable — service already running', tone: 'safe' }
      }
      if (assessment?.status === 'held_possibly_stale') {
        return { label: 'blocked — lock held without a live service to explain it', tone: 'danger' }
      }
      return { label: 'restart not requested', tone: 'info' }
    },
    why: 'A restart can interrupt in-flight order lifecycle handling. This dashboard never restarts anything — restart status is shown for awareness only.',
  },
  {
    action: 'Clear a stale process lock',
    risk: 'high',
    ackNeeded: true,
    currentStatus: ({ live }) => ({
      label: live?.stale_lock_detected ? 'stale lock detected' : 'no stale lock',
      tone: live?.stale_lock_detected ? 'warning' : 'safe',
    }),
    why: 'Clearing a lock while the process is still alive can cause two instances to mutate state concurrently. Read-only display only.',
  },
  {
    action: 'Manually close an open position',
    risk: 'high',
    ackNeeded: true,
    currentStatus: ({ pipeline }) => {
      const n = (pipeline?.positions_risk_incomplete as unknown[] | undefined)?.length ?? 0
      return { label: `${n} risk-incomplete position(s)`, tone: n > 0 ? 'warning' : 'safe' }
    },
    why: 'Manual closes bypass the controlled D3 exit/reduce-only path. This dashboard has no Coinbase write access at all.',
  },
  {
    action: 'Apply a parameter proposal',
    risk: 'medium',
    ackNeeded: true,
    currentStatus: ({ blockedProposals }) => ({
      label: `${blockedProposals ?? 0} blocked proposal(s)`,
      tone: 'info',
    }),
    why: 'Only the existing autonomous_parameter_governor apply path (hash-checked, ACK-gated) may ever write approved_parameter_profile.json. This dashboard never calls it.',
  },
  {
    action: 'Enable market orders / replication',
    risk: 'high',
    ackNeeded: true,
    currentStatus: ({ live }) => ({
      label: live?.market_order_status?.enabled ? 'enabled' : 'disabled',
      tone: live?.market_order_status?.enabled ? 'danger' : 'safe',
    }),
    why: 'Market orders and replication are danger-zone live-trading flags controlled by .env, never by this dashboard.',
  },
]

export function Approvals() {
  const { data: live } = useLiveStatus()
  const { data: pipeline } = usePipelineHealth()
  const { data: riskGuards } = useRiskGuards()
  const { data: proposals } = useParameterProposals()

  return (
    <>
      <Header>
        <Search className='me-auto' />
        <ThemeSwitch />
        <ConfigDrawer />
        <ProfileDropdown />
      </Header>

      <Main>
        <div className='mb-4'>
          <h1 className='text-2xl font-bold tracking-tight'>Manual Approval Panel</h1>
          <p className='text-muted-foreground'>
            Actions that would normally require explicit operator ACK. This is a read-only
            preview — nothing on this page executes anything, now or later without code changes.
          </p>
        </div>

        <div className='grid gap-4 lg:grid-cols-2'>
          {GATED_ACTIONS.map((gated) => {
            const status = gated.currentStatus({
              live,
              pipeline,
              riskGuards,
              blockedProposals: proposals?.blocked_proposal_count,
            })
            return (
              <Card key={gated.action}>
                <CardHeader className='flex flex-row items-center justify-between space-y-0'>
                  <CardTitle className='text-sm font-medium'>{gated.action}</CardTitle>
                  <Badge variant='outline' className={gated.risk === 'high' ? 'border-red-600/30 text-red-600' : 'border-amber-600/30 text-amber-600'}>
                    {gated.risk} risk
                  </Badge>
                </CardHeader>
                <CardContent className='space-y-2 text-sm'>
                  <div className='flex items-center justify-between'>
                    <span className='text-muted-foreground'>Operator ACK needed</span>
                    <span>{gated.ackNeeded ? 'Yes' : 'No'}</span>
                  </div>
                  <div className='flex items-center justify-between'>
                    <span className='text-muted-foreground'>Current status</span>
                    <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
                  </div>
                  <p className='text-xs text-muted-foreground'>{gated.why}</p>
                </CardContent>
              </Card>
            )
          })}
        </div>
      </Main>
    </>
  )
}
