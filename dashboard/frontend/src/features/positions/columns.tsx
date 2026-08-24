import { type ColumnDef } from '@tanstack/react-table'
import { DataTableColumnHeader } from '@/components/data-table'
import { StatusBadge } from '@/components/status-badge'
import type { OrderRow, PositionRow } from './api'

export const positionColumns: ColumnDef<PositionRow>[] = [
  {
    accessorKey: 'ticker',
    header: ({ column }) => <DataTableColumnHeader column={column} title='Ticker' />,
    cell: ({ row }) => <span className='font-mono font-semibold tracking-tight'>{row.original.ticker}</span>,
  },
  {
    id: 'status',
    header: 'Status',
    cell: ({ row }) => (
      <StatusBadge tone={row.original.is_open ? 'info' : 'safe'}>
        {row.original.is_open ? 'open' : 'closed'}
      </StatusBadge>
    ),
  },
  {
    accessorKey: 'entry_price',
    header: ({ column }) => <DataTableColumnHeader column={column} title='Entry price' />,
    cell: ({ row }) => <span className='font-mono tabular-nums'>{row.original.entry_price ?? '—'}</span>,
  },
  {
    accessorKey: 'invalidation_price',
    header: 'Invalidation',
    cell: ({ row }) => <span className='font-mono tabular-nums'>{row.original.invalidation_price ?? '—'}</span>,
  },
  {
    accessorKey: 'd2_plan_status',
    header: 'D2 plan',
  },
  {
    accessorKey: 'd3_exit_status',
    header: 'D3 exit',
  },
  {
    id: 'risk_incomplete',
    header: 'Risk complete',
    cell: ({ row }) => {
      const incomplete = row.original.position_risk_incomplete
      if (!incomplete) return <StatusBadge tone='safe'>complete</StatusBadge>
      // Only an open position with incomplete risk state is an actual,
      // current warning. A closed position can carry this flag as a
      // historical leftover from before it was closed -- still true, but
      // not alarming, so it gets an informational tone instead of danger.
      if (row.original.is_open) {
        return <StatusBadge tone='danger'>incomplete</StatusBadge>
      }
      return <StatusBadge tone='info'>incomplete (historical)</StatusBadge>
    },
  },
  {
    accessorKey: 'close_reason',
    header: 'Close reason',
    cell: ({ row }) => (
      <span className='text-xs text-muted-foreground'>{row.original.close_reason ?? '—'}</span>
    ),
  },
]

export const orderColumns: ColumnDef<OrderRow>[] = [
  {
    accessorKey: 'ticker',
    header: ({ column }) => <DataTableColumnHeader column={column} title='Ticker' />,
    cell: ({ row }) => <span className='font-mono font-semibold tracking-tight'>{row.original.ticker ?? row.original.product_id}</span>,
  },
  {
    accessorKey: 'side',
    header: 'Side',
    cell: ({ row }) => (
      <span
        className={
          row.original.side === 'BUY'
            ? 'font-mono text-xs font-semibold text-emerald-600 dark:text-emerald-400'
            : 'font-mono text-xs font-semibold text-red-600 dark:text-red-400'
        }
      >
        {row.original.side ?? '—'}
      </span>
    ),
  },
  {
    id: 'status',
    header: 'Status',
    cell: ({ row }) => (
      <StatusBadge tone={row.original.is_open ? 'info' : 'safe'}>
        {row.original.status ?? 'unknown'}
      </StatusBadge>
    ),
  },
  {
    accessorKey: 'limit_price',
    header: 'Limit price',
    cell: ({ row }) => <span className='font-mono tabular-nums'>{row.original.limit_price ?? '—'}</span>,
  },
  {
    accessorKey: 'remaining_size',
    header: 'Remaining size',
    cell: ({ row }) => <span className='font-mono tabular-nums'>{row.original.remaining_size ?? '—'}</span>,
  },
  {
    accessorKey: 'filled_base',
    header: 'Filled base',
    cell: ({ row }) => <span className='font-mono tabular-nums'>{row.original.filled_base ?? '—'}</span>,
  },
  {
    accessorKey: 'avg_fill_price',
    header: 'Avg fill price',
    cell: ({ row }) => <span className='font-mono tabular-nums'>{row.original.avg_fill_price ?? '—'}</span>,
  },
  {
    accessorKey: 'phase',
    header: 'Phase',
    cell: ({ row }) => (
      <span className='text-xs text-muted-foreground'>{row.original.phase ?? '—'}</span>
    ),
  },
  {
    accessorKey: 'client_order_id',
    header: 'Client order id',
    cell: ({ row }) => (
      <span className='font-mono text-xs'>{row.original.client_order_id}</span>
    ),
  },
]
