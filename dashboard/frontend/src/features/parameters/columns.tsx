import { type ColumnDef } from '@tanstack/react-table'
import { Button } from '@/components/ui/button'
import { DataTableColumnHeader } from '@/components/data-table'
import { StatusBadge } from '@/components/status-badge'
import type { ParameterProposal } from './api'

const DIRECTION_LABEL: Record<string, string> = {
  loosen: 'Loosen',
  tighten: 'Tighten',
  keep: 'Keep',
}

const SAFETY_TONE: Record<ParameterProposal['safety_status'], 'safe' | 'warning' | 'danger' | 'info'> = {
  safe_to_activate: 'safe',
  needs_more_evidence: 'warning',
  blocked: 'danger',
  no_active_proposal: 'info',
}

const APPLY_TONE: Record<ParameterProposal['apply_status'], 'safe' | 'warning' | 'danger' | 'info'> = {
  ready_for_review: 'safe',
  preview_only: 'warning',
  blocked: 'danger',
  no_active_proposal: 'info',
}

export function buildColumns(onShowDetail: (row: ParameterProposal) => void): ColumnDef<ParameterProposal>[] {
  return [
    {
      accessorKey: 'parameter',
      header: ({ column }) => <DataTableColumnHeader column={column} title='Parameter' />,
      cell: ({ row }) => <span className='font-mono text-xs font-medium'>{row.original.parameter}</span>,
    },
    {
      accessorKey: 'category',
      header: 'Category',
    },
    {
      accessorKey: 'current_value',
      header: 'Current',
      cell: ({ row }) => <span className='font-mono text-xs'>{String(row.original.current_value ?? '—')}</span>,
    },
    {
      accessorKey: 'proposed_value',
      header: 'Proposed',
      cell: ({ row }) => <span className='font-mono text-xs'>{String(row.original.proposed_value ?? '—')}</span>,
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
      cell: ({ row }) =>
        row.original.confidence != null ? `${(row.original.confidence * 100).toFixed(0)}%` : '—',
    },
    {
      accessorKey: 'evidence_count',
      header: ({ column }) => <DataTableColumnHeader column={column} title='Evidence' />,
      cell: ({ row }) => row.original.evidence_count ?? '—',
    },
    {
      id: 'safety_status',
      header: 'Safety',
      cell: ({ row }) => (
        <StatusBadge tone={SAFETY_TONE[row.original.safety_status]}>
          {row.original.safety_status.replace(/_/g, ' ')}
        </StatusBadge>
      ),
    },
    {
      id: 'apply_status',
      header: 'Apply status',
      cell: ({ row }) => (
        <StatusBadge tone={APPLY_TONE[row.original.apply_status]}>
          {row.original.apply_status.replace(/_/g, ' ')}
        </StatusBadge>
      ),
    },
    {
      id: 'operator_ack_needed',
      header: 'ACK needed',
      cell: ({ row }) => (row.original.operator_ack_needed ? 'Yes' : 'No'),
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
