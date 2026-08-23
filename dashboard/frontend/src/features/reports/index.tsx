import { useState } from 'react'
import { FileText } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { useReportDetail, useReportList } from './api'

export function Reports() {
  const [selected, setSelected] = useState<string | null>(null)
  const { data, isLoading, isError } = useReportList()
  const detail = useReportDetail(selected)

  const reports = data?.reports ?? []

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
          <h1 className='text-2xl font-bold tracking-tight'>Rapporten</h1>
          <p className='text-muted-foreground'>
            Door de bot gegenereerde rapporten, alleen-lezen ingezien.
          </p>
        </div>

        {isLoading ? (
          <Skeleton className='h-64' />
        ) : isError ? (
          <Card>
            <CardContent className='text-muted-foreground py-6 text-sm'>
              Rapporten konden niet worden geladen.
            </CardContent>
          </Card>
        ) : reports.length === 0 ? (
          <Card>
            <CardContent className='text-muted-foreground py-6 text-sm'>
              Nog geen rapporten gegenereerd.
            </CardContent>
          </Card>
        ) : (
          <div className='grid gap-4 lg:grid-cols-2'>
            <Card>
              <CardHeader>
                <CardTitle className='text-sm font-medium'>
                  Beschikbaar ({reports.length})
                </CardTitle>
              </CardHeader>
              <CardContent className='space-y-1'>
                {reports.map((report) => (
                  <Button
                    key={report.id}
                    variant={selected === report.id ? 'secondary' : 'ghost'}
                    className='h-auto w-full justify-start py-2 text-start'
                    onClick={() => setSelected(report.id)}
                  >
                    <FileText className='me-2 h-4 w-4 shrink-0' />
                    <span className='truncate font-mono text-xs'>
                      {report.id}
                    </span>
                  </Button>
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className='flex items-center gap-2 text-sm font-medium'>
                  {selected ? (
                    <span className='truncate font-mono text-xs'>{selected}</span>
                  ) : (
                    'Selecteer een rapport'
                  )}
                  {detail.data?.truncated ? (
                    <Badge variant='outline'>ingekort</Badge>
                  ) : null}
                </CardTitle>
              </CardHeader>
              <CardContent>
                {!selected ? (
                  <p className='text-muted-foreground text-sm'>
                    Kies links een rapport om de inhoud te bekijken.
                  </p>
                ) : detail.isLoading ? (
                  <Skeleton className='h-48' />
                ) : detail.isError ? (
                  <p className='text-muted-foreground text-sm'>
                    Dit rapport kon niet worden geladen.
                  </p>
                ) : (
                  <pre className='bg-muted max-h-[28rem] overflow-auto rounded p-3 text-xs'>
                    {JSON.stringify(detail.data?.content ?? detail.data, null, 2)}
                  </pre>
                )}
              </CardContent>
            </Card>
          </div>
        )}
      </Main>
    </>
  )
}
