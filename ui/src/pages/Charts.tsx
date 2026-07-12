import { useMemo, useState, type ReactNode } from 'react'
import {
  closestCenter,
  DndContext,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import {
  arrayMove,
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import {
  useDevices,
  usePref,
  useSavePref,
  useSensors as useAirSensors,
  useTelemetry,
} from '../api/queries'
import type { Device, Sensor } from '../api/types'
import { Button, Card, Spinner } from '../components/ui'

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
  { key: '1h', label: '1ч', seconds: 3_600, agg: 'raw' },
  { key: '6h', label: '6ч', seconds: 6 * 3_600, agg: 'raw' },
  { key: '24h', label: '24ч', seconds: 86_400, agg: 'raw' },
  { key: '7d', label: '7д', seconds: 7 * 86_400, agg: 'hourly' },
  { key: '30d', label: '30д', seconds: 30 * 86_400, agg: 'hourly' },
] as const

type PeriodKey = (typeof PERIODS)[number]['key'] | 'custom'

/** Сырьё хранится 7 дней; старше или шире 2 суток — часовые агрегаты. */
const RAW_RETENTION_SECONDS = 7 * 86_400

/** Панель графика; состав хранится на сервере (ключ prefs "charts"). */
type ChartPanel = {
  id: string
  source: string // "device:{uuid}" | "sensor:{id}" | "" — первый доступный
  metric: string
  period: PeriodKey
  from_ts?: number // только для period="custom", unix-секунды
  to_ts?: number
}

const DEFAULT_PANEL: ChartPanel = {
  id: 'default',
  source: '',
  metric: 'out_temp',
  period: '24h',
}

function panelsEqual(a: ChartPanel[], b: ChartPanel[]): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}

export default function Charts() {
  const devices = useDevices()
  const sensors = useAirSensors()
  const pref = usePref<ChartPanel[]>('charts')
  const savePref = useSavePref<ChartPanel[]>('charts')
  // черновик: правки локальны до явного «Сохранить» (случайное удаление обратимо)
  const [draft, setDraft] = useState<ChartPanel[] | null>(null)
  // во время переноса Recharts-графики подменяются заглушками: иначе каждый
  // кадр жеста перерисовывает тяжёлые SVG и на телефоне жест тормозит
  const [isDragging, setIsDragging] = useState(false)

  // мышь — сразу по сдвигу; тач — долгое нажатие (не конфликтует со скроллом)
  const dndSensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 4 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 200, tolerance: 8 } }),
  )

  if (devices.isPending || sensors.isPending || pref.isPending)
    return <Spinner label="Загружаем графики…" />
  if (devices.isError) {
    return (
      <p className="text-sm text-slate-400">
        Графики появятся, когда будет хотя бы один бризер или датчик.
      </p>
    )
  }

  const saved =
    pref.data !== null && pref.data !== undefined && pref.data.length > 0
      ? pref.data
      : [DEFAULT_PANEL]
  const panels = draft ?? saved
  const isDirty = draft !== null && !panelsEqual(draft, saved)

  const patchPanel = (id: string, patch: Partial<ChartPanel>) =>
    setDraft(
      panels.map((panel) => (panel.id === id ? { ...panel, ...patch } : panel)),
    )

  const onDragEnd = (event: DragEndEvent) => {
    setIsDragging(false)
    const { active, over } = event
    if (over === null || active.id === over.id) return
    const from = panels.findIndex((panel) => panel.id === active.id)
    const to = panels.findIndex((panel) => panel.id === over.id)
    if (from >= 0 && to >= 0) setDraft(arrayMove(panels, from, to))
  }

  const save = () => {
    if (draft !== null) {
      savePref.mutate(draft)
      setDraft(null)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {isDirty && (
        <Card className="flex items-center justify-between gap-3 border border-sky-800">
          <p className="text-sm text-slate-300">Набор графиков изменён.</p>
          <div className="flex shrink-0 gap-2">
            <Button onClick={save} disabled={savePref.isPending}>
              Сохранить
            </Button>
            <Button variant="ghost" onClick={() => setDraft(null)}>
              Сбросить
            </Button>
          </div>
        </Card>
      )}

      <DndContext
        sensors={dndSensors}
        collisionDetection={closestCenter}
        onDragStart={() => setIsDragging(true)}
        onDragCancel={() => setIsDragging(false)}
        onDragEnd={onDragEnd}
      >
        <SortableContext
          items={panels.map((panel) => panel.id)}
          strategy={verticalListSortingStrategy}
        >
          {panels.map((panel) => (
            <SortablePanel key={panel.id} id={panel.id}>
              {(handle) => (
                <ChartPanelCard
                  panel={panel}
                  devices={devices.data}
                  sensors={sensors.data ?? []}
                  dragHandle={handle}
                  quiet={isDragging}
                  onChange={(patch) => patchPanel(panel.id, patch)}
                  onRemove={() =>
                    setDraft(panels.filter((entry) => entry.id !== panel.id))
                  }
                />
              )}
            </SortablePanel>
          ))}
        </SortableContext>
      </DndContext>

      <Button
        variant="ghost"
        onClick={() =>
          setDraft([...panels, { ...DEFAULT_PANEL, id: crypto.randomUUID() }])
        }
      >
        + Добавить график
      </Button>
    </div>
  )
}

function SortablePanel({
  id,
  children,
}: {
  id: string
  children: (handle: ReactNode) => ReactNode
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id })
  const handle = (
    <button
      type="button"
      aria-label="переставить график"
      title="Перетащите, чтобы переставить (на телефоне — задержите палец)"
      className="-m-1 cursor-grab select-none touch-none p-2 text-base text-slate-500 hover:text-slate-300 active:cursor-grabbing"
      {...attributes}
      {...listeners}
    >
      ☰
    </button>
  )
  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={isDragging ? 'relative z-10 opacity-80' : ''}
    >
      {children(handle)}
    </div>
  )
}

/** unix-секунды ↔ значение input type="datetime-local" (локальное время). */
function toLocalInput(ts: number): string {
  const date = new Date(ts * 1000)
  const pad = (n: number) => String(n).padStart(2, '0')
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  )
}

function fromLocalInput(value: string): number | undefined {
  const ms = new Date(value).getTime()
  return Number.isFinite(ms) ? Math.floor(ms / 1000) : undefined
}

function ChartPanelCard({
  panel,
  devices,
  sensors,
  dragHandle,
  quiet,
  onChange,
  onRemove,
}: {
  panel: ChartPanel
  devices: Device[]
  sensors: Sensor[]
  dragHandle: ReactNode
  quiet: boolean
  onChange: (patch: Partial<ChartPanel>) => void
  onRemove: () => void
}) {
  const isCustom = panel.period === 'custom'
  const period = PERIODS.find((p) => p.key === panel.period) ?? PERIODS[2]
  // from округляется до минуты — ключ запроса стабилен между рендерами
  const slidingFrom = useMemo(
    () => Math.floor((Date.now() / 1000 - period.seconds) / 60) * 60,
    [period.seconds],
  )
  const nowTs = useMemo(() => Math.floor(Date.now() / 1000 / 60) * 60, [])

  const customFrom = panel.from_ts
  const customTo = panel.to_ts
  const customValid =
    customFrom !== undefined && customTo !== undefined && customFrom < customTo
  const spanSeconds = isCustom
    ? customValid
      ? customTo - customFrom
      : 0
    : period.seconds
  // сырьё: окно ≤ 2 суток и не старше ретенции; иначе часовые агрегаты
  const agg: 'raw' | 'hourly' = isCustom
    ? spanSeconds <= 2 * 86_400 &&
      customValid &&
      customFrom >= nowTs - RAW_RETENTION_SECONDS
      ? 'raw'
      : 'hourly'
    : period.agg

  const fallbackSource =
    devices[0] !== undefined
      ? `device:${devices[0].uuid}`
      : sensors[0] !== undefined
        ? `sensor:${sensors[0].id}`
        : ''
  const selectedSource = panel.source !== '' ? panel.source : fallbackSource
  const [sourceType, sourceId] = selectedSource.split(':', 2) as [
    'device' | 'sensor',
    string,
  ]
  const metricOptions = sourceType === 'sensor' ? SENSOR_METRICS : DEVICE_METRICS
  const activeMetric = metricOptions.some((entry) => entry.key === panel.metric)
    ? panel.metric
    : metricOptions[0].key

  const series = useTelemetry({
    source_type: sourceType,
    source_id: sourceId ?? '',
    metric: activeMetric,
    agg,
    from_ts: isCustom ? (customFrom ?? 0) : slidingFrom,
    to_ts: isCustom ? customTo : undefined,
    enabled: !isCustom || customValid,
  })

  if (selectedSource === '') {
    return (
      <p className="text-sm text-slate-400">
        Графики появятся, когда будет хотя бы один бризер или датчик.
      </p>
    )
  }

  const selectClass =
    'rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm'
  const periodButton = (active: boolean) =>
    `rounded-lg px-2 py-1.5 text-sm transition-colors ${
      active
        ? 'bg-sky-600 text-white'
        : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
    }`

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
        <div className="flex items-center gap-2">
          {dragHandle}
          <select
            value={selectedSource}
            onChange={(event) => onChange({ source: event.target.value })}
            className={`${selectClass} min-w-0 flex-1 sm:flex-none`}
          >
            {devices.map((device) => (
              <option key={device.uuid} value={`device:${device.uuid}`}>
                {device.name}
              </option>
            ))}
            {sensors.map((sensor) => (
              <option key={`s${sensor.id}`} value={`sensor:${sensor.id}`}>
                Датчик · {sensor.name}
              </option>
            ))}
          </select>
          <select
            value={activeMetric}
            onChange={(event) => onChange({ metric: event.target.value })}
            className={`${selectClass} min-w-0 flex-1 sm:flex-none`}
          >
            {metricOptions.map((entry) => (
              <option key={entry.key} value={entry.key}>
                {entry.label}
              </option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-2 sm:flex-1">
          <div className="flex gap-1">
            {PERIODS.map((entry) => (
              <button
                key={entry.key}
                type="button"
                onClick={() =>
                  onChange({
                    period: entry.key,
                    from_ts: undefined,
                    to_ts: undefined,
                  })
                }
                className={periodButton(panel.period === entry.key)}
              >
                {entry.label}
              </button>
            ))}
            <button
              type="button"
              aria-label="свой диапазон"
              title="Свой диапазон дат"
              onClick={() =>
                isCustom
                  ? onChange({ period: '24h', from_ts: undefined, to_ts: undefined })
                  : onChange({
                      period: 'custom',
                      from_ts: nowTs - 86_400,
                      to_ts: nowTs,
                    })
              }
              className={periodButton(isCustom)}
            >
              ⋯
            </button>
          </div>
          <button
            type="button"
            onClick={onRemove}
            className="ml-auto text-sm text-slate-500 hover:text-rose-400"
          >
            убрать
          </button>
        </div>
      </div>

      {isCustom && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <input
            type="datetime-local"
            value={customFrom !== undefined ? toLocalInput(customFrom) : ''}
            onChange={(event) =>
              onChange({ from_ts: fromLocalInput(event.target.value) })
            }
            aria-label="начало диапазона"
            className={selectClass}
          />
          <span className="text-slate-500">—</span>
          <input
            type="datetime-local"
            value={customTo !== undefined ? toLocalInput(customTo) : ''}
            onChange={(event) =>
              onChange({ to_ts: fromLocalInput(event.target.value) })
            }
            aria-label="конец диапазона"
            className={selectClass}
          />
          {!customValid && (
            <span className="text-xs text-rose-400">
              начало должно быть раньше конца
            </span>
          )}
        </div>
      )}

      <Card>
        {quiet ? (
          <div
            className="h-64 w-full rounded-xl bg-slate-800/40"
            aria-hidden="true"
          />
        ) : isCustom && !customValid ? (
          <p className="py-10 text-center text-sm text-slate-400">
            Задайте корректный диапазон дат.
          </p>
        ) : series.isPending ? (
          <Spinner label="Загружаем серию…" />
        ) : series.isError ? (
          <p className="text-sm text-rose-400">Не удалось загрузить телеметрию.</p>
        ) : (
          <SeriesChart
            agg={agg}
            raw={series.data.raw ?? []}
            hourly={series.data.hourly ?? []}
            longRange={spanSeconds > 2 * 86_400}
          />
        )}
      </Card>
      {agg === 'hourly' && (
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
