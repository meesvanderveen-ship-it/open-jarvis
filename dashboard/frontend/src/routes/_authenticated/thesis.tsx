import { createFileRoute } from '@tanstack/react-router'
import { Thesis } from '@/features/thesis'

export const Route = createFileRoute('/_authenticated/thesis')({
  component: Thesis,
})
