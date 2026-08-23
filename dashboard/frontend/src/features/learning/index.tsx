import { useMemo, useState } from 'react'
import { CheckCircle2, Circle } from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { DataTable } from '@/components/data-table'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { StatusBadge } from '@/components/status-badge'
import { ThemeSwitch } from '@/components/theme-switch'
import { buildEvidenceColumns } from './columns'
import {
  type ParameterEvidence,
  useLearningIntelligence,
  useLearningStatus,
  useParameterProposalFunnel,
  useShadowOutcomesStatus,
  useShadowOutcomesRecent,
} from './api'
import { useLlmCost24h, useLlmCost7d, useMultiAgentAudit } from '../llm-cost/api'

const TIER_FUNNEL_ORDER = [
  'observed_signal',
  'shadow_candidate',
  'backtest_candidate',
  'walk_forward_candidate',
  'operator_review_candidate',
  'apply_ready_candidate',
]
const TIER_FUNNEL_LABEL: Record<string, string> = {
  observed_signal: 'Observed signal',
  shadow_candidate: 'Shadow candidate',
  backtest_candidate: 'Backtest candidate',
  walk_forward_candidate: 'Walk-forward candidate',
  operator_review_candidate: 'Operator review',
  apply_ready_candidate: 'Apply ready',
}

const READINESS_TIER_LABELS: Record<string, string> = {
  report_only_ready: 'Report-only',
  fast_start_autotune_ready: 'Fast-start autotune',
  stabilization_ready: 'Stabilization',
  fine_tuning_ready: 'Fine-tuning',
  parameter_profile_activation_ready: 'Parameter profile activation',
  mode_a_live_ready: 'Mode A live',
  mode_b_live_ready: 'Mode B live',
}

function CoverageBar({ label, pct, threshold = 80 }: { label: string; pct?: number; threshold?: number }) {
  const value = pct ?? 0
  return (
    <div className='space-y-1'>
      <div className='flex items-center justify-between text-sm'>
        <span className='text-muted-foreground'>{label}</span>
        <span className='font-medium'>{value.toFixed(1)}%</span>
      </div>
      <Progress value={Math.min(value, 100)} className={value >= threshold ? '[&>div]:bg-emerald-500' : '[&>div]:bg-amber-500'} />
      <p className='text-xs text-muted-foreground'>threshold {threshold}%</p>
    </div>
  )
}

export function Learning() {
  const { data, isLoading, isError } = useLearningStatus()
  const coverage = data?.learning_data_contract?.coverage
  const { data: intelligence, isLoading: intelligenceLoading } = useLearningIntelligence()
  const { data: funnel, isLoading: funnelLoading } = useParameterProposalFunnel()
  const [selectedEvidence, setSelectedEvidence] = useState<ParameterEvidence | null>(null)
  const evidenceColumns = useMemo(() => buildEvidenceColumns((row) => setSelectedEvidence(row)), [])
  const depth = intelligence?.learning_depth
  const waitQuality = intelligence?.wait_decision_quality
  const missed = intelligence?.missed_opportunity_learning
  const overfit = intelligence?.overfit_risk_monitor
  const { data: cost24h, isLoading: cost24hLoading } = useLlmCost24h()
  const { data: cost7d } = useLlmCost7d()
  const { data: audit, isLoading: auditLoading } = useMultiAgentAudit()
  const { data: shadowStatus, isLoading: shadowLoading } = useShadowOutcomesStatus()
  const { data: shadowRecent } = useShadowOutcomesRecent(10)

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
              Learning Cockpit — GrowBot/River
            </h1>
            <p className='text-muted-foreground'>
              Is the learning layer ready to make reliable proposals?
            </p>
          </div>
          {!isLoading && data?.river_available !== undefined && (
            <StatusBadge tone={data.river_available ? 'safe' : 'warning'}>
              River {data.river_available ? 'available' : 'unavailable'}
              {data.river_backend ? ` · ${data.river_backend}` : ''}
            </StatusBadge>
          )}
        </div>

        {isError && (
          <Alert variant='destructive' className='mb-4'>
            <AlertTitle>Could not load learning status</AlertTitle>
            <AlertDescription>The learning status tool failed to run.</AlertDescription>
          </Alert>
        )}

        {!isLoading && data?.next_operator_action && (
          <Alert className='mb-4'>
            <AlertTitle>Next operator action</AlertTitle>
            <AlertDescription>{data.next_operator_action}</AlertDescription>
          </Alert>
        )}

        {isLoading ? (
          <div className='grid gap-4 sm:grid-cols-2 lg:grid-cols-3'>
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className='h-32' />
            ))}
          </div>
        ) : (
          <>
            <div className='grid gap-4 sm:grid-cols-2 lg:grid-cols-4'>
              <Card>
                <CardHeader>
                  <CardTitle className='text-sm font-medium'>Episodes</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className='text-2xl font-bold'>{data?.episode_count ?? '—'}</div>
                  <p className='text-xs text-muted-foreground'>
                    {data?.new_memory_episodes ?? 0} new this run
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle className='text-sm font-medium'>Memory total</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className='text-2xl font-bold'>{data?.memory_total ?? '—'}</div>
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle className='text-sm font-medium'>Active proposals</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className='text-2xl font-bold'>{data?.proposal_count ?? 0}</div>
                  <p className='text-xs text-muted-foreground'>
                    {data?.blocked_proposal_count ?? 0} blocked
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle className='text-sm font-medium'>Known regime episodes</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className='text-2xl font-bold'>
                    {data?.regime_evidence?.known_regime_episode_count ?? '—'}
                  </div>
                </CardContent>
              </Card>
            </div>

            <Card className='mt-4'>
              <CardHeader>
                <CardTitle className='text-sm font-medium'>Data contract coverage</CardTitle>
              </CardHeader>
              <CardContent className='grid gap-4 sm:grid-cols-2'>
                <CoverageBar label='Feature snapshot coverage' pct={coverage?.nonempty_feature_state_pct} />
                <CoverageBar label='Known market regime coverage' pct={coverage?.known_market_regime_pct} />
              </CardContent>
            </Card>

            <Card className='mt-4'>
              <CardHeader>
                <CardTitle className='text-sm font-medium'>Readiness tiers</CardTitle>
              </CardHeader>
              <CardContent className='flex flex-wrap gap-2'>
                {Object.entries(READINESS_TIER_LABELS).map(([key, label]) => {
                  const ready = data?.product_readiness?.[key]
                  return (
                    <Badge
                      key={key}
                      variant='outline'
                      className={
                        ready
                          ? 'border-emerald-600/30 bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
                          : 'text-muted-foreground'
                      }
                    >
                      {ready ? (
                        <CheckCircle2 className='size-3.5' />
                      ) : (
                        <Circle className='size-3.5' />
                      )}
                      {label}
                    </Badge>
                  )
                })}
              </CardContent>
            </Card>

            {(data?.product_readiness_blockers?.length ?? 0) > 0 && (
              <Card className='mt-4'>
                <CardHeader>
                  <CardTitle className='text-sm font-medium'>Learning blockers</CardTitle>
                </CardHeader>
                <CardContent>
                  <ul className='list-inside list-disc text-sm text-muted-foreground'>
                    {data?.product_readiness_blockers?.map((b) => <li key={b}>{b}</li>)}
                  </ul>
                </CardContent>
              </Card>
            )}
          </>
        )}

        <h2 className='mt-8 text-xl font-bold tracking-tight'>Adaptive learning intelligence</h2>
        <p className='mb-4 text-muted-foreground'>
          Deeper, evidence-tiered view across all learnable parameters. Preview only -- nothing
          here is ever applied automatically; everything stops at operator_review_candidate.
        </p>

        {intelligenceLoading || funnelLoading ? (
          <div className='grid gap-4 sm:grid-cols-2 lg:grid-cols-3'>
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className='h-32' />
            ))}
          </div>
        ) : (
          <>
            <div className='grid gap-4 sm:grid-cols-2 lg:grid-cols-4'>
              <Card>
                <CardHeader>
                  <CardTitle className='text-sm font-medium'>Learning depth</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className='text-2xl font-bold'>{depth?.decision_outcomes_resolved ?? '—'}</div>
                  <p className='text-xs text-muted-foreground'>
                    resolved decision outcomes · {depth?.decision_outcomes_pending ?? 0} pending ·{' '}
                    {depth?.execution_outcomes_count ?? 0} execution outcomes
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle className='text-sm font-medium'>Wait decision quality</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className='text-2xl font-bold'>
                    {waitQuality?.wait_decision_quality_pct != null
                      ? `${(waitQuality.wait_decision_quality_pct * 100).toFixed(0)}%`
                      : '—'}
                  </div>
                  <p className='text-xs text-muted-foreground'>
                    {waitQuality?.correct_count ?? 0} correct vs {waitQuality?.missed_opportunity_count ?? 0}{' '}
                    missed, of {waitQuality?.resolved_wait_like_decisions ?? 0} wait/watch/skip decisions
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle className='text-sm font-medium'>Missed opportunities</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className='text-2xl font-bold'>{missed?.missed_opportunity_count ?? 0}</div>
                  <p className='text-xs text-muted-foreground'>
                    top ticker: {Object.keys(missed?.by_ticker ?? {})[0] ?? 'none recorded'}
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle className='text-sm font-medium'>Overfit risk monitor</CardTitle>
                </CardHeader>
                <CardContent className='flex gap-2'>
                  <StatusBadge tone='safe'>low {overfit?.low ?? 0}</StatusBadge>
                  <StatusBadge tone='warning'>medium {overfit?.medium ?? 0}</StatusBadge>
                  <StatusBadge tone='danger'>high {overfit?.high ?? 0}</StatusBadge>
                </CardContent>
              </Card>
            </div>

            <Card className='mt-4'>
              <CardHeader>
                <CardTitle className='text-sm font-medium'>Proposal maturity funnel</CardTitle>
              </CardHeader>
              <CardContent className='space-y-3'>
                {TIER_FUNNEL_ORDER.map((tier) => {
                  const count = funnel?.funnel_counts?.[tier] ?? 0
                  const total = funnel?.total_parameters || 1
                  return (
                    <div key={tier} className='space-y-1'>
                      <div className='flex items-center justify-between text-sm'>
                        <span className='text-muted-foreground'>{TIER_FUNNEL_LABEL[tier]}</span>
                        <span className='font-medium'>{count}</span>
                      </div>
                      <Progress value={(count / total) * 100} />
                    </div>
                  )
                })}
                <p className='pt-1 text-xs text-muted-foreground'>{funnel?.apply_ready_policy}</p>
              </CardContent>
            </Card>

            {(missed?.by_ticker || missed?.by_setup_type) && (
              <Card className='mt-4'>
                <CardHeader>
                  <CardTitle className='text-sm font-medium'>Missed opportunity learning</CardTitle>
                </CardHeader>
                <CardContent className='grid gap-4 sm:grid-cols-2'>
                  <div>
                    <p className='mb-1 font-medium text-muted-foreground'>By ticker</p>
                    <ul className='space-y-1 text-sm'>
                      {Object.entries(missed?.by_ticker ?? {}).map(([ticker, count]) => (
                        <li key={ticker} className='flex justify-between'>
                          <span>{ticker}</span>
                          <span className='font-mono'>{count}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <p className='mb-1 font-medium text-muted-foreground'>By setup type</p>
                    <ul className='space-y-1 text-sm'>
                      {Object.entries(missed?.by_setup_type ?? {}).map(([setup, count]) => (
                        <li key={setup} className='flex justify-between'>
                          <span>{setup}</span>
                          <span className='font-mono'>{count}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </CardContent>
              </Card>
            )}

            <Card className='mt-4'>
              <CardHeader>
                <CardTitle className='text-sm font-medium'>
                  Parameter evidence ({intelligence?.parameter_evidence?.length ?? 0})
                </CardTitle>
              </CardHeader>
              <CardContent>
                <DataTable
                  columns={evidenceColumns}
                  data={intelligence?.parameter_evidence ?? []}
                  pageSize={15}
                  emptyMessage='No parameter evidence found.'
                />
              </CardContent>
            </Card>
          </>
        )}

        <h2 className='mt-8 text-xl font-bold tracking-tight'>LLM cost & multi-agent health</h2>
        <p className='mb-4 text-muted-foreground'>
          Read-only cost/usage ledger and pipeline-correctness audit. No prompt or completion
          content is ever logged or displayed here -- metadata only.
        </p>

        {cost24hLoading || auditLoading ? (
          <div className='grid gap-4 sm:grid-cols-2 lg:grid-cols-4'>
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className='h-32' />
            ))}
          </div>
        ) : (
          <>
            <div className='grid gap-4 sm:grid-cols-2 lg:grid-cols-4'>
              <Card>
                <CardHeader>
                  <CardTitle className='text-sm font-medium'>LLM cost (24h)</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className='text-2xl font-bold'>
                    ${(cost24h?.total_estimated_cost_usd ?? 0).toFixed(4)}
                  </div>
                  <p className='text-xs text-muted-foreground'>
                    {cost24h?.total_calls ?? 0} calls · ${(cost24h?.avg_cost_per_call_usd ?? 0).toFixed(6)} avg/call
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle className='text-sm font-medium'>LLM cost (7d)</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className='text-2xl font-bold'>
                    ${(cost7d?.total_estimated_cost_usd ?? 0).toFixed(4)}
                  </div>
                  <p className='text-xs text-muted-foreground'>{cost7d?.total_calls ?? 0} calls</p>
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle className='text-sm font-medium'>No-action cost (24h)</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className='text-2xl font-bold'>{(cost24h?.no_action_cost_pct ?? 0).toFixed(1)}%</div>
                  <p className='text-xs text-muted-foreground'>
                    {cost24h?.no_action_calls ?? 0} wait/skip/reject calls · {cost24h?.retried_attempts ?? 0} retried attempts
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle className='text-sm font-medium'>Pipeline status</CardTitle>
                </CardHeader>
                <CardContent>
                  <StatusBadge tone={audit?.conclusion?.multi_agent_system_correctness === 'working_as_designed' ? 'safe' : 'warning'}>
                    {audit?.conclusion?.multi_agent_system_correctness ?? 'unknown'}
                  </StatusBadge>
                  <p className='mt-2 text-xs text-muted-foreground'>
                    {audit?.llm_layer_count ?? 0} LLM layers · {audit?.deterministic_layer_count ?? 0} deterministic layers
                  </p>
                </CardContent>
              </Card>
            </div>

            <Card className='mt-4'>
              <CardHeader>
                <CardTitle className='text-sm font-medium'>Cost per agent (24h)</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className='space-y-1 text-sm'>
                  {Object.entries(cost24h?.by_agent ?? {})
                    .sort((a, b) => (b[1]?.estimated_cost_usd ?? 0) - (a[1]?.estimated_cost_usd ?? 0))
                    .map(([agent, stats]) => (
                      <li key={agent} className='flex justify-between'>
                        <span>{agent}</span>
                        <span className='font-mono'>
                          ${stats.estimated_cost_usd.toFixed(4)} · {stats.calls} calls · {stats.avg_tokens_per_call} avg tok
                        </span>
                      </li>
                    ))}
                  {Object.keys(cost24h?.by_agent ?? {}).length === 0 && (
                    <li className='text-muted-foreground'>No LLM calls recorded in this window yet.</li>
                  )}
                </ul>
              </CardContent>
            </Card>

            <Card className='mt-4'>
              <CardHeader>
                <CardTitle className='text-sm font-medium'>Top 10 most expensive calls (24h)</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className='space-y-1 text-sm'>
                  {(cost24h?.top_10_expensive_calls ?? []).map((call, i) => (
                    <li key={i} className='flex justify-between'>
                      <span>
                        {call.ticker} · {call.agent} · {call.model}
                      </span>
                      <span className='font-mono'>
                        ${(call.estimated_cost_usd ?? 0).toFixed(6)} ({call.decision_result ?? 'n/a'})
                      </span>
                    </li>
                  ))}
                  {(cost24h?.top_10_expensive_calls?.length ?? 0) === 0 && (
                    <li className='text-muted-foreground'>No LLM calls recorded in this window yet.</li>
                  )}
                </ul>
              </CardContent>
            </Card>

            <Card className='mt-4'>
              <CardHeader>
                <CardTitle className='text-sm font-medium'>
                  Multi-agent layers ({audit?.layers?.length ?? 0})
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ul className='space-y-2 text-sm'>
                  {(audit?.layers ?? []).map((layer) => (
                    <li key={layer.name} className='flex items-start justify-between gap-4'>
                      <div>
                        <span className='font-medium'>{layer.label}</span>
                        <p className='text-xs text-muted-foreground'>{layer.skip_conditions}</p>
                      </div>
                      <Badge variant='outline' className={layer.is_llm ? 'border-amber-600/30 bg-amber-500/15 text-amber-600 dark:text-amber-400' : 'text-muted-foreground'}>
                        {layer.is_llm ? `LLM · ${layer.provider}` : 'deterministic'}
                      </Badge>
                    </li>
                  ))}
                </ul>
                <p className='mt-3 text-xs text-muted-foreground'>
                  Prompt inventory: {audit?.prompt_inventory?.prompts?.length ?? 0} templates ·{' '}
                  secrets check: <strong>{audit?.prompt_inventory?.secrets_in_prompts_conclusion ?? 'unknown'}</strong>
                </p>
              </CardContent>
            </Card>

            {(cost24h?.recommendations?.length ?? 0) > 0 && (
              <Card className='mt-4'>
                <CardHeader>
                  <CardTitle className='text-sm font-medium'>Cost-reduction recommendations</CardTitle>
                </CardHeader>
                <CardContent>
                  <ul className='list-inside list-disc space-y-1 text-sm text-muted-foreground'>
                    {cost24h?.recommendations?.map((rec) => <li key={rec}>{rec}</li>)}
                  </ul>
                </CardContent>
              </Card>
            )}
          </>
        )}
        {/* ----------------------------------------------------------------- */}
        {/* Shadow Outcome Accelerator                                        */}
        {/* ----------------------------------------------------------------- */}
        <h2 className='mt-8 text-xl font-bold tracking-tight'>Shadow Outcome Accelerator</h2>
        <p className='mb-4 text-muted-foreground'>
          Every full-cycle ticker decision is recorded and hypothetically evaluated after 1h / 4h / 24h
          using local price data. Evidence-only — no live orders, no Coinbase calls, no parameter mutation.
        </p>

        {shadowLoading ? (
          <div className='grid gap-4 sm:grid-cols-2 lg:grid-cols-4'>
            {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className='h-32' />)}
          </div>
        ) : (
          <>
            <div className='grid gap-4 sm:grid-cols-2 lg:grid-cols-4'>
              <Card>
                <CardHeader><CardTitle className='text-sm font-medium'>Shadow decisions</CardTitle></CardHeader>
                <CardContent>
                  <div className='text-2xl font-bold'>{shadowStatus?.total_shadow_decisions ?? 0}</div>
                  <p className='text-xs text-muted-foreground'>
                    {shadowStatus?.status_counts?.pending ?? 0} pending · {shadowStatus?.status_counts?.complete ?? 0} complete
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle className='text-sm font-medium'>Usable evidence</CardTitle></CardHeader>
                <CardContent>
                  <div className='text-2xl font-bold'>{shadowStatus?.usable_evidence_count ?? 0}</div>
                  <p className='text-xs text-muted-foreground'>
                    quality score: {((shadowStatus?.evidence_quality_score ?? 0) * 100).toFixed(0)}%
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle className='text-sm font-medium'>Sufficient for optimisation</CardTitle></CardHeader>
                <CardContent>
                  <StatusBadge tone={shadowStatus?.sufficient_for_optimization ? 'safe' : 'warning'}>
                    {shadowStatus?.sufficient_for_optimization ? 'Yes' : 'Not yet'}
                  </StatusBadge>
                  <p className='mt-2 text-xs text-muted-foreground'>{shadowStatus?.sufficiency_note}</p>
                </CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle className='text-sm font-medium'>Safety flags</CardTitle></CardHeader>
                <CardContent className='flex flex-col gap-1'>
                  <StatusBadge tone='safe'>No live orders</StatusBadge>
                  <StatusBadge tone='safe'>No Coinbase calls</StatusBadge>
                  <StatusBadge tone='safe'>No param mutation</StatusBadge>
                </CardContent>
              </Card>
            </div>

            <div className='mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3'>
              <Card>
                <CardHeader><CardTitle className='text-sm font-medium'>Evaluation horizons</CardTitle></CardHeader>
                <CardContent className='space-y-2 text-sm'>
                  {(['1h', '4h', '24h'] as const).map((hk) => {
                    const h = shadowStatus?.evaluations_by_horizon?.[hk] ?? { pending: 0, complete: 0, insufficient_data: 0 }
                    return (
                      <div key={hk} className='flex items-center justify-between'>
                        <span className='text-muted-foreground'>{hk}</span>
                        <span className='font-mono text-xs'>
                          {h.complete} done · {h.pending} pending · {h.insufficient_data} insufficient
                        </span>
                      </div>
                    )
                  })}
                </CardContent>
              </Card>

              <Card>
                <CardHeader><CardTitle className='text-sm font-medium'>Per-ticker coverage</CardTitle></CardHeader>
                <CardContent>
                  <ul className='space-y-1 text-sm'>
                    {Object.entries(shadowStatus?.by_ticker ?? {}).map(([ticker, count]) => (
                      <li key={ticker} className='flex justify-between'>
                        <span className='font-mono'>{ticker}</span>
                        <span>{count}</span>
                      </li>
                    ))}
                    {Object.keys(shadowStatus?.by_ticker ?? {}).length === 0 && (
                      <li className='text-muted-foreground'>No decisions yet.</li>
                    )}
                  </ul>
                </CardContent>
              </Card>

              <Card>
                <CardHeader><CardTitle className='text-sm font-medium'>Per-regime coverage</CardTitle></CardHeader>
                <CardContent>
                  <ul className='space-y-1 text-sm'>
                    {Object.entries(shadowStatus?.by_regime ?? {}).map(([regime, count]) => (
                      <li key={regime} className='flex justify-between'>
                        <span>{regime}</span>
                        <span className='font-mono'>{count}</span>
                      </li>
                    ))}
                    {Object.keys(shadowStatus?.by_regime ?? {}).length === 0 && (
                      <li className='text-muted-foreground'>No regimes yet.</li>
                    )}
                  </ul>
                </CardContent>
              </Card>
            </div>

            {((shadowStatus?.top_missed_opportunity_patterns?.length ?? 0) > 0 ||
              (shadowStatus?.top_bad_trade_avoided_patterns?.length ?? 0) > 0) && (
              <div className='mt-4 grid gap-4 sm:grid-cols-2'>
                <Card>
                  <CardHeader><CardTitle className='text-sm font-medium'>Missed opportunity patterns</CardTitle></CardHeader>
                  <CardContent>
                    <ul className='space-y-1 text-sm'>
                      {shadowStatus?.top_missed_opportunity_patterns?.map((p) => (
                        <li key={p.setup_type} className='flex justify-between'>
                          <span>{p.setup_type}</span>
                          <span className='font-mono'>{p.count}</span>
                        </li>
                      ))}
                    </ul>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader><CardTitle className='text-sm font-medium'>Bad trade avoided patterns</CardTitle></CardHeader>
                  <CardContent>
                    <ul className='space-y-1 text-sm'>
                      {shadowStatus?.top_bad_trade_avoided_patterns?.map((p) => (
                        <li key={p.decision} className='flex justify-between'>
                          <span>{p.decision}</span>
                          <span className='font-mono'>{p.count}</span>
                        </li>
                      ))}
                    </ul>
                  </CardContent>
                </Card>
              </div>
            )}

            {(shadowRecent?.records?.length ?? 0) > 0 && (
              <Card className='mt-4'>
                <CardHeader><CardTitle className='text-sm font-medium'>Recent shadow decisions</CardTitle></CardHeader>
                <CardContent>
                  <div className='overflow-x-auto'>
                    <table className='w-full text-xs'>
                      <thead>
                        <tr className='border-b text-left text-muted-foreground'>
                          <th className='pb-1 pr-3'>Time</th>
                          <th className='pb-1 pr-3'>Ticker</th>
                          <th className='pb-1 pr-3'>Decision</th>
                          <th className='pb-1 pr-3'>Regime</th>
                          <th className='pb-1 pr-3'>Bull</th>
                          <th className='pb-1 pr-3'>Bear</th>
                          <th className='pb-1 pr-3'>1h</th>
                          <th className='pb-1 pr-3'>4h</th>
                          <th className='pb-1'>24h</th>
                        </tr>
                      </thead>
                      <tbody>
                        {shadowRecent?.records?.map((r) => (
                          <tr key={r.shadow_id} className='border-b last:border-0'>
                            <td className='py-1 pr-3 font-mono'>
                              {r.timestamp ? new Date(r.timestamp).toLocaleTimeString() : '—'}
                            </td>
                            <td className='pr-3 font-mono'>{r.ticker ?? '—'}</td>
                            <td className='pr-3'>{r.decision ?? '—'}</td>
                            <td className='pr-3'>{r.market_regime ?? '—'}</td>
                            <td className='pr-3'>{r.bull_score != null ? (r.bull_score * 100).toFixed(0) + '%' : '—'}</td>
                            <td className='pr-3'>{r.bear_score != null ? (r.bear_score * 100).toFixed(0) + '%' : '—'}</td>
                            {(['1h', '4h', '24h'] as const).map((hk) => {
                              const ev = r.evaluations?.[hk]
                              const label = ev == null
                                ? '⏳'
                                : ev?.status === 'insufficient_data'
                                ? '—'
                                : ev?.missed_opportunity_label === 'yes'
                                ? '⚠️ missed'
                                : ev?.bad_trade_avoided_label === 'yes'
                                ? '✓ avoided'
                                : ev?.status === 'complete'
                                ? '✓'
                                : '⏳'
                              return <td key={hk} className='pr-3'>{label}</td>
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>
            )}
          </>
        )}

      </Main>

      <Sheet open={!!selectedEvidence} onOpenChange={(open) => !open && setSelectedEvidence(null)}>
        <SheetContent className='w-full sm:max-w-lg'>
          {selectedEvidence && (
            <>
              <SheetHeader>
                <SheetTitle className='font-mono text-sm'>{selectedEvidence.parameter}</SheetTitle>
                <SheetDescription>
                  {selectedEvidence.category} · tier: {selectedEvidence.tier}
                </SheetDescription>
              </SheetHeader>
              <div className='space-y-4 px-4 text-sm'>
                <DetailRow label='Why' value={selectedEvidence.why} />
                <DetailRow
                  label='Current → Proposed'
                  value={`${String(selectedEvidence.current_value ?? '—')} → ${String(selectedEvidence.proposed_value ?? '—')}`}
                />
                <DetailRow label='Expected effect' value={selectedEvidence.expected_effect} />
                <DetailRow label='Risk impact' value={selectedEvidence.risk_impact} />
                <DetailRow
                  label='Regimes seen'
                  value={selectedEvidence.regimes_seen.length ? selectedEvidence.regimes_seen.join(', ') : 'none recorded'}
                />
                <DetailRow
                  label='Tickers seen'
                  value={selectedEvidence.tickers_seen.length ? selectedEvidence.tickers_seen.join(', ') : 'none recorded'}
                />
                <DetailRow
                  label='Overfit risk'
                  value={`${selectedEvidence.overfit_risk} -- ${selectedEvidence.overfit_reasons.join('; ')}`}
                />
                <DetailRow label='Why not apply-ready' value={selectedEvidence.why_not_apply_ready} />
                <DetailRow label='Next data needed' value={selectedEvidence.next_data_needed} />
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
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
