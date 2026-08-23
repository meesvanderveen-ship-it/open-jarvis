import { ShieldCheck } from 'lucide-react'
import { Badge } from '@/components/ui/badge'

export function ProfileDropdown() {
  return (
    <Badge variant='outline' className='gap-1.5 text-muted-foreground'>
      <ShieldCheck className='size-3.5' />
      Read-only
    </Badge>
  )
}
