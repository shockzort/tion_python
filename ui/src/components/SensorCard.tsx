import type { Sensor } from '../api/types'
import { Badge, Card } from './ui'

/** Пороги подсветки CO₂, ppm (бытовая шкала качества воздуха). */
const CO2_WARN = 800
const CO2_BAD = 1000

function co2Tone(value: number): string {
  if (value > CO2_BAD) return 'text-rose-400'
  if (value > CO2_WARN) return 'text-amber-400'
  return 'text-emerald-400'
}

export default function SensorCard({
  sensor,
  roomName,
}: {
  sensor: Sensor
  roomName?: string
}) {
  const values = sensor.last_values ?? {}
  return (
    <Card className="flex items-center justify-between gap-3 py-3">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <p className="truncate font-medium">{sensor.name}</p>
          {sensor.stale && <Badge tone="warn">нет данных</Badge>}
        </div>
        <p className="text-xs text-slate-500">
          {roomName ?? (sensor.kind === 'magicair' ? 'MagicAir' : 'MQTT')}
        </p>
      </div>
      <div className="flex shrink-0 items-baseline gap-3 text-sm">
        {values.co2 !== undefined && (
          <span className={sensor.stale ? 'text-slate-500' : co2Tone(values.co2)}>
            <span className="text-lg font-semibold">{Math.round(values.co2)}</span>{' '}
            ppm
          </span>
        )}
        {values.temperature !== undefined && (
          <span className="text-slate-300">
            {values.temperature.toFixed(1)} °C
          </span>
        )}
        {values.humidity !== undefined && (
          <span className="text-slate-400">{Math.round(values.humidity)} %</span>
        )}
        {sensor.last_values === null && (
          <span className="text-slate-500">ждём данные…</span>
        )}
      </div>
    </Card>
  )
}
