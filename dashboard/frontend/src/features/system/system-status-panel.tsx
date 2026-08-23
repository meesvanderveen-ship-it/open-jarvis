import {
  AlertTriangle,
  BrainCircuit,
  CircleHelp,
  KeyRound,
  ShieldCheck,
  Wrench,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Skeleton } from '@/components/ui/skeleton'
import {
  type ProviderCheck,
  type SystemState,
  useSetupStatus,
} from './api'

type Tone = 'ready' | 'warn' | 'error' | 'neutral'

const TONE_VAR: Record<Tone, string> = {
  ready: 'var(--jarvis-ready)',
  warn: 'var(--jarvis-warn)',
  error: 'var(--jarvis-error)',
  neutral: 'var(--jarvis-accent)',
}

const STATE_PRESENTATION: Record<
  SystemState,
  { tone: Tone; label: string; blurb: string; Icon: typeof ShieldCheck }
> = {
  READY: {
    tone: 'ready',
    label: 'JARVIS READY',
    blurb: 'Credentials zijn compleet en bruikbaar. De bot kan gestart worden.',
    Icon: ShieldCheck,
  },
  SETUP_REQUIRED: {
    tone: 'warn',
    label: 'SETUP REQUIRED',
    blurb: 'Er ontbreken credentials. Draai de setup-wizard om ze in te stellen.',
    Icon: Wrench,
  },
  CONFIGURATION_ERROR: {
    tone: 'error',
    label: 'CONFIGURATION ERROR',
    blurb: 'Credentials zijn aanwezig maar niet bruikbaar. Zie de details hieronder.',
    Icon: AlertTriangle,
  },
  UNKNOWN: {
    tone: 'neutral',
    label: 'STATUS ONBEKEND',
    blurb: 'De statuscontrole kon niet worden uitgevoerd.',
    Icon: CircleHelp,
  },
}

const PROVIDER_META: Record<string, { label: string; Icon: typeof BrainCircuit }> = {
  openai: { label: 'OpenAI', Icon: BrainCircuit },
  coinbase: { label: 'Coinbase', Icon: KeyRound },
}

function toneForProvider(check: ProviderCheck): Tone {
  if (check.status === 'ok') return 'ready'
  if (check.status === 'missing') return 'warn'
  if (check.status === 'invalid') return 'error'
  return 'neutral'
}

function Pulse({ tone, className }: { tone: Tone; className?: string }) {
  return (
    <span
      className={cn('jarvis-pulse', className)}
      style={{ ['--jarvis-tone' as string]: TONE_VAR[tone] }}
      aria-hidden
    />
  )
}

function ProviderTile({ check }: { check: ProviderCheck }) {
  const tone = toneForProvider(check)
  const meta = PROVIDER_META[check.provider] ?? {
    label: check.provider,
    Icon: CircleHelp,
  }
  const { Icon } = meta

  return (
    <div className='bg-card/60 flex items-start gap-3 rounded-lg border p-3'>
      <Icon className='mt-0.5 size-4 shrink-0' style={{ color: TONE_VAR[tone] }} />
      <div className='min-w-0 flex-1'>
        <div className='flex items-center gap-2'>
          <span className='text-sm font-medium'>{meta.label}</span>
          <Pulse tone={tone} />
        </div>
        <p className='text-muted-foreground mt-0.5 text-xs'>{check.summary}</p>
        {check.detail ? (
          <p className='text-muted-foreground/80 mt-1 text-xs'>{check.detail}</p>
        ) : null}
      </div>
    </div>
  )
}

/**
 * Toont in één oogopslag of JARVIS kan draaien.
 *
 * Leest uitsluitend /api/setup/status, dat read-only is en nooit een secret
 * teruggeeft — er wordt hier dus ook nooit een credential gerenderd, alleen
 * de status en de uitleg die de backend meegeeft.
 */
export function SystemStatusPanel() {
  const { data, isLoading, isError } = useSetupStatus()

  if (isLoading) {
    return <Skeleton className='h-40 w-full' />
  }

  const state: SystemState = isError ? 'UNKNOWN' : (data?.state ?? 'UNKNOWN')
  const presentation = STATE_PRESENTATION[state] ?? STATE_PRESENTATION.UNKNOWN
  const { Icon, tone } = presentation

  const providers = Object.values(data?.providers ?? {})

  return (
    <section
      className='jarvis-panel jarvis-rise jarvis-glow mb-6 rounded-xl p-5'
      style={{ ['--jarvis-tone' as string]: TONE_VAR[tone] }}
      aria-label='Systeemstatus'
    >
      <div className='relative flex flex-wrap items-start justify-between gap-4'>
        <div className='flex items-start gap-3'>
          <span
            className='flex size-10 shrink-0 items-center justify-center rounded-lg border'
            style={{
              color: TONE_VAR[tone],
              borderColor: `color-mix(in oklch, ${TONE_VAR[tone]} 35%, transparent)`,
              background: `color-mix(in oklch, ${TONE_VAR[tone]} 12%, transparent)`,
            }}
          >
            <Icon className='size-5' />
          </span>
          <div>
            <div className='flex items-center gap-2'>
              <h2
                className='font-mono text-lg font-semibold tracking-widest'
                style={{ color: TONE_VAR[tone] }}
              >
                {presentation.label}
              </h2>
              <Pulse tone={tone} />
            </div>
            <p className='text-muted-foreground mt-1 max-w-prose text-sm'>
              {presentation.blurb}
            </p>
          </div>
        </div>

        {data?.verified_online ? (
          <span className='text-muted-foreground rounded-full border px-2 py-0.5 text-xs'>
            geverifieerd tegen de API's
          </span>
        ) : null}
      </div>

      {providers.length > 0 ? (
        <div className='relative mt-4 grid gap-3 sm:grid-cols-2'>
          {providers.map((check) => (
            <ProviderTile key={check.provider} check={check} />
          ))}
        </div>
      ) : null}

      {state !== 'READY' ? (
        <p className='text-muted-foreground relative mt-4 text-xs'>
          Stel de credentials in met{' '}
          <code className='bg-muted rounded px-1 py-0.5 font-mono'>
            python -m tools.setup_wizard
          </code>
          {' '}en verifieer ze met{' '}
          <code className='bg-muted rounded px-1 py-0.5 font-mono'>
            --check --online
          </code>
          .
        </p>
      ) : null}

      {data?.detail ? (
        <p className='text-muted-foreground relative mt-2 text-xs'>{data.detail}</p>
      ) : null}

      {data?.error_output ? (
        <pre className='bg-muted/60 relative mt-2 overflow-x-auto rounded p-2 text-[11px] leading-relaxed'>
          {data.error_output}
        </pre>
      ) : null}
    </section>
  )
}
