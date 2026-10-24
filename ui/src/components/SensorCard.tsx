import type { Sensor } from '../api/types'
import { formatValue, METRIC_INFO, METRIC_ORDER, quality, type Quality, type SensorMetric } from '../lib/metrics'
import { Badge, Card } from './ui'

const QUALITY_TONE: Record<Quality, string> = {
  good: 'text-emerald-400',
  fair: 'text-amber-400',
  poor: 'text-rose-400',
  neutral: 'text-slate-200',
}

export default function SensorCard({ sensor, roomName }: { sensor: Sensor; roomName?: string }) {
  const values = sensor.last_values ?? {}
  const shown = METRIC_ORDER.filter((metric) => metric !== 'battery' && values[metric] !== undefined)
  const stale = (metric: SensorMetric) => sensor.metric_stale?.[metric] ?? sensor.stale
  const age = (metric: SensorMetric) => {
    const ts = sensor.last_metric_at?.[metric]
    return `${stale(metric) ? 'Данные устарели. ' : ''}${ts ? new Date(ts * 1000).toLocaleString('ru') : 'Время измерения неизвестно'}`
  }
  const partlyStale = sensor.stale && shown.some((metric) => !stale(metric))
  const battery = values.battery
  return (
    <Card className="flex flex-col gap-3 py-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate font-medium">{sensor.name}</p>
          {roomName && <p className="text-xs text-slate-500">{roomName}</p>}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {battery !== undefined && battery < 100 && (
            <span className="text-xs text-slate-500" title="Заряд батареи">
              {formatValue('battery', battery)} %
            </span>
          )}
          {sensor.stale && <Badge tone="warn">{partlyStale ? 'часть данных устарела' : 'нет данных'}</Badge>}
        </div>
      </div>
      {shown.length > 0 ? (
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-5">
          {shown.map((metric) => {
            const value = values[metric] as number
            const tone = stale(metric) ? 'text-slate-500' : QUALITY_TONE[quality(metric, value)]
            return (
              <div key={metric} title={age(metric)} className="flex flex-col rounded-xl bg-slate-950/50 px-2.5 py-2">
                <span className="text-[11px] uppercase tracking-wide text-slate-500">{METRIC_INFO[metric].short}</span>
                <span className={`text-lg font-semibold tabular-nums ${tone}`} data-metric={metric}>
                  {formatValue(metric, value)}
                </span>
                <span className="text-[11px] text-slate-500">{METRIC_INFO[metric].unit}</span>
              </div>
            )
          })}
        </div>
      ) : (
        <span className="text-sm text-slate-500">ждём данные…</span>
      )}
    </Card>
  )
}
