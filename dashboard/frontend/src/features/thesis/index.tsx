import { formatDistanceToNow } from 'date-fns'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { StatusBadge, type StatusTone } from '@/components/status-badge'
import { ThemeSwitch } from '@/components/theme-switch'
import { type TickerThesis, useThesisReport } from './api'

const STATUS_TONE: Record<TickerThesis['status'], StatusTone> = {
  open: 'safe',
  closed: 'info',
  watching: 'warning',
}

const STATUS_LABEL: Record<TickerThesis['status'], string> = {
  open: 'Position open',
  closed: 'Position closed',
  watching: 'Watching — no position',
}

function fmtPrice(value: number | null | undefined): string {
  if (value == null) return '—'
  return `$${value.toLocaleString(undefined, { maximumFractionDigits: 6 })}`
}

function fmtUsd(value: number | null | undefined): string {
  if (value == null) return '—'
  return `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function fmtPct(value: number | null | undefined): string {
  if (value == null) return '—'
  return `${(value * 100).toLocaleString(undefined, { maximumFractionDigits: 2 })}%`
}

function fmtTime(value: string | null | undefined): string {
  if (!value) return '—'
  try {
    return formatDistanceToNow(new Date(value), { addSuffix: true })
  } catch {
    return value
  }
}

export function Thesis() {
  const { data, isLoading, isError } = useThesisReport()

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
            <h1 className='text-2xl font-bold tracking-tight'>Trade Thesis</h1>
            <p className='text-muted-foreground'>
              Per ticker, in plain terms: what would trigger a buy and at what
              price, where things stand right now, the reasoning behind the
              trade, and the exit parameters (take-profit, stop-loss,
              trailing stop, position size).
            </p>
          </div>
          <div className='flex gap-2'>
            <Badge variant='outline'>{data?.summary.open_count ?? 0} open</Badge>
            <Badge variant='outline'>{data?.summary.closed_count ?? 0} closed</Badge>
            <Badge variant='outline'>{data?.summary.watching_count ?? 0} watching</Badge>
          </div>
        </div>

        {isError && <p className='text-sm text-destructive'>Could not load the thesis report.</p>}

        {isLoading ? (
          <div className='grid gap-4 lg:grid-cols-2'>
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className='h-96' />
            ))}
          </div>
        ) : (
          <div className='grid gap-4 lg:grid-cols-2'>
            {(data?.tickers ?? []).map((t) => (
              <ThesisCard key={t.ticker} thesis={t} />
            ))}
            {(data?.tickers ?? []).length === 0 && (
              <p className='col-span-full text-center text-muted-foreground'>
                No thesis data available yet.
              </p>
            )}
          </div>
        )}
      </Main>
    </>
  )
}

function ThesisCard({ thesis }: { thesis: TickerThesis }) {
  const { entry_plan, trailing_stop, position } = thesis

  return (
    <Card>
      <CardHeader className='flex flex-row items-center justify-between space-y-0 pb-2'>
        <CardTitle className='text-base font-semibold'>{thesis.ticker}</CardTitle>
        <div className='flex items-center gap-2'>
          <StatusBadge tone={STATUS_TONE[thesis.status]}>{STATUS_LABEL[thesis.status]}</StatusBadge>
        </div>
      </CardHeader>
      <CardContent className='space-y-4 text-sm'>
        <div className='flex items-center justify-between text-xs text-muted-foreground'>
          <span>
            {thesis.setup_type ?? 'setup unclear'} · as of {fmtTime(thesis.as_of)}
          </span>
          <span>current {fmtPrice(thesis.current_price)}</span>
        </div>

        <Section title='Buy condition & price'>
          <p className='text-muted-foreground'>{entry_plan.condition_text || 'No entry thesis recorded yet.'}</p>
          <dl className='mt-2 grid grid-cols-2 gap-x-4 gap-y-1'>
            <Row label='Entry zone'>
              {entry_plan.entry_zone_low != null || entry_plan.entry_zone_high != null
                ? `${fmtPrice(entry_plan.entry_zone_low)} – ${fmtPrice(entry_plan.entry_zone_high)}`
                : '—'}
            </Row>
            <Row label='Trigger price'>{fmtPrice(entry_plan.trigger_price)}</Row>
            <Row label="Don't chase above">{fmtPrice(entry_plan.do_not_chase_above)}</Row>
            <Row label='Plan status'>
              {entry_plan.valid_new_entry_plan ? 'valid new-entry plan' : entry_plan.plan_action ?? '—'}
            </Row>
          </dl>
        </Section>

        <Separator />

        <Section title='Where we stand'>
          {position ? (
            <dl className='grid grid-cols-2 gap-x-4 gap-y-1'>
              <Row label='Entry price'>{fmtPrice(position.entry_price)}</Row>
              <Row label='Entry time'>{fmtTime(position.entry_time)}</Row>
              {thesis.status === 'closed' ? (
                <>
                  <Row label='Close price'>{fmtPrice(position.close_price)}</Row>
                  <Row label='Closed'>{fmtTime(position.close_time)}</Row>
                  <Row label='Close reason'>{position.close_reason ?? '—'}</Row>
                  <Row label='Realized PnL'>{fmtUsd(position.realized_pnl)}</Row>
                </>
              ) : (
                <>
                  <Row label='Size'>{fmtUsd(position.size_quote_usdc)}</Row>
                  <Row label='Entry reason'>{position.entry_reason ?? '—'}</Row>
                </>
              )}
            </dl>
          ) : (
            <p className='text-muted-foreground'>
              No position — waiting for the entry condition above to trigger.
            </p>
          )}
        </Section>

        <Separator />

        <Section title='Thesis'>
          {thesis.thesis_reasons.length > 0 ? (
            <ul className='list-disc space-y-1 ps-4 text-muted-foreground'>
              {thesis.thesis_reasons
                .filter((r) => !r.startsWith('objective_score='))
                .map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
            </ul>
          ) : (
            <p className='text-muted-foreground'>No reasoning recorded yet.</p>
          )}
          {thesis.judge_decision && (
            <p className='mt-2 text-xs text-muted-foreground'>
              Latest judge decision: <span className='font-medium'>{thesis.judge_decision}</span>
              {thesis.judge_confidence != null && ` (confidence ${thesis.judge_confidence})`}
            </p>
          )}
        </Section>

        <Separator />

        <Section title='Exit parameters'>
          <dl className='grid grid-cols-2 gap-x-4 gap-y-1'>
            <Row label='Take-profit'>{fmtPrice(thesis.take_profit_price)}</Row>
            <Row label='Take-profit 2'>{fmtPrice(thesis.take_profit_2_price)}</Row>
            <Row label='Stop-loss'>{fmtPrice(thesis.stop_loss_price)}</Row>
            <Row label='Invalidation'>{fmtPrice(thesis.invalidation_price)}</Row>
            <Row label='Trailing stop'>
              {trailing_stop.active ? 'active' : 'not yet active'}
            </Row>
            <Row label='Trailing trigger / distance'>
              {fmtPct(trailing_stop.trigger_pct)} / {fmtPct(trailing_stop.distance_pct)}
            </Row>
            <Row label='Position size'>{fmtUsd(position?.size_quote_usdc)}</Row>
          </dl>
        </Section>

        {thesis.must_reject_if.length > 0 && (
          <>
            <Separator />
            <Section title='Invalidates the thesis if'>
              <ul className='list-disc space-y-1 ps-4 text-muted-foreground'>
                {thesis.must_reject_if.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            </Section>
          </>
        )}
      </CardContent>
    </Card>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className='mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground'>
        {title}
      </h3>
      {children}
    </div>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className='text-muted-foreground'>{label}</dt>
      <dd className='text-end font-medium'>{children}</dd>
    </>
  )
}
