import { useMemo, useState } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { useDevices, useSensors, useTelemetry } from '../api/queries'
import { Card, Spinner } from '../components/ui'

const DEVICE_METRICS = [
  { key: 'out_temp', label: 'После бризера, °C' },
  { key: 'in_temp', label: 'Приток, °C' },
  { key: 'fan_speed', label: 'Скорость' },
  { key: 'heater_temp', label: 'Цель нагрева, °C' },
] as const

const SENSOR_METRICS = [
  { key: 'co2', label: 'CO₂, ppm' },
  { key: 'temperature', label: 'Температура, °C' },
  { key: 'humidity', label: 'Влажность, %' },
] as const

const PERIODS = [
  { key: '24h', label: '24 ч', seconds: 86_400, agg: 'raw' },
  { key: '7d', label: '7 дней', seconds: 7 * 86_400, agg: 'hourly' },
  { key: '30d', label: '30 дней', seconds: 30 * 86_400, agg: 'hourly' },
] as const

type PeriodKey = (typeof PERIODS)[number]['key']

export default function Charts() {
  const devices = useDevices()
  const sensors = useSensors()
  // источник кодируется "device:{uuid}" | "sensor:{id}"
  const [source, setSource] = useState('')
  const [metric, setMetric] = useState('out_temp')
  const [periodKey, setPeriodKey] = useState<PeriodKey>('24h')

  const period = PERIODS.find((p) => p.key === periodKey) ?? PERIODS[0]
  // from округляется до минуты — ключ запроса стабилен между рендерами
  const fromTs = useMemo(
    () => Math.floor((Date.now() / 1000 - period.seconds) / 60) * 60,
    [period.seconds],
  )

  const fallbackSource =
    devices.data?.[0] !== undefined
      ? `device:${devices.data[0].uuid}`
      : sensors.data?.[0] !== undefined
        ? `sensor:${sensors.data[0].id}`
        : ''
  const selectedSource = source !== '' ? source : fallbackSource
  const [sourceType, sourceId] = selectedSource.split(':', 2) as [
    'device' | 'sensor',
    string,
  ]
  const metricOptions = sourceType === 'sensor' ? SENSOR_METRICS : DEVICE_METRICS
  const activeMetric = metricOptions.some((entry) => entry.key === metric)
    ? metric
    : metricOptions[0].key

  const series = useTelemetry({
    source_type: sourceType,
    source_id: sourceId ?? '',
    metric: activeMetric,
    agg: period.agg,
    from_ts: fromTs,
  })

  if (devices.isPending || sensors.isPending)
    return <Spinner label="Загружаем источники…" />
  if (devices.isError || selectedSource === '') {
    return (
      <p className="text-sm text-slate-400">
        Графики появятся, когда будет хотя бы один бризер или датчик.
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={selectedSource}
          onChange={(event) => setSource(event.target.value)}
          className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm"
        >
          {devices.data.map((device) => (
            <option key={device.uuid} value={`device:${device.uuid}`}>
              {device.name}
            </option>
          ))}
          {sensors.data?.map((sensor) => (
            <option key={`s${sensor.id}`} value={`sensor:${sensor.id}`}>
              Датчик · {sensor.name}
            </option>
          ))}
        </select>
        <select
          value={activeMetric}
          onChange={(event) => setMetric(event.target.value)}
          className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm"
        >
          {metricOptions.map((entry) => (
            <option key={entry.key} value={entry.key}>
              {entry.label}
            </option>
          ))}
        </select>
        <div className="flex gap-1">
          {PERIODS.map((entry) => (
            <button
              key={entry.key}
              type="button"
              onClick={() => setPeriodKey(entry.key)}
              className={`rounded-lg px-2.5 py-1.5 text-sm transition-colors ${
                periodKey === entry.key
                  ? 'bg-sky-600 text-white'
                  : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
              }`}
            >
              {entry.label}
            </button>
          ))}
        </div>
      </div>

      <Card>
        {series.isPending ? (
          <Spinner label="Загружаем серию…" />
        ) : series.isError ? (
          <p className="text-sm text-rose-400">Не удалось загрузить телеметрию.</p>
        ) : (
          <SeriesChart
            agg={period.agg}
            raw={series.data.raw ?? []}
            hourly={series.data.hourly ?? []}
            longRange={period.seconds > 2 * 86_400}
          />
        )}
      </Card>
      {period.agg === 'hourly' && (
        <p className="text-xs text-slate-500">
          Часовые агрегаты: средняя (яркая), минимум и максимум (тонкие).
          Заполняются по завершении часа.
        </p>
      )}
    </div>
  )
}

function makeTsFormatters(longRange: boolean) {
  const formatTs = (ts: number) => {
    const date = new Date(ts * 1000)
    return longRange
      ? date.toLocaleDateString('ru', { day: '2-digit', month: '2-digit' })
      : date.toLocaleTimeString('ru', { hour: '2-digit', minute: '2-digit' })
  }
  const formatFull = (ts: number) => new Date(ts * 1000).toLocaleString('ru')
  return { formatTs, formatFull }
}

function ChartFrame({
  formatTs,
  formatFull,
}: ReturnType<typeof makeTsFormatters>) {
  return (
    <>
      <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
      <XAxis
        dataKey="ts"
        tickFormatter={formatTs}
        stroke="#64748b"
        fontSize={11}
        minTickGap={40}
      />
      <YAxis stroke="#64748b" fontSize={11} domain={['auto', 'auto']} />
      <Tooltip
        labelFormatter={(ts) => formatFull(ts as number)}
        contentStyle={{
          backgroundColor: '#0f172a',
          border: '1px solid #334155',
          borderRadius: 12,
          fontSize: 12,
        }}
      />
    </>
  )
}

function SeriesChart({
  agg,
  raw,
  hourly,
  longRange,
}: {
  agg: 'raw' | 'hourly'
  raw: { ts: number; value: number }[]
  hourly: { ts: number; min: number; max: number; avg: number }[]
  longRange: boolean
}) {
  const empty = agg === 'raw' ? raw.length === 0 : hourly.length === 0
  if (empty) {
    return (
      <p className="py-10 text-center text-sm text-slate-400">
        Точек за период пока нет.
      </p>
    )
  }
  const formatters = makeTsFormatters(longRange)
  const margin = { top: 8, right: 8, bottom: 0, left: -20 }

  return (
    <div className="h-64 w-full">
      <ResponsiveContainer>
        {agg === 'raw' ? (
          <LineChart data={raw} margin={margin}>
            {ChartFrame(formatters)}
            <Line
              type="monotone"
              dataKey="value"
              name="значение"
              stroke="#38bdf8"
              dot={false}
              strokeWidth={2}
              isAnimationActive={false}
            />
          </LineChart>
        ) : (
          <LineChart data={hourly} margin={margin}>
            {ChartFrame(formatters)}
            <Line
              type="monotone"
              dataKey="min"
              name="мин"
              stroke="#334155"
              dot={false}
              strokeWidth={1}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="max"
              name="макс"
              stroke="#334155"
              dot={false}
              strokeWidth={1}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="avg"
              name="среднее"
              stroke="#38bdf8"
              dot={false}
              strokeWidth={2}
              isAnimationActive={false}
            />
          </LineChart>
        )}
      </ResponsiveContainer>
    </div>
  )
}
