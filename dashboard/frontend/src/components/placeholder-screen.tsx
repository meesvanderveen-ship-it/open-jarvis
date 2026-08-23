import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'

type PlaceholderScreenProps = {
  title: string
  description: string
  endpoints: string[]
}

export function PlaceholderScreen({
  title,
  description,
  endpoints,
}: PlaceholderScreenProps) {
  return (
    <>
      <Header>
        <Search className='me-auto' />
        <ThemeSwitch />
        <ConfigDrawer />
        <ProfileDropdown />
      </Header>

      <Main>
        <div className='mb-2 flex items-center justify-between space-y-2'>
          <div>
            <h1 className='text-2xl font-bold tracking-tight'>{title}</h1>
            <p className='text-muted-foreground'>{description}</p>
          </div>
          <Badge variant='outline'>Read-only</Badge>
        </div>
        <Card>
          <CardHeader>
            <CardTitle>Not wired yet</CardTitle>
          </CardHeader>
          <CardContent className='text-sm text-muted-foreground'>
            Will be sourced from{' '}
            {endpoints.map((e, i) => (
              <code key={e} className='mx-0.5'>
                {e}
                {i < endpoints.length - 1 ? ',' : ''}
              </code>
            ))}
            .
          </CardContent>
        </Card>
      </Main>
    </>
  )
}
