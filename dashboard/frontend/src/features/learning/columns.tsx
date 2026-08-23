import { type ColumnDef } from '@tanstack/react-table'
import { Button } from '@/components/ui/button'
import { DataTableColumnHeader } from '@/components/data-table'
import { StatusBadge } from '@/components/status-badge'
import type { ParameterEvidence } from './api'

const TIER_LABEL: Record<string, string> = {
  observed_signal: 'Observed signal',
  shadow_candidate: 'Shadow candidate',
  backtest_candidate: 'Backtest candidate',
  walk_forward_candidate: 'Walk-forward candidate',
  operator_review_candidate: 'Operator review',
  apply_ready_candidate: 'Apply ready',
}

const OVERFIT_TONE: Record<string, 'safe' | 'warning' | 'danger' | 'info'> = {
  low: 'safe',
  medium: 'warning',
  high: 'danger',
}

const DIRECTION_LABEL: Record<string, string> = {
  loosen: 'Loosen',
  tighten: 'Tighten',
  keep: 'Keep',
  mixed: 'Mixed',
  no_signal: 'No signal',
}

export function buildEvidenceColumns(
  onShowDetail: (row: ParameterEvidence) => void
): ColumnDef<ParameterEvidence>[] {
  return [
    {
      accessorKey: 'parameter',
      header: ({ column }) => <DataTableColumnHeader column={column} title='Parameter' />,
      cell: ({ row }) => <span className='font-mono text-xs font-medium'>{row.original.parameter}</span>,
    },
    { accessorKey: 'category', header: 'Category' },
    {
      id: 'tier',
      header: 'Tier',
      cell: ({ row }) => (
        <StatusBadge tone={row.original.tier === 'observed_signal' ? 'info' : 'safe'}>
          {TIER_LABEL[row.original.tier] ?? row.original.tier}
        </StatusBadge>
      ),
    },
    {
      accessorKey: 'direction',
      header: 'Direction',
      cell: ({ row }) => (
        <StatusBadge tone={row.original.direction === 'keep' ? 'info' : 'warning'}>
          {DIRECTION_LABEL[row.original.direction] ?? row.original.direction}
        </StatusBadge>
      ),
    },
    {
      accessorKey: 'confidence',
      header: ({ column }) => <DataTableColumnHeader column={column} title='Confidence' />,
      cell: ({ row }) => `${(row.original.confidence * 100).toFixed(0)}%`,
    },
    {
      accessorKey: 'evidence_count',
      header: ({ column }) => <DataTableColumnHeader column={column} title='Evidence' />,
    },
    {
      id: 'overfit_risk',
      header: 'Overfit risk',
      cell: ({ row }) => (
        <StatusBadge tone={OVERFIT_TONE[row.original.overfit_risk] ?? 'info'}>
          {row.original.overfit_risk}
        </StatusBadge>
      ),
    },
    {
      accessorKey: 'proposal_score',
      header: ({ column }) => <DataTableColumnHeader column={column} title='Score' />,
      cell: ({ row }) => row.original.proposal_score.toFixed(2),
    },
    {
      id: 'detail',
      header: '',
      cell: ({ row }) => (
        <Button variant='ghost' size='sm' onClick={() => onShowDetail(row.original)}>
          Evidence
        </Button>
      ),
    },
  ]
}
