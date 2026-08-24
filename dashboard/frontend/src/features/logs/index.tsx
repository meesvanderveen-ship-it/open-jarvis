import { useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Input } from '@/components/ui/input'
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
import { ThemeSwitch } from '@/components/theme-switch'
import { useLogs } from './api'

const SEVERITY_BORDER: Record<string, string> = {
  error: 'border-l-4 border-l-red-500',
  warning: 'border-l-4 border-l-amber-500',
  warn: 'border-l-4 border-l-amber-500',
  info: 'border-l-4 border-l-blue-500',
}

function previewLine(entry: Record<string, unknown>): string {
  const parts = [entry.generated_at, entry.ticker, entry.event, entry.event_type, entry.status]
    .filter((v) => typeof v === 'string')
    .slice(0, 4)
  return parts.length ? parts.join(' · ') : JSON.stringify(entry).slice(0, 120)
}

export function Logs() {
  const available = useLogs({ type: null })
  const [type, setType] = useState<string | null>(null)
  const [ticker, setTicker] = useState('')
  const [q, setQ] = useState('')
  const logs = useLogs({ type, ticker, q, limit: 100 })

  return (
    <>
      <Header>
        <Search className='me-auto' />
        <ThemeSwitch />
        <ConfigDrawer />
        <ProfileDropdown />
      </Header>

      <Main>
        <div className='mb-4'>
          <h1 className='text-2xl font-bold tracking-tight'>Logs & Evidence Viewer</h1>
          <p className='text-muted-foreground'>
            Tails the bot's own JSONL logs — never the full file, capped reads only.
          </p>
        </div>

        <div className='mb-4 flex flex-wrap items-center gap-2'>
          <Select value={type ?? undefined} onValueChange={setType}>
            <SelectTrigger className='w-64'>
              <SelectValue placeholder='Select a log file' />
            </SelectTrigger>
            <SelectContent>
              {available.data?.available_logs.map((l) => (
                <SelectItem key={l.name} value={l.name}>
                  {l.name} ({(l.size_bytes / 1024).toFixed(0)} KB)
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Input
            placeholder='Filter by ticker (e.g. BTC-USDC)'
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            className='w-56'
          />
          <Input
            placeholder='Free-text search'
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className='w-56'
          />
          {logs.data?.truncated && (
            <Badge variant='outline' className='border-amber-600/30 text-amber-600'>
              scan capped — older entries not searched
            </Badge>
          )}
        </div>

        {!type ? (
          <p className='text-muted-foreground'>Select a log file to view recent entries.</p>
        ) : logs.isLoading ? (
          <div className='space-y-2'>
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className='h-12' />
            ))}
          </div>
        ) : (
          <div className='space-y-2'>
            {(logs.data?.entries ?? []).map((entry, idx) => (
              <LogRow key={idx} entry={entry} />
            ))}
            {(logs.data?.entries ?? []).length === 0 && (
              <p className='text-muted-foreground'>No matching entries.</p>
            )}
          </div>
        )}
      </Main>
    </>
  )
}

function LogRow({ entry }: { entry: Record<string, unknown> }) {
  const [open, setOpen] = useState(false)
  const severity = String(entry.severity ?? entry.level ?? '').toLowerCase()
  const borderClass = SEVERITY_BORDER[severity] ?? 'border-l-4 border-l-transparent'

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <div className={`rounded-md border bg-card ${borderClass}`}>
        <CollapsibleTrigger asChild>
          <Button
            variant='ghost'
            className='w-full justify-between px-3 py-2 font-mono text-xs'
          >
            <span className='truncate text-start'>{previewLine(entry)}</span>
            <ChevronDown className={open ? 'rotate-180 transition-transform' : 'transition-transform'} />
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <pre className='max-h-80 overflow-auto rounded-b-md bg-muted p-3 text-xs'>
            {JSON.stringify(entry, null, 2)}
          </pre>
        </CollapsibleContent>
      </div>
    </Collapsible>
  )
}
