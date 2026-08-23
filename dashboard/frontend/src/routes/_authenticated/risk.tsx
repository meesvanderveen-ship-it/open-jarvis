import { createFileRoute } from '@tanstack/react-router'
import { Risk } from '@/features/risk'

export const Route = createFileRoute('/_authenticated/risk')({
  component: Risk,
})
