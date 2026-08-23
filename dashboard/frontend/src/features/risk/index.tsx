import { CheckCircle2, ShieldAlert, XCircle } from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { StatusBadge } from '@/components/status-badge'
import { ThemeSwitch } from '@/components/theme-switch'
import { type GuardRow, useRiskGuards } from './api'

const CATEGORY_LABELS: Record<string, string> = {
  process: 'Process & lock',
  coinbase: 'Coinbase access',
  'danger-zone': 'Danger zone',
  operator: 'Operator action',
  config: 'Configuration',
}

export function Risk() {
  const { data, isLoading, isError } = useRiskGuards()

  const guardsByCategory = (data?.guards ?? []).reduce<Record<string, GuardRow[]>>(
    (acc, guard) => {
      acc[guard.category] = acc[guard.category] ?? []
      acc[guard.category].push(guard)
      return acc
    },
    {}
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
            <h1 className='text-2xl font-bold tracking-tight'>Risk & Safety Dashboard</h1>
            <p className='text-muted-foreground'>
              Why something is, or is not, allowed to go live — guard by guard.
            </p>
          </div>
          {!isLoading && data && (
            <div className='flex items-center gap-2'>
              <StatusBadge tone={data.operational_health.tone}>
                operational: {data.operational_health.tone}
              </StatusBadge>
              <Badge
                variant='outline'
                className={
                  data.danger_count > 0
                    ? 'border-red-600/30 bg-red-500/15 text-red-600 dark:text-red-400'
                    : 'border-emerald-600/30 bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
                }
              >
                <ShieldAlert className='size-3.5' />
                {data.danger_count} danger {data.danger_count === 1 ? 'flag' : 'flags'}
              </Badge>
            </div>
          )}
        </div>

        {isError && (
          <Alert variant='destructive' className='mb-4'>
            <AlertTitle>Could not load risk guards</AlertTitle>
            <AlertDescription>
              The underlying status tools failed to run. Try again shortly.
            </AlertDescription>
          </Alert>
        )}

        {!isLoading && data?.operator_action && (
          <Alert className='mb-4'>
            <AlertTitle>Operator action required</AlertTitle>
            <AlertDescription>{data.operator_action}</AlertDescription>
          </Alert>
        )}

        {isLoading ? (
          <div className='grid gap-4 sm:grid-cols-2'>
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className='h-40' />
            ))}
          </div>
        ) : (
          <div className='grid gap-4 sm:grid-cols-2'>
            {Object.entries(guardsByCategory).map(([category, guards]) => (
              <Card key={category}>
                <CardHeader>
                  <CardTitle className='text-sm font-medium'>
                    {CATEGORY_LABELS[category] ?? category}
                  </CardTitle>
                </CardHeader>
                <CardContent className='space-y-2'>
                  {guards.map((guard) => (
                    <div key={guard.guard} className='space-y-0.5 text-sm'>
                      <div className='flex items-center justify-between gap-2'>
                        <span className='flex items-center gap-2 text-muted-foreground'>
                          {guard.status === 'danger' ? (
                            <XCircle className='size-3.5 text-red-500' />
                          ) : guard.status === 'safe' ? (
                            <CheckCircle2 className='size-3.5 text-emerald-500' />
                          ) : null}
                          {guard.guard}
                        </span>
                        <StatusBadge tone={guard.status}>{String(guard.value)}</StatusBadge>
                      </div>
                      {guard.note && (
                        <p className='ps-5.5 text-xs text-muted-foreground'>{guard.note}</p>
                      )}
                    </div>
                  ))}
                </CardContent>
              </Card>
            ))}
          </div>
        )}

        {!isLoading && (data?.annotated_blockers?.length ?? 0) > 0 && (
          <Card className='mt-4'>
            <CardHeader>
              <CardTitle className='text-sm font-medium'>
                Restart/maintenance blockers (show_full_pipeline_health.py)
              </CardTitle>
            </CardHeader>
            <CardContent className='space-y-2'>
              <p className='text-xs text-muted-foreground'>
                These answer "is it safe to restart or do maintenance right now" —
                a different question from "is the bot healthy". Each one is
                explained below, not just listed; nothing here is hidden, only
                annotated.
              </p>
              {data?.annotated_blockers.map((b) => (
                <div key={b.blocker} className='flex items-start justify-between gap-2 text-sm'>
                  <div>
                    <span className='font-mono text-xs'>{b.blocker}</span>
                    <p className='text-xs text-muted-foreground'>{b.detail}</p>
                  </div>
                  <StatusBadge tone={b.tone}>{b.tone}</StatusBadge>
                </div>
              ))}
            </CardContent>
          </Card>
        )}

        {!isLoading && (data?.operator_checklist?.length ?? 0) > 0 && (
          <Card className='mt-4'>
            <CardHeader>
              <CardTitle className='text-sm font-medium'>Operator checklist</CardTitle>
            </CardHeader>
            <CardContent>
              <ul className='space-y-1 text-sm text-muted-foreground'>
                {data?.operator_checklist.map((item) => <li key={item}>{item}</li>)}
              </ul>
            </CardContent>
          </Card>
        )}
      </Main>
    </>
  )
}
