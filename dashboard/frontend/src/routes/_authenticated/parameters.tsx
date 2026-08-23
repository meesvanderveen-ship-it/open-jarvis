import { createFileRoute } from '@tanstack/react-router'
import { Parameters } from '@/features/parameters'

export const Route = createFileRoute('/_authenticated/parameters')({
  component: Parameters,
})
