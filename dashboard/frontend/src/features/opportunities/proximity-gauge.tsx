import { cn } from '@/lib/utils'
import type { Proximity } from './api'

// Fixed status hues (never themed — same rationale as StatusBadge's tones):
// a gauge zone must mean the same thing in light and dark mode, so these are
// plain hex, not CSS variables that shift with the theme.
const ZONE_COLOR: Record<Proximity['zone'], string> = {
  red: '#ef4444',
  orange: '#f59e0b',
  green: '#10b981',
}

const ZONE_LABEL: Record<Proximity['zone'], string> = {
  red: 'Ver weg',
  orange: 'Bouwt op',
  green: 'Dichtbij',
}

// Score bands must match dashboard/backend/services/opportunities.py::_proximity
// exactly, or the arc coloring and the needle position disagree.
const BANDS: { zone: Proximity['zone']; from: number; to: number }[] = [
  { zone: 'red', from: 0, to: 40 },
  { zone: 'orange', from: 40, to: 70 },
  { zone: 'green', from: 70, to: 100 },
]

const CX = 60
const CY = 58
const R = 50
const TRACK_WIDTH = 12

function polarToCartesian(cx: number, cy: number, r: number, angleDeg: number) {
  const angleRad = (angleDeg * Math.PI) / 180
  return { x: cx + r * Math.cos(angleRad), y: cy - r * Math.sin(angleRad) }
}

// score 0 -> 180deg (left/red end), score 100 -> 0deg (right/green end)
function scoreToAngle(score: number) {
  return 180 - (Math.max(0, Math.min(100, score)) / 100) * 180
}

function describeArc(cx: number, cy: number, r: number, startAngle: number, endAngle: number) {
  const start = polarToCartesian(cx, cy, r, startAngle)
  const end = polarToCartesian(cx, cy, r, endAngle)
  const largeArcFlag = Math.abs(startAngle - endAngle) > 180 ? 1 : 0
  return `M ${start.x} ${start.y} A ${r} ${r} 0 ${largeArcFlag} 1 ${end.x} ${end.y}`
}

export function ProximityGauge({
  proximity,
  className,
}: {
  proximity: Proximity | null | undefined
  className?: string
}) {
  const score = proximity?.score ?? 0
  const zone = proximity?.zone ?? 'red'
  const needleAngle = scoreToAngle(score)
  const needleTip = polarToCartesian(CX, CY, R - TRACK_WIDTH / 2 - 4, needleAngle)

  return (
    <div className={cn('flex flex-col items-center', className)}>
      <svg viewBox='0 0 120 66' className='w-full max-w-[220px]' role='img' aria-label={`Actie-nabijheid ${score} van 100, zone ${ZONE_LABEL[zone]}`}>
        {BANDS.map((band) => (
          <path
            key={band.zone}
            d={describeArc(CX, CY, R, scoreToAngle(band.from), scoreToAngle(band.to))}
            fill='none'
            stroke={ZONE_COLOR[band.zone]}
            strokeWidth={TRACK_WIDTH}
            strokeLinecap='butt'
            opacity={proximity ? 1 : 0.25}
          />
        ))}
        <line
          x1={CX}
          y1={CY}
          x2={needleTip.x}
          y2={needleTip.y}
          stroke='currentColor'
          className='text-foreground'
          strokeWidth={2.5}
          strokeLinecap='round'
        />
        <circle cx={CX} cy={CY} r={4} fill='currentColor' className='text-foreground' />
      </svg>
      <div className='-mt-1 flex flex-col items-center'>
        <span className='text-lg font-semibold tabular-nums' style={{ color: ZONE_COLOR[zone] }}>
          {proximity ? score : '—'}
        </span>
        <span className='text-xs text-muted-foreground'>{ZONE_LABEL[zone]}</span>
      </div>
    </div>
  )
}

export function ProximityConditions({ proximity }: { proximity: Proximity | null | undefined }) {
  if (!proximity || proximity.conditions.length === 0) return null
  return (
    <ul className='mt-2 space-y-1 text-xs text-muted-foreground'>
      {proximity.conditions.map((condition, i) => (
        <li key={i} className='flex gap-1.5'>
          <span aria-hidden='true'>•</span>
          <span>{condition}</span>
        </li>
      ))}
    </ul>
  )
}
