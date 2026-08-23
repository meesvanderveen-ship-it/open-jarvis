import { useState } from 'react'
import { ExternalLink } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { StatusBadge } from '@/components/status-badge'
import { ThemeSwitch } from '@/components/theme-switch'
import { useParameterProposals } from '@/features/parameters/api'
import { useReportDetail, useReportList } from '@/features/reports/api'

const ADAPTIVE_LAB_REPORT_ID = 'adaptive_policy/adaptive-policy-lab-latest.json'

export function Simulation() {
  const { data: proposalsData, isLoading: proposalsLoading } = useParameterProposals()
  const [selectedParam, setSelectedParam] = useState<string | null>(null)
  const proposals = proposalsData?.proposals ?? []
  const selected = proposals.find((p) => p.parameter === selectedParam) ?? proposals[0]

  const lab = useReportDetail(ADAPTIVE_LAB_REPORT_ID)
  const labContent = lab.data?.content as Record<string, unknown> | undefined

  const backtests = useReportList('backtests')

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
            <h1 className='text-2xl font-bold tracking-tight'>Simulation / Backtest Lab</h1>
            <p className='text-muted-foreground'>
              Review a proposal's evidence, regime split, and overfit risk before it would
              ever be considered for activation. Preview only — no apply action exists here.
            </p>
          </div>
          <Select
            value={selected?.parameter}
            onValueChange={setSelectedParam}
            disabled={proposalsLoading}
          >
            <SelectTrigger className='w-72'>
              <SelectValue placeholder='Select parameter' />
            </SelectTrigger>
            <SelectContent>
              {proposals.map((p) => (
                <SelectItem key={p.parameter} value={p.parameter} className='font-mono text-xs'>
                  {p.parameter}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {proposalsLoading ? (
          <Skeleton className='h-64' />
        ) : selected ? (
          <div className='grid gap-4 lg:grid-cols-2'>
            <Card>
              <CardHeader>
                <CardTitle className='text-sm font-medium'>{selected.parameter}</CardTitle>
              </CardHeader>
              <CardContent className='space-y-2 text-sm'>
                <Row label='Category' value={selected.category} />
                <Row label='Current → Proposed' value={`${String(selected.current_value ?? '—')} → ${String(selected.proposed_value ?? '—')}`} />
                <Row label='Direction' value={selected.direction} />
                <Row label='Reason' value={selected.reason ?? '—'} />
                <Row label='Confidence' value={selected.confidence != null ? `${(selected.confidence * 100).toFixed(1)}%` : '—'} />
                <Row label='Evidence count' value={String(selected.evidence_count ?? '—')} />
                <div className='flex items-center justify-between'>
                  <span className='text-muted-foreground'>Safety status</span>
                  <StatusBadge
                    tone={selected.safety_status === 'blocked' ? 'danger' : selected.safety_status === 'safe_to_activate' ? 'safe' : 'warning'}
                  >
                    {selected.safety_status.replace(/_/g, ' ')}
                  </StatusBadge>
                </div>
                <Row label='Blockers' value={selected.blockers.length ? selected.blockers.join(', ') : 'none'} />
                <Row label='Rollback plan' value={selected.rollback_plan.length ? selected.rollback_plan.join(' → ') : 'n/a'} />
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className='text-sm font-medium'>Expected effect & risk impact</CardTitle>
              </CardHeader>
              <CardContent className='space-y-2 text-sm'>
                <pre className='overflow-x-auto rounded-md bg-muted p-2 text-xs'>
                  {JSON.stringify({ expected_effect: selected.expected_effect, risk_impact: selected.risk_impact }, null, 2)}
                </pre>
                <Row label='Regimes seen' value={selected.regimes_seen.length ? selected.regimes_seen.join(', ') : 'none recorded'} />
              </CardContent>
            </Card>
          </div>
        ) : (
          <p className='text-muted-foreground'>No active parameter proposals to review.</p>
        )}

        <Card className='mt-4'>
          <CardHeader>
            <CardTitle className='text-sm font-medium'>
              Adaptive policy lab — regime split & overfit risk
            </CardTitle>
          </CardHeader>
          <CardContent className='space-y-2 text-sm'>
            {lab.isLoading ? (
              <Skeleton className='h-32' />
            ) : labContent ? (
              <>
                <div className='flex items-center justify-between'>
                  <span className='text-muted-foreground'>Overfit risk</span>
                  <StatusBadge
                    tone={
                      labContent.overfit_risk === 'high'
                        ? 'danger'
                        : labContent.overfit_risk === 'medium'
                          ? 'warning'
                          : 'safe'
                    }
                  >
                    {String(labContent.overfit_risk ?? 'unknown')}
                  </StatusBadge>
                </div>
                <Row label='Market regime coverage' value={`${labContent.market_regime_coverage_pct ?? '—'}%`} />
                <Row label='Recommendation' value={String(labContent.recommendation ?? '—')} />
                <Row label='Safe to activate now' value={String(labContent.safe_to_activate_now ?? '—')} />
                <details className='mt-2'>
                  <summary className='cursor-pointer text-muted-foreground'>Regime diversity (raw)</summary>
                  <pre className='mt-2 max-h-64 overflow-auto rounded-md bg-muted p-2 text-xs'>
                    {JSON.stringify(labContent.regime_diversity, null, 2)}
                  </pre>
                </details>
              </>
            ) : (
              <p className='text-muted-foreground'>No adaptive policy lab report available.</p>
            )}
          </CardContent>
        </Card>

        <Card className='mt-4'>
          <CardHeader>
            <CardTitle className='text-sm font-medium'>Linked backtest reports</CardTitle>
          </CardHeader>
          <CardContent>
            {backtests.isLoading ? (
              <Skeleton className='h-20' />
            ) : (backtests.data?.reports.length ?? 0) === 0 ? (
              <p className='text-muted-foreground'>No backtest reports found.</p>
            ) : (
              <ul className='space-y-1 text-sm'>
                {backtests.data?.reports.map((r) => (
                  <li key={r.id}>
                    <a
                      href={`/api/reports/${r.id}`}
                      target='_blank'
                      rel='noreferrer'
                      className='inline-flex items-center gap-1 font-mono text-xs underline-offset-2 hover:underline'
                    >
                      {r.name} <ExternalLink className='size-3' />
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </Main>
    </>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className='flex items-center justify-between gap-2'>
      <span className='text-muted-foreground'>{label}</span>
      <span className='break-words text-end'>{value}</span>
    </div>
  )
}
