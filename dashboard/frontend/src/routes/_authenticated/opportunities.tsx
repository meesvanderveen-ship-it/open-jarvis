import { createFileRoute } from '@tanstack/react-router'
import { Opportunities } from '@/features/opportunities'

export const Route = createFileRoute('/_authenticated/opportunities')({
  component: Opportunities,
})
