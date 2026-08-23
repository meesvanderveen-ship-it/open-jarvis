import { createFileRoute } from '@tanstack/react-router'
import { AgentTrace } from '@/features/agent-trace'

export const Route = createFileRoute('/_authenticated/agent-trace')({
  component: AgentTrace,
})
