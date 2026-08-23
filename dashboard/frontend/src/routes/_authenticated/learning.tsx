import { createFileRoute } from '@tanstack/react-router'
import { Learning } from '@/features/learning'

export const Route = createFileRoute('/_authenticated/learning')({
  component: Learning,
})
