import { ShieldCheck } from 'lucide-react'
import { SidebarMenu, SidebarMenuItem } from '@/components/ui/sidebar'

export function NavUser() {
  return (
    <SidebarMenu>
      <SidebarMenuItem className='flex items-center gap-2 px-2 py-1.5 text-xs text-muted-foreground'>
        <ShieldCheck className='size-3.5 shrink-0' />
        <span className='truncate'>No write access · No Coinbase calls</span>
      </SidebarMenuItem>
    </SidebarMenu>
  )
}
