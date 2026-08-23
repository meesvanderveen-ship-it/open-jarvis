import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'

export type StatusTone = 'safe' | 'warning' | 'danger' | 'info'

const TONE_CLASSES: Record<StatusTone, string> = {
  safe: 'border-emerald-600/30 bg-emerald-500/15 text-emerald-600 dark:text-emerald-400',
  warning: 'border-amber-600/30 bg-amber-500/15 text-amber-600 dark:text-amber-400',
  danger: 'border-red-600/30 bg-red-500/15 text-red-600 dark:text-red-400',
  info: 'border-blue-600/30 bg-blue-500/15 text-blue-600 dark:text-blue-400',
}

export function StatusBadge({
  tone,
  children,
  className,
}: {
  tone: StatusTone
  children: React.ReactNode
  className?: string
}) {
  return (
    <Badge variant='outline' className={cn(TONE_CLASSES[tone], className)}>
      {children}
    </Badge>
  )
}
