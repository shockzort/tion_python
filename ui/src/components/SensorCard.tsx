import type { Sensor, SensorMetric } from '../api/types'
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
  const stale = (metric: SensorMetric) => sensor.metric_stale?.[metric] ?? sensor.stale
  const age = (metric: SensorMetric) => {
    const ts = sensor.last_metric_at?.[metric]
    return `${stale(metric) ? 'Данные устарели. ' : ''}${ts ? new Date(ts * 1000).toLocaleString('ru') : 'Время измерения неизвестно'}`
  }
  const partlyStale = sensor.stale && Object.keys(values).some((metric) => !stale(metric as SensorMetric))
  return (
    <Card className="flex flex-wrap items-center justify-between gap-3 py-3">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <p className="truncate font-medium">{sensor.name}</p>
          {sensor.stale && <Badge tone="warn">{partlyStale ? 'часть данных устарела' : 'нет данных'}</Badge>}
        </div>
        <p className="text-xs text-slate-500">
          {roomName ?? ({ magicair: 'MagicAir', mqtt: 'MQTT', qingping_ble: 'Qingping BLE' }[sensor.kind])}
        </p>
      </div>
      <div className="flex max-w-full flex-wrap items-baseline gap-3 text-sm">
        {values.co2 !== undefined && (
          <span title={age('co2')} className={stale('co2') ? 'text-slate-500' : co2Tone(values.co2)}>
            <span className="text-lg font-semibold">{Math.round(values.co2)}</span>{' '}
            ppm
          </span>
        )}
        {values.temperature !== undefined && (
          <span title={age('temperature')} className={stale('temperature') ? 'text-slate-500' : 'text-slate-300'}>
            {values.temperature.toFixed(1)} °C
          </span>
        )}
        {values.humidity !== undefined && (
          <span title={age('humidity')} className={stale('humidity') ? 'text-slate-500' : 'text-slate-400'}>{Math.round(values.humidity)} %</span>
        )}
        {sensor.last_values === null && (
          <span className="text-slate-500">ждём данные…</span>
        )}
      </div>
    </Card>
  )
}
