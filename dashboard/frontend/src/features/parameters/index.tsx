import { useMemo, useState } from 'react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { DataTable } from '@/components/data-table'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { StatusBadge } from '@/components/status-badge'
import { ThemeSwitch } from '@/components/theme-switch'
import { type ParameterProposal, useParameterProposals, type FullParameter, useFullParameterProposals } from './api'
import { buildColumns } from './columns'

// ---------------------------------------------------------------------------
// Status tone helpers
// ---------------------------------------------------------------------------

const STATUS_TONE: Record<string, 'safe' | 'warning' | 'danger' | 'info'> = {
  safe_to_activate: 'safe',
  needs_more_evidence: 'warning',
  blocked: 'danger',
  no_proposal: 'info',
}

const DIRECTION_TONE: Record<string, 'safe' | 'warning' | 'info'> = {
  loosen: 'warning',
  tighten: 'warning',
  keep: 'info',
}

// ---------------------------------------------------------------------------
// Full parameter table
// ---------------------------------------------------------------------------

type FilterKey =
  | 'all'
  | 'actionable'
  | 'blocked'
  | 'no_proposal'
  | 'not_wired'
  | 'governor'
  | 'growbot_river'
  | 'approved_profile'
  | 'shadow_evidence'
  | 'sizing'
  | 'risk'
  | 'judge'
  | 'runtime_active'
  | 'runtime_inactive'

const FILTER_LABELS: Record<FilterKey, string> = {
  all: 'All',
  actionable: 'Actionable',
  blocked: 'Blocked',
  no_proposal: 'No proposal',
  not_wired: 'Not wired',
  governor: 'Governor-owned',
  growbot_river: 'GrowBot/River',
  approved_profile: 'Approved profile',
  shadow_evidence: 'Shadow evidence',
  sizing: 'Sizing',
  risk: 'Risk',
  judge: 'Judge/gate',
  runtime_active: 'Runtime active',
  runtime_inactive: 'Runtime inactive',
}

function applyFilter(rows: FullParameter[], filter: FilterKey): FullParameter[] {
  switch (filter) {
    case 'all': return rows
    case 'actionable': return rows.filter((r) => r.status === 'safe_to_activate' || r.status === 'needs_more_evidence')
    case 'blocked': return rows.filter((r) => r.status === 'blocked')
    case 'no_proposal': return rows.filter((r) => r.status === 'no_proposal')
    case 'not_wired': return rows.filter((r) => !r.active_in_runtime)
    case 'governor': return rows.filter((r) => r.in_governor_allowlist)
    case 'growbot_river': return rows.filter((r) => r.source === 'growbot_river')
    case 'approved_profile': return rows.filter((r) => r.visible_in_approved_profile)
    case 'shadow_evidence': return rows.filter((r) => r.shadow_evidence_usable > 0)
    case 'sizing': return rows.filter((r) => r.family === 'sizing')
    case 'risk': return rows.filter((r) => r.family === 'risk')
    case 'judge': return rows.filter((r) => r.family === 'judge')
    case 'runtime_active': return rows.filter((r) => r.active_in_runtime)
    case 'runtime_inactive': return rows.filter((r) => !r.active_in_runtime)
    default: return rows
  }
}

function FullParameterRow({ row, onSelect }: { row: FullParameter; onSelect: (r: FullParameter) => void }) {
  return (
    <tr
      className='border-b last:border-0 cursor-pointer hover:bg-muted/40 text-sm'
      onClick={() => onSelect(row)}
    >
      <td className='py-2 pr-3'>
        <span className='font-mono text-xs font-medium'>{row.name}</span>
        {row.governor_is_watching && (
          <Badge variant='outline' className='ml-1 border-violet-600/30 bg-violet-500/10 text-violet-600 text-[10px] px-1'>
            gov
          </Badge>
        )}
      </td>
      <td className='pr-3 text-muted-foreground'>{row.category}</td>
      <td className='pr-3 font-mono text-xs'>{String(row.current_value ?? '—')}</td>
      <td className='pr-3 font-mono text-xs'>{String(row.proposed_value ?? '—')}</td>
      <td className='pr-3'>
        {row.direction !== 'keep' && row.proposed_value != null ? (
          <StatusBadge tone={DIRECTION_TONE[row.direction] ?? 'info'}>
            {row.direction}
          </StatusBadge>
        ) : (
          <span className='text-muted-foreground text-xs'>keep</span>
        )}
      </td>
      <td className='pr-3'>
        <StatusBadge tone={STATUS_TONE[row.status] ?? 'info'}>
          {row.status.replace(/_/g, ' ')}
        </StatusBadge>
      </td>
      <td className='pr-3'>
        <StatusBadge tone={row.active_in_runtime ? 'safe' : 'info'}>
          {row.active_in_runtime ? 'wired' : 'not wired'}
        </StatusBadge>
      </td>
      <td className='pr-3'>
        {row.in_governor_allowlist ? (
          <StatusBadge tone='safe'>governor</StatusBadge>
        ) : (
          <span className='text-muted-foreground text-xs'>manual</span>
        )}
      </td>
      <td className='text-xs text-muted-foreground'>{row.source.replace(/_/g, ' ')}</td>
    </tr>
  )
}

function FullParameterDetail({ row }: { row: FullParameter }) {
  return (
    <>
      <SheetHeader>
        <SheetTitle className='font-mono text-sm'>{row.name}</SheetTitle>
        <SheetDescription>{row.category} · {row.family}</SheetDescription>
      </SheetHeader>
      <div className='space-y-4 px-4 text-sm'>
        <DetailRow label='Description' value={row.description || '—'} />
        <DetailRow label='Current → Proposed'
          value={`${String(row.current_value ?? '—')} → ${String(row.proposed_value ?? '—')}`} />
        {row.proposed_delta != null && (
          <DetailRow label='Delta' value={String(row.proposed_delta)} />
        )}
        <DetailRow label='Direction' value={row.direction} />
        <DetailRow label='Status' value={row.status.replace(/_/g, ' ')} />
        <DetailRow label='Owner' value={row.owner} />
        <DetailRow label='Source' value={row.source.replace(/_/g, ' ')} />
        <DetailRow label='Activation route' value={row.activation_route || '—'} />
        <DetailRow label='Governor allowlist' value={row.in_governor_allowlist ? 'Yes' : 'No'} />
        <DetailRow label='Active in runtime' value={row.active_in_runtime ? 'Yes' : 'No'} />
        <DetailRow label='In approved profile' value={row.visible_in_approved_profile ? 'Yes' : 'No'} />
        {row.confidence != null && (
          <DetailRow label='Confidence' value={`${(row.confidence * 100).toFixed(1)}%`} />
        )}
        {row.evidence_count != null && (
          <DetailRow label='Evidence count' value={String(row.evidence_count)} />
        )}
        {row.regimes_seen.length > 0 && (
          <DetailRow label='Regimes seen' value={row.regimes_seen.join(', ')} />
        )}
        {row.blockers.length > 0 && (
          <DetailRow label='Blockers' value={row.blockers.join(', ')} />
        )}
        {row.rollback_note && (
          <DetailRow label='Rollback note' value={row.rollback_note} />
        )}
        <div>
          <p className='font-medium text-muted-foreground'>Shadow evidence</p>
          <p>{row.shadow_evidence_usable} usable / {row.shadow_evidence_total} total
            {row.shadow_sufficient ? ' · sufficient' : ' · not yet sufficient'}</p>
        </div>
        {row.candidate_profile_value != null && row.candidate_profile_value !== row.current_value && (
          <DetailRow label='Candidate profile value' value={String(row.candidate_profile_value)} />
        )}
        {row.last_updated && (
          <DetailRow label='Last updated' value={row.last_updated} />
        )}
        <p className='rounded-md bg-muted p-2 text-xs text-muted-foreground'>
          Evidence-only dashboard. Nothing here can apply, activate or modify any parameter.
        </p>
      </div>
    </>
  )
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className='font-medium text-muted-foreground'>{label}</p>
      <p className='break-words'>{value}</p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main page component
// ---------------------------------------------------------------------------

export function Parameters() {
  const { data, isLoading, isError } = useParameterProposals()
  const { data: fullData, isLoading: fullLoading } = useFullParameterProposals()
  const [selected, setSelected] = useState<ParameterProposal | null>(null)
  const [selectedFull, setSelectedFull] = useState<FullParameter | null>(null)
  const [activeFilter, setActiveFilter] = useState<FilterKey>('all')
  const columns = useMemo(() => buildColumns((row) => setSelected(row)), [])

  const filteredFull = useMemo(
    () => applyFilter(fullData?.parameters ?? [], activeFilter),
    [fullData?.parameters, activeFilter]
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
            <h1 className='text-2xl font-bold tracking-tight'>Parameter Proposals</h1>
            <p className='text-muted-foreground'>
              What GrowBot/River and the adaptive governor want to change, and why.
              Preview only — nothing here is ever applied by this dashboard.
            </p>
          </div>
          <div className='flex gap-2'>
            <Badge variant='outline'>{data?.proposal_count ?? 0} active proposals</Badge>
            <Badge variant='outline'>{fullData?.total_parameters ?? 0} parameters tracked</Badge>
          </div>
        </div>

        {isError && (
          <Alert variant='destructive' className='mb-4'>
            <AlertTitle>Could not load parameter proposals</AlertTitle>
            <AlertDescription>The learning status tool failed to run.</AlertDescription>
          </Alert>
        )}

        {!isLoading && data?.next_operator_action && (
          <Alert className='mb-4'>
            <AlertTitle>Next operator action</AlertTitle>
            <AlertDescription>{data.next_operator_action}</AlertDescription>
          </Alert>
        )}

        {/* Summary cards for full universe */}
        {fullData && (
          <div className='mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5'>
            <Card>
              <CardHeader><CardTitle className='text-xs font-medium'>With proposal</CardTitle></CardHeader>
              <CardContent><div className='text-2xl font-bold'>{fullData.parameters_with_proposal}</div></CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle className='text-xs font-medium'>Blocked</CardTitle></CardHeader>
              <CardContent><div className='text-2xl font-bold'>{fullData.parameters_blocked}</div></CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle className='text-xs font-medium'>No proposal</CardTitle></CardHeader>
              <CardContent><div className='text-2xl font-bold'>{fullData.parameters_no_proposal}</div></CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle className='text-xs font-medium'>Governor allowlist</CardTitle></CardHeader>
              <CardContent><div className='text-2xl font-bold'>{fullData.parameters_in_governor_allowlist}</div></CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle className='text-xs font-medium'>Shadow evidence</CardTitle></CardHeader>
              <CardContent>
                <div className='text-2xl font-bold'>{fullData.shadow_evidence_usable}</div>
                <p className='text-xs text-muted-foreground'>usable / {fullData.shadow_evidence_total} total</p>
              </CardContent>
            </Card>
          </div>
        )}

        <Tabs defaultValue='full'>
          <TabsList className='mb-4'>
            <TabsTrigger value='full'>Full universe</TabsTrigger>
            <TabsTrigger value='proposals'>Active proposals</TabsTrigger>
          </TabsList>

          <TabsContent value='full'>
            {/* Filter bar */}
            <div className='mb-3 flex flex-wrap gap-2'>
              {(Object.keys(FILTER_LABELS) as FilterKey[]).map((key) => (
                <button
                  key={key}
                  onClick={() => setActiveFilter(key)}
                  className={[
                    'rounded-full border px-3 py-1 text-xs transition-colors',
                    activeFilter === key
                      ? 'border-primary bg-primary text-primary-foreground'
                      : 'border-border bg-background hover:bg-muted',
                  ].join(' ')}
                >
                  {FILTER_LABELS[key]}
                  {key !== 'all' && (
                    <span className='ml-1 text-[10px] opacity-70'>
                      ({applyFilter(fullData?.parameters ?? [], key).length})
                    </span>
                  )}
                </button>
              ))}
            </div>

            {fullLoading ? (
              <Skeleton className='h-96' />
            ) : (
              <Card>
                <CardHeader>
                  <CardTitle className='text-sm font-medium'>
                    {filteredFull.length} parameter(s) · filter: {FILTER_LABELS[activeFilter]}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className='overflow-x-auto'>
                    <table className='w-full text-sm'>
                      <thead>
                        <tr className='border-b text-left text-xs text-muted-foreground'>
                          <th className='pb-2 pr-3'>Parameter</th>
                          <th className='pb-2 pr-3'>Category</th>
                          <th className='pb-2 pr-3'>Current</th>
                          <th className='pb-2 pr-3'>Proposed</th>
                          <th className='pb-2 pr-3'>Direction</th>
                          <th className='pb-2 pr-3'>Status</th>
                          <th className='pb-2 pr-3'>Runtime</th>
                          <th className='pb-2 pr-3'>Route</th>
                          <th className='pb-2'>Source</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredFull.map((row) => (
                          <FullParameterRow key={row.name} row={row} onSelect={setSelectedFull} />
                        ))}
                        {filteredFull.length === 0 && (
                          <tr>
                            <td colSpan={9} className='py-4 text-center text-muted-foreground text-sm'>
                              No parameters match this filter.
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>
            )}
          </TabsContent>

          <TabsContent value='proposals'>
            {isLoading ? (
              <Skeleton className='h-96' />
            ) : (
              <Card>
                <CardHeader>
                  <CardTitle className='text-sm font-medium'>
                    {data?.proposals.length ?? 0} parameter(s) tracked
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <DataTable
                    columns={columns}
                    data={data?.proposals ?? []}
                    pageSize={15}
                    emptyMessage='No parameters found.'
                  />
                </CardContent>
              </Card>
            )}
          </TabsContent>
        </Tabs>
      </Main>

      {/* Existing proposal detail sheet */}
      <Sheet open={!!selected} onOpenChange={(open) => !open && setSelected(null)}>
        <SheetContent className='w-full sm:max-w-lg'>
          {selected && (
            <>
              <SheetHeader>
                <SheetTitle className='font-mono text-sm'>{selected.parameter}</SheetTitle>
                <SheetDescription>{selected.category}</SheetDescription>
              </SheetHeader>
              <div className='space-y-4 px-4 text-sm'>
                <DetailRow label='Reason' value={selected.reason ?? '—'} />
                <DetailRow
                  label='Current → Proposed'
                  value={`${String(selected.current_value ?? '—')} → ${String(selected.proposed_value ?? '—')}`}
                />
                <DetailRow
                  label='Confidence'
                  value={selected.confidence != null ? `${(selected.confidence * 100).toFixed(1)}%` : '—'}
                />
                <DetailRow label='Evidence count' value={String(selected.evidence_count ?? '—')} />
                <DetailRow
                  label='Regimes seen'
                  value={selected.regimes_seen.length ? selected.regimes_seen.join(', ') : 'none recorded'}
                />
                <DetailRow
                  label='Blockers'
                  value={selected.blockers.length ? selected.blockers.join(', ') : 'none'}
                />
                <DetailRow
                  label='Rollback plan'
                  value={selected.rollback_plan.length ? selected.rollback_plan.join(' → ') : 'n/a'}
                />
                <DetailRow label='Activation route' value={selected.activation_route ?? '—'} />
                <DetailRow label='Source' value={selected.source} />
                {selected.expected_effect && (
                  <div>
                    <p className='mb-1 font-medium text-muted-foreground'>Expected effect</p>
                    <pre className='overflow-x-auto rounded-md bg-muted p-2 text-xs'>
                      {JSON.stringify(selected.expected_effect, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>

      {/* Full parameter detail sheet */}
      <Sheet open={!!selectedFull} onOpenChange={(open) => !open && setSelectedFull(null)}>
        <SheetContent className='w-full sm:max-w-lg overflow-y-auto'>
          {selectedFull && <FullParameterDetail row={selectedFull} />}
        </SheetContent>
      </Sheet>
    </>
  )
}
