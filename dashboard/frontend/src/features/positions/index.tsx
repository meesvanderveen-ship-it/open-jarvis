import { useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { DataTable } from '@/components/data-table'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { useOrders, usePositions } from './api'
import { orderColumns, positionColumns } from './columns'

export function Positions() {
  const positions = usePositions()
  const orders = useOrders()
  const [positionsOpenOnly, setPositionsOpenOnly] = useState(false)
  const [ordersOpenOnly, setOrdersOpenOnly] = useState(false)
  const [showHistoricalDiagnostics, setShowHistoricalDiagnostics] = useState(false)

  const positionRows = (positions.data?.positions ?? []).filter(
    (p) => !positionsOpenOnly || p.is_open
  )
  const orderRows = (orders.data?.orders ?? []).filter((o) => !ordersOpenOnly || o.is_open)

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
            <h1 className='text-2xl font-bold tracking-tight'>Positions & Orders</h1>
            <p className='text-muted-foreground'>
              All exposure and order state — read-only.
            </p>
          </div>
          <div className='flex gap-2'>
            <Badge variant='outline'>
              {positions.data?.summary.open_count ?? 0} open positions
            </Badge>
            <Badge variant='outline'>{orders.data?.summary.open_count ?? 0} open orders</Badge>
            <Badge variant='outline'>{orders.data?.summary.open_d3_exit_count ?? 0} open D3 exits</Badge>
          </div>
        </div>

        {(positions.data?.summary.open_risk_incomplete_count ?? 0) > 0 && (
          <Alert variant='destructive' className='mb-4'>
            <AlertTriangle className='size-4' />
            <AlertTitle>Open risk-incomplete positions present</AlertTitle>
            <AlertDescription>
              {positions.data?.summary.open_risk_incomplete_count} currently open
              position(s) ({positions.data?.summary.open_risk_incomplete_tickers.join(', ')})
              are missing complete protective-stop state. See the highlighted rows below.
            </AlertDescription>
          </Alert>
        )}

        {(positions.data?.summary.closed_risk_incomplete_count ?? 0) > 0 && (
          <Alert className='mb-4'>
            <AlertTitle>Historical data quality note</AlertTitle>
            <AlertDescription>
              {positions.data?.summary.closed_risk_incomplete_count} already-closed
              position(s) ({positions.data?.summary.closed_risk_incomplete_tickers.join(', ')})
              still carry a leftover incomplete-risk flag from before they were
              closed. This is not current exposure — no action needed. Enable
              "show historical diagnostics" below to highlight those rows.
            </AlertDescription>
          </Alert>
        )}

        <Tabs defaultValue='positions' className='space-y-4'>
          <TabsList>
            <TabsTrigger value='positions'>Positions</TabsTrigger>
            <TabsTrigger value='orders'>Orders</TabsTrigger>
          </TabsList>

          <TabsContent value='positions' className='space-y-3'>
            <div className='flex items-center gap-4'>
              <div className='flex items-center gap-2'>
                <Switch
                  id='positions-open-only'
                  checked={positionsOpenOnly}
                  onCheckedChange={setPositionsOpenOnly}
                />
                <Label htmlFor='positions-open-only'>Open only</Label>
              </div>
              <div className='flex items-center gap-2'>
                <Switch
                  id='positions-show-historical-diagnostics'
                  checked={showHistoricalDiagnostics}
                  onCheckedChange={setShowHistoricalDiagnostics}
                />
                <Label htmlFor='positions-show-historical-diagnostics'>
                  Show historical diagnostics
                </Label>
              </div>
            </div>
            {positions.isLoading ? (
              <Skeleton className='h-64' />
            ) : (
              <Card>
                <CardHeader>
                  <CardTitle className='text-sm font-medium'>
                    {positionRows.length} position(s)
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <DataTable
                    columns={positionColumns}
                    data={positionRows}
                    emptyMessage='No positions to show.'
                    getRowClassName={(row) => {
                      if (!row.position_risk_incomplete) return undefined
                      // Only a currently-open risk-incomplete position is an
                      // actual warning; a closed one is historical data
                      // quality and only highlighted (faintly) when the
                      // operator explicitly asks to see it.
                      if (row.is_open) return 'bg-red-500/10'
                      return showHistoricalDiagnostics ? 'bg-muted/40' : undefined
                    }}
                  />
                </CardContent>
              </Card>
            )}
          </TabsContent>

          <TabsContent value='orders' className='space-y-3'>
            <div className='flex items-center gap-2'>
              <Switch
                id='orders-open-only'
                checked={ordersOpenOnly}
                onCheckedChange={setOrdersOpenOnly}
              />
              <Label htmlFor='orders-open-only'>Open only</Label>
            </div>
            {orders.isLoading ? (
              <Skeleton className='h-64' />
            ) : (
              <Card>
                <CardHeader>
                  <CardTitle className='text-sm font-medium'>
                    {orderRows.length} order(s)
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <DataTable
                    columns={orderColumns}
                    data={orderRows}
                    emptyMessage='No orders to show.'
                  />
                </CardContent>
              </Card>
            )}
          </TabsContent>
        </Tabs>
      </Main>
    </>
  )
}
