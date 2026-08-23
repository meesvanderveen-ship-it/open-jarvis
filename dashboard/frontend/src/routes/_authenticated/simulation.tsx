import { createFileRoute } from '@tanstack/react-router'
import { Simulation } from '@/features/simulation'

export const Route = createFileRoute('/_authenticated/simulation')({
  component: Simulation,
})
