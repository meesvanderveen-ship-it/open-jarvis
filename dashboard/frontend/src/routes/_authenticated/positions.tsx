import { createFileRoute } from '@tanstack/react-router'
import { Positions } from '@/features/positions'

export const Route = createFileRoute('/_authenticated/positions')({
  component: Positions,
})
