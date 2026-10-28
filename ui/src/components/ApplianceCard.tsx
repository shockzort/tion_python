// Карточка прибора Xiaomi (увлажнитель-очиститель) — презентационная.
// Свёрнута: показания как у датчика + режим одной строкой; развёрнута —
// ручное управление. Редкие настройки (экран, звук, ночь…) — в Устройствах.

import type {
  Appliance,
  ApplianceCommand,
  ApplianceState,
  HumidifierMode,
  PurifierMode,
  Sensor,
} from '../api/types'
import {
  HUMIDIFIER_MODE_LABELS,
  PURIFIER_MODE_LABELS,
  formatMinutesLeft,
} from '../lib/appliance'
import { usePersistentState } from '../lib/usePersistentState'
import { CompactMetrics } from './SensorCard'
import { Badge, Card, Toggle } from './ui'

export type ApplianceCardProps = {
  appliance: Appliance
  /** встроенный датчик прибора (xiaomi_miio:<id>) — для строки показаний */
  sensor?: Sensor
  onCommand: (body: ApplianceCommand) => void
}

const TARGET_MIN = 40
const TARGET_MAX = 70
const TARGET_STEP = 5
const FAVORITE_MAX = 9
const OFF_TIMER_HOURS = [1, 2, 3, 4, 5, 6, 7, 8]
const FILTER_WARN_PERCENT = 10

const WATER_LABELS: Record<ApplianceState['water_state'], string> = {
  no_tank: 'бак снят',
  low: 'мало воды',
  normal: '',
  full: 'бак полон',
  unknown: '',
}

const STATUS_LABELS: Partial<Record<ApplianceState['status'], string>> = {
  drying: 'сушка',
  cleaning: 'самоочистка',
}

function applianceSummary(state: ApplianceState): string {
  if (!state.power) return 'Выключен'
  if (state.function === 'humidify') {
    const mode =
      state.humidifier_mode === 'constant'
        ? `цель ${state.target_humidity}%`
        : state.humidifier_mode === 'fan'
          ? `скорость ${state.humidifier_fan_level}`
          : HUMIDIFIER_MODE_LABELS[state.humidifier_mode].toLowerCase()
    return `Увлажнение · ${mode}`
  }
  const mode =
    state.purifier_mode === 'fan'
      ? `скорость ${state.purifier_fan_level}`
      : state.purifier_mode === 'favorite'
        ? `уровень ${state.purifier_favorite_level}`
        : PURIFIER_MODE_LABELS[state.purifier_mode].toLowerCase()
  return `Очистка · ${mode}`
}

export default function ApplianceCard({
  appliance,
  sensor,
  onCommand,
}: ApplianceCardProps) {
  const { state } = appliance
  const enabled = appliance.online && state !== null
  const active = enabled && state.power
  const [collapsed, setCollapsed] = usePersistentState(
    `eb:card-collapsed:appliance:${appliance.id}`,
    false,
  )
  const hasSensorLine = sensor !== undefined && (sensor.last_values ?? null) !== null

  return (
    <Card className={`flex flex-col py-3 ${collapsed ? 'gap-1.5' : 'gap-3'}`}>
      <header className="flex items-start justify-between gap-2">
        <button
          type="button"
          aria-expanded={!collapsed}
          title={collapsed ? 'Развернуть' : 'Свернуть'}
          onClick={() => setCollapsed((value) => !value)}
          className="flex min-w-0 items-start gap-1.5 text-left"
        >
          <span
            aria-hidden="true"
            className={`mt-0.5 text-xs text-slate-500 transition-transform ${
              collapsed ? '' : 'rotate-90'
            }`}
          >
            ▸
          </span>
          <span className="min-w-0">
            <span className="block truncate font-medium">{appliance.name}</span>
            {!collapsed && (
              <span className="block text-xs text-slate-500">Увлажнитель-очиститель</span>
            )}
          </span>
        </button>
        <div className="flex flex-wrap justify-end gap-1.5">
          {!appliance.online && <Badge tone="error">нет связи</Badge>}
          {appliance.online && !collapsed && <Badge tone="ok">на связи</Badge>}
          {state !== null && STATUS_LABELS[state.status] && (
            <Badge tone="ok">{STATUS_LABELS[state.status]}</Badge>
          )}
          {state !== null && WATER_LABELS[state.water_state] && (
            <Badge tone="warn">{WATER_LABELS[state.water_state]}</Badge>
          )}
          {state !== null && state.fault !== 0 && (
            <Badge tone="error">ошибка {state.fault}</Badge>
          )}
        </div>
      </header>

      {state === null ? (
        <p className="text-sm text-slate-500">Нет данных — ждём прибор…</p>
      ) : collapsed ? (
        <div className="flex flex-col gap-1 pl-4">
          {hasSensorLine ? (
            <CompactMetrics sensor={sensor} />
          ) : (
            <p className="text-sm tabular-nums text-slate-400">
              <span className="font-bold text-slate-200">{state.humidity}</span> % ·{' '}
              <span className="font-bold text-slate-200">{state.temperature}</span> °C · PM2.5{' '}
              <span className="font-bold text-slate-200">{state.pm25}</span>
            </p>
          )}
          <p className="text-xs text-slate-500">
            {applianceSummary(state)} · вода {state.water_level}%
            {state.off_timer && ` · выкл. через ${formatMinutesLeft(state.off_timer_remaining)}`}
          </p>
        </div>
      ) : (
        <div className={appliance.online ? '' : 'opacity-60'}>
          <Toggle
            label={state.power ? 'Включён' : 'Выключен'}
            checked={state.power}
            disabled={!enabled}
            onChange={(power) => onCommand({ power })}
          />

          <Segmented
            label="Функция"
            value={state.function}
            options={[
              ['humidify', 'Увлажнение'],
              ['purify', 'Очистка'],
            ]}
            disabled={!active}
            onChange={(fn) => onCommand({ function: fn })}
          />

          {state.function === 'humidify' ? (
            <>
              <Segmented
                label="Режим увлажнения"
                value={state.humidifier_mode}
                options={humidifierModes(state.humidifier_mode)}
                disabled={!active}
                onChange={(humidifier_mode) => onCommand({ humidifier_mode })}
              />
              {state.humidifier_mode === 'constant' && (
                <TargetStepper
                  value={state.target_humidity}
                  disabled={!active}
                  onChange={(target_humidity) => onCommand({ target_humidity })}
                />
              )}
              {state.humidifier_mode === 'fan' && (
                <LevelPicker
                  value={state.humidifier_fan_level}
                  disabled={!active}
                  onChange={(humidifier_fan_level) => onCommand({ humidifier_fan_level })}
                />
              )}
            </>
          ) : (
            <>
              <Segmented
                label="Режим очистки"
                value={state.purifier_mode}
                options={Object.entries(PURIFIER_MODE_LABELS) as [PurifierMode, string][]}
                disabled={!active}
                onChange={(purifier_mode) => onCommand({ purifier_mode })}
              />
              {state.purifier_mode === 'fan' && (
                <LevelPicker
                  value={state.purifier_fan_level}
                  disabled={!active}
                  onChange={(purifier_fan_level) => onCommand({ purifier_fan_level })}
                />
              )}
              {state.purifier_mode === 'favorite' && (
                <Stepper
                  label="Уровень"
                  value={state.purifier_favorite_level}
                  display={String(state.purifier_favorite_level)}
                  min={0}
                  max={FAVORITE_MAX}
                  lowerLabel="тише"
                  upperLabel="сильнее"
                  disabled={!active}
                  onChange={(purifier_favorite_level) => onCommand({ purifier_favorite_level })}
                />
              )}
            </>
          )}

          <OffTimer state={state} disabled={!active} onCommand={onCommand} />

          <footer className="mt-2 flex flex-wrap justify-between gap-x-4 gap-y-1 border-t border-slate-800 pt-2 text-xs text-slate-500">
            <span>
              {state.humidity}% · {state.temperature}°C · PM2.5 {state.pm25}
            </span>
            <span>вода {state.water_level}%</span>
            <span className={filterTone(state.humidifier_filter_life)}>
              фильтр увлажнения {state.humidifier_filter_life}%
            </span>
            <span className={filterTone(state.purifier_filter_life)}>
              фильтр очистки {state.purifier_filter_life}%
            </span>
          </footer>
        </div>
      )}
    </Card>
  )
}

/**
 * «Избранный» режим увлажнения задаётся только в Mi Home и без своей
 * скорости в протоколе — в выборе его нет; если прибор уже в нём (включили
 * с кнопки или из приложения), режим показывается, чтобы не врать.
 */
function humidifierModes(current: HumidifierMode): [HumidifierMode, string][] {
  return (Object.entries(HUMIDIFIER_MODE_LABELS) as [HumidifierMode, string][]).filter(
    ([mode]) => mode !== 'favorite' || current === 'favorite',
  )
}

function OffTimer({
  state,
  disabled,
  onCommand,
}: {
  state: ApplianceState
  disabled: boolean
  onCommand: (body: ApplianceCommand) => void
}) {
  return (
    <div className="mt-2 flex items-center justify-between gap-2 text-sm text-slate-200">
      <span>
        Выключить через
        {state.off_timer && (
          <span className="ml-1 text-xs text-slate-500">
            (осталось {formatMinutesLeft(state.off_timer_remaining)})
          </span>
        )}
      </span>
      <select
        aria-label="Таймер выключения"
        disabled={disabled}
        value={state.off_timer ? state.off_timer_hours : 0}
        onChange={(event) => {
          const hours = Number(event.target.value)
          onCommand(hours === 0 ? { off_timer: false } : { off_timer_hours: hours, off_timer: true })
        }}
        className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-sm disabled:opacity-50"
      >
        <option value={0}>не выключать</option>
        {OFF_TIMER_HOURS.map((hours) => (
          <option key={hours} value={hours}>
            {hours} ч
          </option>
        ))}
      </select>
    </div>
  )
}

function filterTone(percent: number): string {
  return percent < FILTER_WARN_PERCENT ? 'text-rose-400' : ''
}

export function Segmented<T extends string>({
  label,
  value,
  options,
  disabled,
  onChange,
}: {
  label: string
  value: T
  options: [T, string][]
  disabled: boolean
  onChange: (value: T) => void
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className="mt-2 grid gap-1 rounded-xl bg-slate-800/60 p-1 text-xs sm:text-sm"
      style={{ gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` }}
    >
      {options.map(([option, title]) => {
        const active = option === value
        return (
          <button
            key={option}
            type="button"
            disabled={disabled || active}
            aria-pressed={active}
            onClick={() => onChange(option)}
            className={`rounded-lg px-1 py-1.5 transition-colors ${
              active
                ? 'bg-accent font-semibold text-slate-950'
                : 'text-slate-300 hover:bg-slate-700 disabled:opacity-50'
            }`}
          >
            {title}
          </button>
        )
      })}
    </div>
  )
}

function TargetStepper({
  value,
  disabled,
  onChange,
}: {
  value: number
  disabled: boolean
  onChange: (value: number) => void
}) {
  // шаг 5 % — как на самом приборе; крайние значения прижимаются к диапазону
  const lower = Math.max(TARGET_MIN, Math.ceil(value / TARGET_STEP) * TARGET_STEP - TARGET_STEP)
  const upper = Math.min(TARGET_MAX, Math.floor(value / TARGET_STEP) * TARGET_STEP + TARGET_STEP)
  return (
    <Stepper
      label="Целевая влажность"
      value={value}
      display={`${value}%`}
      min={TARGET_MIN}
      max={TARGET_MAX}
      lowerLabel="суше"
      upperLabel="влажнее"
      disabled={disabled}
      onChange={(next) => onChange(next < value ? lower : upper)}
    />
  )
}

function Stepper({
  label,
  value,
  display,
  min,
  max,
  lowerLabel,
  upperLabel,
  disabled,
  onChange,
}: {
  label: string
  value: number
  display: string
  min: number
  max: number
  lowerLabel: string
  upperLabel: string
  disabled: boolean
  onChange: (value: number) => void
}) {
  return (
    <div className="mt-2 flex items-center justify-between text-sm text-slate-200">
      <span>{label}</span>
      <div className="flex items-center gap-1">
        <StepButton label={lowerLabel} disabled={disabled || value <= min} onClick={() => onChange(value - 1)}>
          −
        </StepButton>
        <span className="w-12 text-center font-semibold text-sky-400">{display}</span>
        <StepButton label={upperLabel} disabled={disabled || value >= max} onClick={() => onChange(value + 1)}>
          +
        </StepButton>
      </div>
    </div>
  )
}

function LevelPicker({
  value,
  disabled,
  onChange,
}: {
  value: number
  disabled: boolean
  onChange: (value: number) => void
}) {
  return (
    <Segmented
      label="Скорость"
      value={String(value)}
      options={[
        ['1', 'Скорость 1'],
        ['2', 'Скорость 2'],
        ['3', 'Скорость 3'],
      ]}
      disabled={disabled}
      onChange={(level) => onChange(Number(level))}
    />
  )
}

function StepButton({
  label,
  disabled,
  onClick,
  children,
}: {
  label: string
  disabled: boolean
  onClick: () => void
  children: string
}) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className="size-7 rounded-lg bg-slate-800 text-slate-200 hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
    >
      {children}
    </button>
  )
}
