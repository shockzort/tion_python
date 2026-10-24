import type { Sensor } from '../api/types'
import { formatValue, METRIC_INFO, METRIC_ORDER, metricColor, type SensorMetric } from '../lib/metrics'
import { usePersistentState } from '../lib/usePersistentState'
import { Badge, Card } from './ui'

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
  // как у бризеров: per-датчик и per-браузер
  const [collapsed, setCollapsed] = usePersistentState(`eb:sensor-collapsed:${sensor.id}`, false)
  const colorOf = (metric: SensorMetric, value: number) => (stale(metric) ? null : metricColor(metric, value))
  const toneOf = (metric: SensorMetric) => (stale(metric) ? 'text-slate-500' : 'text-slate-200')
  return (
    <Card className={`flex flex-col py-3 ${collapsed ? 'gap-1.5' : 'gap-3'}`}>
      <div className="flex items-start justify-between gap-2">
        <button
          type="button"
          aria-expanded={!collapsed}
          title={collapsed ? 'Развернуть' : 'Свернуть'}
          onClick={() => setCollapsed((value) => !value)}
          className="flex min-w-0 items-start gap-1.5 text-left"
        >
          <span
            aria-hidden="true"
            className={`mt-0.5 text-xs text-slate-500 transition-transform ${collapsed ? '' : 'rotate-90'}`}
          >
            ▸
          </span>
          <span className="min-w-0">
            <span className="block truncate font-medium">{sensor.name}</span>
            {!collapsed && (
              <span className="block text-xs text-slate-500">
                {[roomName, sensor.last_seen_at ? `обновлено ${new Date(sensor.last_seen_at * 1000).toLocaleTimeString('ru', { hour: '2-digit', minute: '2-digit' })}` : null]
                  .filter(Boolean)
                  .join(' · ')}
              </span>
            )}
          </span>
        </button>
        <div className="flex shrink-0 items-center gap-1.5">
          {battery !== undefined && battery < 100 && (
            <span className="text-xs text-slate-500" style={{ color: metricColor('battery', battery) ?? undefined }} title="Заряд батареи">
              {formatValue('battery', battery)} %
            </span>
          )}
          {sensor.stale && <Badge tone="warn">{partlyStale ? 'часть данных устарела' : 'нет данных'}</Badge>}
        </div>
      </div>
      {shown.length === 0 ? (
        <span className="text-sm text-slate-500">ждём данные…</span>
      ) : collapsed ? (
        // компактная строка: «CO₂ 757 · 24,9 °C · 41,4 % · PM2.5 3»
        <p className="flex flex-wrap gap-x-3 gap-y-1 pl-4 text-sm tabular-nums">
          {shown.map((metric) => {
            const value = values[metric] as number
            const color = colorOf(metric, value)
            const unit = METRIC_INFO[metric].unit
            const isPrefixed = unit === 'ppm' || unit === 'мкг/м³'
            return (
              <span key={metric} title={age(metric)} className="whitespace-nowrap text-slate-400">
                {isPrefixed && `${METRIC_INFO[metric].short} `}
                <span
                  className={`font-bold ${toneOf(metric)}`}
                  style={color === null ? undefined : { color }}
                  data-metric={metric}
                >
                  {formatValue(metric, value)}
                </span>
                {!isPrefixed && ` ${unit}`}
              </span>
            )
          })}
        </p>
      ) : (
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-5">
          {shown.map((metric) => {
            const value = values[metric] as number
            const color = colorOf(metric, value)
            return (
              <div key={metric} title={age(metric)} className="flex flex-col rounded-xl bg-slate-950/70 px-3 py-2">
                <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">{METRIC_INFO[metric].short}</span>
                <span
                  className={`text-[1.35rem] font-extrabold tabular-nums transition-colors ${toneOf(metric)}`}
                  style={color === null ? undefined : { color }}
                  data-metric={metric}
                >
                  {formatValue(metric, value)}
                </span>
                <span className="text-[11px] text-slate-400">{METRIC_INFO[metric].unit}</span>
              </div>
            )
          })}
        </div>
      )}
    </Card>
  )
}
