import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
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

export function Logs() {
  const [selectedLog, setSelectedLog] = useState<string | null>(null)
  const [filter, setFilter] = useState('')

  const { data, isLoading, isError } = useLogs({
    type: selectedLog,
    q: filter.trim() || undefined,
  })

  const available = data?.available_logs ?? []
  const entries = data?.entries ?? []

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
          <h1 className='text-2xl font-bold tracking-tight'>Logs</h1>
          <p className='text-muted-foreground'>
            Gestructureerde botlogs, alleen-lezen. Secrets worden door de
            backend weggefilterd voordat ze hier aankomen.
          </p>
        </div>

        <div className='mb-4 flex flex-wrap gap-2'>
          <Select
            value={selectedLog ?? undefined}
            onValueChange={setSelectedLog}
            disabled={isLoading && available.length === 0}
          >
            <SelectTrigger className='w-80'>
              <SelectValue placeholder='Kies een logbestand' />
            </SelectTrigger>
            <SelectContent>
              {available.map((name) => (
                <SelectItem key={name} value={name} className='font-mono text-xs'>
                  {name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Input
            className='w-64'
            placeholder='Filter op tekst...'
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            disabled={!selectedLog}
          />
        </div>

        <Card>
          <CardHeader>
            <CardTitle className='text-sm font-medium'>
              {selectedLog ? `${selectedLog} — ${entries.length} regels` : 'Geen log gekozen'}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {!selectedLog ? (
              <p className='text-muted-foreground text-sm'>
                Kies hierboven een logbestand om de laatste regels te bekijken.
              </p>
            ) : isLoading ? (
              <Skeleton className='h-64' />
            ) : isError ? (
              <p className='text-muted-foreground text-sm'>
                Dit logbestand kon niet worden geladen.
              </p>
            ) : entries.length === 0 ? (
              <p className='text-muted-foreground text-sm'>
                Geen regels gevonden{filter ? ' voor dit filter' : ''}.
              </p>
            ) : (
              <div className='max-h-[32rem] space-y-2 overflow-auto'>
                {entries.map((entry, index) => (
                  <pre
                    key={index}
                    className='bg-muted overflow-x-auto rounded p-2 text-xs'
                  >
                    {JSON.stringify(entry, null, 2)}
                  </pre>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </Main>
    </>
  )
}
