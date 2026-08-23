import { useState } from 'react'
import { formatDistanceToNow } from 'date-fns'
import { AlertTriangle, ChevronDown, Info, RefreshCcw } from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Skeleton } from '@/components/ui/skeleton'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { StatusBadge, type StatusTone } from '@/components/status-badge'
import { ThemeSwitch } from '@/components/theme-switch'
import { useRiskGuards } from '@/features/risk/api'
import { useLiveStatus, usePipelineHealth, useRunSummary } from './api'

const DECISION_TONE: Record<string, StatusTone> = {
  approve_trade: 'safe',
  wait: 'info',
  reject: 'warning',
  reduce_size: 'warning',
  close_position: 'warning',
  no_decisions_recorded: 'info',
}

const VISIBLE_SUMMARY_LINES = 12

function toneFromWord(value: unknown): StatusTone {
  if (typeof value !== 'string') return 'info'
  const v = value.toLowerCase()
  if (['green', 'ok', 'safe', 'active/running', 'active'].some((w) => v.includes(w))) return 'safe'
  if (['yellow', 'warning', 'degraded'].some((w) => v.includes(w))) return 'warning'
  if (['red', 'critical', 'danger', 'failed', 'inactive'].some((w) => v.includes(w))) return 'danger'
  return 'info'
}

const RUNTIME_LOCK_LABELS: Record<string, string> = {
  held_by_running_service: 'held (expected — bot is running)',
  held_possibly_stale: 'held — no live service to explain it',
  unverifiable: 'could not verify',
  not_held: 'free',
}

function safeTimeAgo(iso: string | undefined): string {
  if (!iso) return 'unknown'
  try {
    return formatDistanceToNow(new Date(iso), { addSuffix: true })
  } catch {
    return iso
  }
}

export function Overview() {
  const live = useLiveStatus()
  const pipeline = usePipelineHealth()
  const riskGuards = useRiskGuards()
  const runSummary = useRunSummary()
  const [showFullSummary, setShowFullSummary] = useState(false)

  const isLoading = live.isLoading || pipeline.isLoading || riskGuards.isLoading
  const isError = live.isError || pipeline.isError || riskGuards.isError

  // Deliberately NOT derived from pipeline.data?.pipeline_health: that field
  // (and do_not_run_bot_yet/safe_to_restart/blockers) answers "is it safe to
  // restart/do maintenance right now", which a healthy, actively running bot
  // will always answer "no" to — it's not a general health signal. The
  // overall badge uses the backend's operational_health instead, which is
  // computed independently of restart-readiness. See risk_guards.py.
  const overallTone: StatusTone = riskGuards.data?.operational_health.tone ?? 'info'

  const overallLabel: Record<StatusTone, string> = {
    safe: 'Safe',
    warning: 'Warning',
    danger: 'Critical',
    info: 'Unknown',
  }

  return (
    <>
      <Header>
        <Search className='me-auto' />
        <ThemeSwitch />
        <ConfigDrawer />
        <ProfileDropdown />
      </Header>

      <Main>
        <div className='mb-4 flex flex-wrap items-center justify-between gap-2'>
          <div>
            <h1 className='text-2xl font-bold tracking-tight'>
              Live Status Cockpit
            </h1>
            <p className='text-muted-foreground'>
              At-a-glance: is the bot running safely right now?
            </p>
          </div>
          <div className='flex items-center gap-2'>
            <StatusBadge tone={overallTone} className='px-3 py-1 text-sm font-medium'>
              {overallLabel[overallTone]}
            </StatusBadge>
            <Button
              variant='outline'
              size='sm'
              onClick={() => {
                live.refetch()
                pipeline.refetch()
                riskGuards.refetch()
                runSummary.refetch()
              }}
            >
              <RefreshCcw className='size-3.5' />
              Refresh
            </Button>
          </div>
        </div>

        {isError && (
          <Alert variant='destructive' className='mb-4'>
            <AlertTriangle className='size-4' />
            <AlertTitle>Could not load status</AlertTitle>
            <AlertDescription>
              One of the status tools failed to run or returned an error. The
              bot itself may still be fine — this only means the dashboard
              backend could not read its status just now.
            </AlertDescription>
          </Alert>
        )}

        {(() => {
          const blockers = riskGuards.data?.annotated_blockers ?? []
          if (blockers.length === 0) return null
          const real = blockers.filter((b) => b.tone === 'danger' || b.tone === 'warning')
          const informational = blockers.filter((b) => b.tone === 'safe' || b.tone === 'info')
          return (
            <>
              {real.length > 0 && (
                <Alert
                  variant={real.some((b) => b.tone === 'danger') ? 'destructive' : 'default'}
                  className='mb-4 border-amber-600/40'
                >
                  <AlertTriangle className='size-4' />
                  <AlertTitle>Restart/maintenance blockers — needs review</AlertTitle>
                  <AlertDescription>
                    <ul className='list-inside list-disc'>
                      {real.map((b) => (
                        <li key={b.blocker}>
                          <span className='font-mono text-xs'>{b.blocker}</span> — {b.detail}
                        </li>
                      ))}
                    </ul>
                  </AlertDescription>
                </Alert>
              )}
              {informational.length > 0 && (
                <Alert className='mb-4 border-blue-600/30'>
                  <Info className='size-4' />
                  <AlertTitle>
                    Maintenance/restart note — not a trading risk
                  </AlertTitle>
                  <AlertDescription>
                    <p className='mb-1'>
                      This is about whether a server-side restart or maintenance
                      action would currently be safe to run — it has no bearing on
                      trading risk, and does not affect the Safe/Warning/Critical
                      status above.
                    </p>
                    <ul className='list-inside list-disc'>
                      {informational.map((b) => (
                        <li key={b.blocker}>
                          <span className='font-mono text-xs'>{b.blocker}</span> — {b.detail}
                        </li>
                      ))}
                    </ul>
                  </AlertDescription>
                </Alert>
              )}
            </>
          )
        })()}

        {isLoading ? (
          <div className='grid gap-4 sm:grid-cols-2 lg:grid-cols-3'>
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className='h-32' />
            ))}
          </div>
        ) : (
          <div className='grid gap-4 sm:grid-cols-2 lg:grid-cols-3'>
            <Card>
              <CardHeader>
                <CardTitle className='text-sm font-medium'>
                  Service & process
                </CardTitle>
              </CardHeader>
              <CardContent className='space-y-2 text-sm'>
                <Row label='systemd'>
                  <StatusBadge tone={toneFromWord(live.data?.systemd_service_status)}>
                    {live.data?.systemd_service_status ?? 'unknown'}
                  </StatusBadge>
                </Row>
                <Row label='run health'>
                  <StatusBadge tone={toneFromWord(live.data?.run_health)}>
                    {live.data?.run_health ?? 'unknown'}
                  </StatusBadge>
                </Row>
                <Row label='mode'>
                  <span className='font-mono text-xs'>{live.data?.mode ?? '—'}</span>
                </Row>
                <Row label='PID consistent'>
                  <StatusBadge tone={live.data?.pid_consistent ? 'safe' : 'danger'}>
                    {String(live.data?.pid_consistent ?? 'unknown')}
                  </StatusBadge>
                </Row>
                <Row label='stale lock'>
                  <StatusBadge tone={live.data?.stale_lock_detected ? 'danger' : 'safe'}>
                    {String(live.data?.stale_lock_detected ?? 'unknown')}
                  </StatusBadge>
                </Row>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className='text-sm font-medium'>Exposure</CardTitle>
              </CardHeader>
              <CardContent className='space-y-2 text-sm'>
                <Row label='open orders'>
                  <span className='font-semibold'>{pipeline.data?.open_orders ?? '—'}</span>
                </Row>
                <Row label='open positions'>
                  <span className='font-semibold'>{pipeline.data?.open_positions ?? '—'}</span>
                </Row>
                <Row label='open D3 exits'>
                  <span className='font-semibold'>
                    {live.data?.open_d3_exit_summary?.count ?? '—'}
                  </span>
                </Row>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className='text-sm font-medium'>Cycle timing</CardTitle>
              </CardHeader>
              <CardContent className='space-y-2 text-sm'>
                <Row label='last full cycle'>
                  <span>{safeTimeAgo(live.data?.last_full_cycle_time)}</span>
                </Row>
                <Row label='last heartbeat'>
                  <span>{safeTimeAgo(live.data?.last_heartbeat_time)}</span>
                </Row>
                <Row label='readiness'>
                  <span className='text-end text-xs text-muted-foreground'>
                    {live.data?.latest_readiness_recommendation ?? '—'}
                  </span>
                </Row>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className='text-sm font-medium'>Errors & warnings</CardTitle>
              </CardHeader>
              <CardContent className='space-y-2 text-sm'>
                {live.data?.errors_by_type && Object.keys(live.data.errors_by_type).length > 0 ? (
                  Object.entries(live.data.errors_by_type).map(([type, count]) => (
                    <Row key={type} label={type}>
                      <Badge variant='destructive'>{count}</Badge>
                    </Row>
                  ))
                ) : (
                  <p className='text-muted-foreground'>No errors recorded.</p>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className='text-sm font-medium'>
                  Replication & market orders
                </CardTitle>
              </CardHeader>
              <CardContent className='space-y-2 text-sm'>
                <Row label='market orders'>
                  <StatusBadge tone={live.data?.market_order_status?.enabled ? 'danger' : 'safe'}>
                    {String(live.data?.market_order_status?.enabled ?? 'unknown')}
                  </StatusBadge>
                </Row>
                <Row label='replication'>
                  <span className='font-mono text-xs'>
                    {String(
                      (live.data?.replication_status as Record<string, unknown> | undefined)
                        ?.follower_mode ?? 'unknown'
                    )}
                  </span>
                </Row>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className='text-sm font-medium'>Approved profile</CardTitle>
              </CardHeader>
              <CardContent className='space-y-2 text-sm'>
                <Row label='hash valid'>
                  <StatusBadge tone={live.data?.approved_profile_status?.hash_valid ? 'safe' : 'danger'}>
                    {String(live.data?.approved_profile_status?.hash_valid ?? 'unknown')}
                  </StatusBadge>
                </Row>
                <Row label='loaded'>
                  <span>{String(live.data?.approved_profile_status?.loaded ?? 'unknown')}</span>
                </Row>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className='text-sm font-medium'>
                  Restart & maintenance readiness
                </CardTitle>
              </CardHeader>
              <CardContent className='space-y-2 text-sm'>
                <p className='text-xs text-muted-foreground'>
                  Different question from overall health, and not a trading risk:
                  is it safe to restart or do maintenance right now? A healthy,
                  running bot normally says "no" here, simply because it's busy.
                </p>
                <Row label='runtime lock'>
                  <StatusBadge tone={riskGuards.data?.runtime_lock_assessment.tone ?? 'info'}>
                    {riskGuards.data?.runtime_lock_assessment.status
                      ? RUNTIME_LOCK_LABELS[riskGuards.data.runtime_lock_assessment.status] ??
                        riskGuards.data.runtime_lock_assessment.status
                      : 'unknown'}
                  </StatusBadge>
                </Row>
                <Row label='safe to restart'>
                  <span>{String(pipeline.data?.safe_to_restart ?? 'unknown')}</span>
                </Row>
              </CardContent>
            </Card>
          </div>
        )}

        {!isLoading && live.data?.last_cycle_summary && (
          <Card className='mt-4'>
            <CardHeader>
              <CardTitle className='text-sm font-medium'>
                Last full cycle — decision breakdown
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className='flex flex-wrap gap-4 text-sm'>
                {Object.entries(live.data.last_cycle_summary).map(([key, value]) => (
                  <div key={key} className='flex flex-col items-center rounded-md border px-3 py-2'>
                    <span className='text-xs text-muted-foreground'>{key}</span>
                    <span className='text-lg font-semibold'>{String(value)}</span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        <Card className='mt-4'>
          <CardHeader className='flex flex-row items-center justify-between space-y-0'>
            <div>
              <CardTitle className='text-sm font-medium'>Latest Run Summary</CardTitle>
              <p className='text-xs text-muted-foreground'>
                A deterministic run evidence summary, built from logs and recorded
                decisions — not an LLM call, not a chain of thought.
              </p>
            </div>
            {runSummary.data?.overall_decision && (
              <StatusBadge tone={DECISION_TONE[runSummary.data.overall_decision] ?? 'info'}>
                Overall: {runSummary.data.overall_decision.replace(/_/g, ' ')}
              </StatusBadge>
            )}
          </CardHeader>
          <CardContent className='space-y-3'>
            {runSummary.isLoading ? (
              <Skeleton className='h-48' />
            ) : runSummary.isError ? (
              <p className='text-sm text-muted-foreground'>
                Could not load the run summary tool right now.
              </p>
            ) : runSummary.data ? (
              <>
                <div className='flex flex-wrap items-center gap-2 text-xs text-muted-foreground'>
                  <Badge variant='outline'>{runSummary.data.cycle_type ?? 'unknown'} cycle</Badge>
                  <span>{safeTimeAgo(runSummary.data.cycle_id ?? undefined)}</span>
                  {runSummary.data.market_regime && (
                    <Badge variant='outline'>regime: {runSummary.data.market_regime}</Badge>
                  )}
                </div>

                <p className='text-sm font-medium'>{runSummary.data.operator_takeaway}</p>

                <Collapsible open={showFullSummary} onOpenChange={setShowFullSummary}>
                  <ol className='list-inside list-decimal space-y-1 text-sm text-muted-foreground'>
                    {runSummary.data.summary_lines
                      .slice(0, VISIBLE_SUMMARY_LINES)
                      .map((line) => (
                        <li key={line} className='ps-1'>
                          {line.replace(/^\d+\.\s*/, '')}
                        </li>
                      ))}
                  </ol>
                  {runSummary.data.summary_lines.length > VISIBLE_SUMMARY_LINES && (
                    <>
                      <CollapsibleContent>
                        <ol
                          start={VISIBLE_SUMMARY_LINES + 1}
                          className='list-inside list-decimal space-y-1 text-sm text-muted-foreground'
                        >
                          {runSummary.data.summary_lines
                            .slice(VISIBLE_SUMMARY_LINES)
                            .map((line) => (
                              <li key={line} className='ps-1'>
                                {line.replace(/^\d+\.\s*/, '')}
                              </li>
                            ))}
                        </ol>
                      </CollapsibleContent>
                      <CollapsibleTrigger asChild>
                        <Button variant='ghost' size='sm' className='mt-1'>
                          {showFullSummary ? 'Hide' : 'Show'} full run evidence summary (
                          {runSummary.data.summary_lines.length} lines)
                          <ChevronDown
                            className={showFullSummary ? 'rotate-180 transition-transform' : 'transition-transform'}
                          />
                        </Button>
                      </CollapsibleTrigger>
                    </>
                  )}
                </Collapsible>

                {runSummary.data.ticker_highlights.length > 0 && (
                  <div>
                    <p className='mb-1 text-xs font-medium text-muted-foreground'>
                      Ticker highlights
                    </p>
                    <div className='space-y-1'>
                      {runSummary.data.ticker_highlights.map((h) => (
                        <div key={h.ticker} className='flex items-start gap-2 text-xs'>
                          <Badge variant='outline' className='shrink-0 font-mono'>
                            {h.ticker}
                          </Badge>
                          <StatusBadge tone={DECISION_TONE[h.decision] ?? 'info'} className='shrink-0'>
                            {h.decision}
                          </StatusBadge>
                          <span className='text-muted-foreground'>{h.reason}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {runSummary.data.learning_notes.length > 0 && (
                  <div>
                    <p className='mb-1 text-xs font-medium text-muted-foreground'>Learning notes</p>
                    <ul className='list-inside list-disc text-xs text-muted-foreground'>
                      {runSummary.data.learning_notes.map((note) => (
                        <li key={note}>{note}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </>
            ) : (
              <p className='text-sm text-muted-foreground'>No run summary available yet.</p>
            )}
          </CardContent>
        </Card>
      </Main>
    </>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className='flex items-center justify-between gap-2'>
      <span className='text-muted-foreground'>{label}</span>
      {children}
    </div>
  )
}
