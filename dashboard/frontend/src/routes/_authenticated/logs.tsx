import { createFileRoute } from '@tanstack/react-router'
import { Logs } from '@/features/logs'

export const Route = createFileRoute('/_authenticated/logs')({
  component: Logs,
})
