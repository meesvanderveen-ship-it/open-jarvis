import { useMemo, useState } from 'react'
import { Badge } from '@/components/ui/badge'
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
import { StatusBadge, type StatusTone } from '@/components/status-badge'
import { ThemeSwitch } from '@/components/theme-switch'
import { useOpportunities } from './api'

function scoreTone(score: number | null | undefined): StatusTone {
  if (score == null) return 'info'
  if (score >= 70) return 'safe'
  if (score >= 40) return 'warning'
  return 'danger'
}

const DECISION_TONE: Record<string, StatusTone> = {
  wait: 'info',
  prepare_buy: 'safe',
  approve_trade: 'safe',
  close_position: 'warning',
  reject: 'danger',
}

export function Opportunities() {
  const { data, isLoading, isError } = useOpportunities()
  const [decisionFilter, setDecisionFilter] = useState<string>('all')

  const decisions = useMemo(
    () => Object.keys(data?.summary.decision_counts ?? {}),
    [data]
  )

  const filtered = (data?.opportunities ?? []).filter(
    (o) => decisionFilter === 'all' || o.decision === decisionFilter
  )

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
            <h1 className='text-2xl font-bold tracking-tight'>Opportunity Radar</h1>
            <p className='text-muted-foreground'>
              Market opportunities the bot sees — including the ones it chose to wait on.
            </p>
          </div>
          <div className='flex items-center gap-2'>
            <Select value={decisionFilter} onValueChange={setDecisionFilter}>
              <SelectTrigger className='w-44'>
                <SelectValue placeholder='Filter decision' />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value='all'>All decisions</SelectItem>
                {decisions.map((d) => (
                  <SelectItem key={d} value={d}>
                    {d} ({data?.summary.decision_counts[d]})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Badge variant='outline'>{data?.summary.ticker_count ?? 0} tickers</Badge>
          </div>
        </div>

        {isError && (
          <p className='text-sm text-destructive'>Could not load opportunities.</p>
        )}

        {isLoading ? (
          <div className='grid gap-4 sm:grid-cols-2 lg:grid-cols-3'>
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className='h-48' />
            ))}
          </div>
        ) : (
          <div className='grid gap-4 sm:grid-cols-2 lg:grid-cols-3'>
            {filtered.map((o) => (
              <Card key={o.ticker}>
                <CardHeader className='flex flex-row items-center justify-between space-y-0 pb-2'>
                  <CardTitle className='text-sm font-medium'>{o.ticker}</CardTitle>
                  <StatusBadge tone={scoreTone(o.opportunity_score)}>
                    score {o.opportunity_score ?? '—'}
                  </StatusBadge>
                </CardHeader>
                <CardContent className='space-y-2 text-sm'>
                  <div className='flex items-center justify-between'>
                    <span className='text-muted-foreground'>decision</span>
                    <StatusBadge tone={DECISION_TONE[o.decision ?? ''] ?? 'info'}>
                      {o.decision ?? 'unknown'}
                    </StatusBadge>
                  </div>
                  <div className='flex items-center justify-between'>
                    <span className='text-muted-foreground'>setup</span>
                    <span>{o.setup_type ?? '—'}</span>
                  </div>
                  <div className='flex items-center justify-between'>
                    <span className='text-muted-foreground'>judge confidence</span>
                    <span>{o.judge?.confidence ?? '—'}</span>
                  </div>
                  <div className='flex items-center justify-between'>
                    <span className='text-muted-foreground'>price</span>
                    <span>{o.current_price ?? '—'}</span>
                  </div>
                  <p className='line-clamp-3 text-xs text-muted-foreground'>{o.reason}</p>
                </CardContent>
              </Card>
            ))}
            {filtered.length === 0 && (
              <p className='col-span-full text-center text-muted-foreground'>
                No opportunities match this filter.
              </p>
            )}
          </div>
        )}
      </Main>
    </>
  )
}
