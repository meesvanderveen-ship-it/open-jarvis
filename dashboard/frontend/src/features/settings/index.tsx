import { Separator } from '@/components/ui/separator'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { SettingsAppearance } from './appearance'

export function Settings() {
  return (
    <>
      <Header>
        <Search className='me-auto' />
        <ThemeSwitch />
        <ConfigDrawer />
        <ProfileDropdown />
      </Header>

      <Main fixed>
        <div className='space-y-0.5'>
          <h1 className='text-2xl font-bold tracking-tight md:text-3xl'>
            Appearance
          </h1>
          <p className='text-muted-foreground'>
            Theme and font for this local, read-only console. No account settings —
            this dashboard has no user accounts.
          </p>
        </div>
        <Separator className='my-4 lg:my-6' />
        <div className='lg:max-w-xl'>
          <SettingsAppearance />
        </div>
      </Main>
    </>
  )
}
