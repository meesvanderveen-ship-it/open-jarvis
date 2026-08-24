import { useMemo, useState } from 'react'
import { formatDistanceToNow } from 'date-fns'
import { type ColumnDef } from '@tanstack/react-table'
import { ExternalLink } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { DataTable, DataTableColumnHeader } from '@/components/data-table'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { type ReportEntry, useReportDetail, useReportList } from './api'

export function Reports() {
  const { data, isLoading } = useReportList()
  const [category, setCategory] = useState('all')
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const categories = useMemo(
    () => Array.from(new Set((data?.reports ?? []).map((r) => r.category))).sort(),
    [data]
  )
  const filtered = (data?.reports ?? []).filter(
    (r) => category === 'all' || r.category === category
  )

  const columns: ColumnDef<ReportEntry>[] = useMemo(
    () => [
      {
        accessorKey: 'category',
        header: ({ column }) => <DataTableColumnHeader column={column} title='Category' />,
      },
      {
        accessorKey: 'name',
        header: ({ column }) => <DataTableColumnHeader column={column} title='Name' />,
        cell: ({ row }) => (
          <button
            className='text-start font-mono text-xs underline-offset-2 hover:underline'
            onClick={() => setSelectedId(row.original.id)}
          >
            {row.original.name}
          </button>
        ),
      },
      {
        id: 'latest',
        header: 'Latest',
        cell: ({ row }) => (row.original.is_latest ? <Badge variant='outline'>latest</Badge> : null),
      },
      {
        accessorKey: 'size_bytes',
        header: ({ column }) => <DataTableColumnHeader column={column} title='Size' />,
        cell: ({ row }) => `${(row.original.size_bytes / 1024).toFixed(1)} KB`,
      },
      {
        accessorKey: 'modified_at',
        header: ({ column }) => <DataTableColumnHeader column={column} title='Modified' />,
        cell: ({ row }) =>
          formatDistanceToNow(new Date(row.original.modified_at * 1000), { addSuffix: true }),
      },
    ],
    []
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
            <h1 className='text-2xl font-bold tracking-tight'>Reports & Audits</h1>
            <p className='text-muted-foreground'>
              Readiness, live-run, GrowBot/River, audit, and backtest reports — newest first.
            </p>
          </div>
          <Select value={category} onValueChange={setCategory}>
            <SelectTrigger className='w-48'>
              <SelectValue placeholder='Category' />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value='all'>All categories</SelectItem>
              {categories.map((c) => (
                <SelectItem key={c} value={c}>
                  {c}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {isLoading ? (
          <Skeleton className='h-96' />
        ) : (
          <Card>
            <CardHeader>
              <CardTitle className='text-sm font-medium'>{filtered.length} report(s)</CardTitle>
            </CardHeader>
            <CardContent>
              <DataTable columns={columns} data={filtered} pageSize={20} emptyMessage='No reports found.' />
            </CardContent>
          </Card>
        )}
      </Main>

      <ReportDetailSheet id={selectedId} onClose={() => setSelectedId(null)} />
    </>
  )
}

function ReportDetailSheet({ id, onClose }: { id: string | null; onClose: () => void }) {
  const { data, isLoading } = useReportDetail(id)

  return (
    <Sheet open={!!id} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className='w-full sm:max-w-2xl'>
        <SheetHeader>
          <SheetTitle className='font-mono text-sm'>{id}</SheetTitle>
          <SheetDescription>
            {data && (
              <a
                href={`/api/reports/${id}`}
                target='_blank'
                rel='noreferrer'
                className='inline-flex items-center gap-1 underline-offset-2 hover:underline'
              >
                Open raw <ExternalLink className='size-3' />
              </a>
            )}
          </SheetDescription>
        </SheetHeader>
        <div className='overflow-y-auto px-4'>
          {isLoading ? (
            <Skeleton className='h-64' />
          ) : data?.truncated ? (
            <p className='text-sm text-muted-foreground'>
              File is {(data.size_bytes / 1024 / 1024).toFixed(1)} MB — too large to render
              inline. Use "Open raw" to fetch it directly.
            </p>
          ) : typeof data?.content === 'string' ? (
            <pre className='whitespace-pre-wrap text-xs'>{data.content}</pre>
          ) : (
            <pre className='overflow-auto text-xs'>{JSON.stringify(data?.content, null, 2)}</pre>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}
