import { useMemo, useState } from 'react'
import { ChevronDown, ScrollText } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
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
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { StatusBadge } from '@/components/status-badge'
import { ThemeSwitch } from '@/components/theme-switch'
import { useOpportunities } from '@/features/opportunities/api'
import { usePrompts, useTickerTrace } from './api'

export function AgentTrace() {
  const { data: opportunities } = useOpportunities()
  const tickers = useMemo(
    () => (opportunities?.opportunities ?? []).map((o) => o.ticker),
    [opportunities]
  )
  const [ticker, setTicker] = useState<string | null>(null)
  const effectiveTicker = ticker ?? tickers[0] ?? null
  const { data, isLoading } = useTickerTrace(effectiveTicker)
  const [promptsOpen, setPromptsOpen] = useState(false)

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
              Multi-Agent Decision Trace
            </h1>
            <p className='text-muted-foreground'>
              Hard gate → synthesis → judge → risk/D2/D3 → outcome → learning, per ticker.
            </p>
          </div>
          <div className='flex items-center gap-2'>
            <Select value={effectiveTicker ?? undefined} onValueChange={setTicker}>
              <SelectTrigger className='w-40'>
                <SelectValue placeholder='Select ticker' />
              </SelectTrigger>
              <SelectContent>
                {tickers.map((t) => (
                  <SelectItem key={t} value={t}>
                    {t}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button variant='outline' size='sm' onClick={() => setPromptsOpen(true)}>
              <ScrollText className='size-3.5' />
              Prompt templates
            </Button>
          </div>
        </div>

        {isLoading ? (
          <div className='space-y-3'>
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className='h-20' />
            ))}
          </div>
        ) : data ? (
          <div className='space-y-3'>
            <div className='flex items-center gap-2 text-sm text-muted-foreground'>
              <span>latest decision: </span>
              <Badge variant='outline'>{data.decision ?? 'unknown'}</Badge>
              <span>{data.decision_created_at}</span>
            </div>
            {data.steps.map((step, idx) => (
              <TraceStepCard key={step.step} index={idx} step={step} />
            ))}
          </div>
        ) : (
          <p className='text-muted-foreground'>Select a ticker to see its decision trace.</p>
        )}
      </Main>

      <Sheet open={promptsOpen} onOpenChange={setPromptsOpen}>
        <SheetContent className='w-full sm:max-w-xl'>
          <SheetHeader>
            <SheetTitle>Prompt templates</SheetTitle>
            <SheetDescription>
              Static templates from bot/prompts.py — never shown with live-filled
              market data, just the instructions sent to each LLM step.
            </SheetDescription>
          </SheetHeader>
          <PromptList />
        </SheetContent>
      </Sheet>
    </>
  )
}

function TraceStepCard({ step, index }: { step: { step: string; label: string; status: string; summary: unknown }; index: number }) {
  const [open, setOpen] = useState(false)
  const tone = step.status === 'no_data' || step.status === 'no_open_position' || step.status === 'no_orders' ? 'info' : 'safe'

  return (
    <Card>
      <Collapsible open={open} onOpenChange={setOpen}>
        <CardHeader className='flex flex-row items-center justify-between space-y-0'>
          <CardTitle className='flex items-center gap-2 text-sm font-medium'>
            <span className='flex size-6 items-center justify-center rounded-full bg-muted text-xs'>
              {index + 1}
            </span>
            {step.label}
          </CardTitle>
          <div className='flex items-center gap-2'>
            <StatusBadge tone={tone}>{step.status}</StatusBadge>
            <CollapsibleTrigger asChild>
              <Button variant='ghost' size='sm'>
                <ChevronDown className={open ? 'rotate-180 transition-transform' : 'transition-transform'} />
              </Button>
            </CollapsibleTrigger>
          </div>
        </CardHeader>
        <CollapsibleContent>
          <CardContent>
            <pre className='max-h-80 overflow-auto rounded-md bg-muted p-3 text-xs'>
              {JSON.stringify(step.summary, null, 2) ?? 'null'}
            </pre>
          </CardContent>
        </CollapsibleContent>
      </Collapsible>
    </Card>
  )
}

function PromptList() {
  const { data, isLoading } = usePrompts()
  const [expanded, setExpanded] = useState<string | null>(null)

  if (isLoading) return <Skeleton className='m-4 h-64' />

  return (
    <div className='space-y-2 overflow-y-auto px-4'>
      {data?.prompts.map((p) => (
        <Collapsible
          key={p.name}
          open={expanded === p.name}
          onOpenChange={(open) => setExpanded(open ? p.name : null)}
        >
          <CollapsibleTrigger asChild>
            <Button variant='outline' className='w-full justify-between font-mono text-xs'>
              {p.name}
              <ChevronDown className='size-3.5' />
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <p className='px-2 py-1 text-xs text-muted-foreground'>{p.purpose}</p>
            <pre className='max-h-64 overflow-auto rounded-md bg-muted p-2 text-xs whitespace-pre-wrap'>
              {p.text}
            </pre>
          </CollapsibleContent>
        </Collapsible>
      ))}
    </div>
  )
}
