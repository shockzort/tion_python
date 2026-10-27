// Карточка прибора Xiaomi (увлажнитель-очиститель) — презентационная

import type {
  Appliance,
  ApplianceCommand,
  ApplianceState,
  HumidifierMode,
  PurifierMode,
} from '../api/types'
import { HUMIDIFIER_MODE_LABELS, PURIFIER_MODE_LABELS } from '../lib/appliance'
import { usePersistentState } from '../lib/usePersistentState'
import { Badge, Card, Toggle } from './ui'

export type ApplianceCardProps = {
  appliance: Appliance
  onCommand: (body: ApplianceCommand) => void
}

const TARGET_MIN = 40
const TARGET_MAX = 70
const TARGET_STEP = 5
const FILTER_WARN_PERCENT = 10

const WATER_LABELS: Record<ApplianceState['water_state'], string> = {
  no_tank: 'бак снят',
  low: 'мало воды',
  normal: '',
  full: 'бак полон',
  unknown: '',
}

function summary(state: ApplianceState): string {
  if (!state.power) return 'Выключен'
  if (state.function === 'humidify') {
    const mode =
      state.humidifier_mode === 'constant'
        ? `цель ${state.target_humidity}%`
        : HUMIDIFIER_MODE_LABELS[state.humidifier_mode].toLowerCase()
    return `Увлажнение · ${mode}`
  }
  return `Очистка · ${PURIFIER_MODE_LABELS[state.purifier_mode].toLowerCase()}`
}

export default function ApplianceCard({ appliance, onCommand }: ApplianceCardProps) {
  const { state } = appliance
  const enabled = appliance.online && state !== null
  const [collapsed, setCollapsed] = usePersistentState(
    `eb:card-collapsed:appliance:${appliance.id}`,
    false,
  )

  return (
    <Card className="flex flex-col gap-3">
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
            <h3 className="font-medium">{appliance.name}</h3>
            <p className="text-xs text-slate-500">Увлажнитель-очиститель</p>
          </span>
        </button>
        <div className="flex flex-wrap justify-end gap-1.5">
          {appliance.online ? (
            <Badge tone="ok">на связи</Badge>
          ) : (
            <Badge tone="error">нет связи</Badge>
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
        <p className="text-sm text-slate-400">
          {summary(state)} · влажность {state.humidity}%
        </p>
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
            disabled={!enabled || !state.power}
            onChange={(fn) => onCommand({ function: fn })}
          />

          {state.function === 'humidify' ? (
            <>
              <Segmented
                label="Режим увлажнения"
                value={state.humidifier_mode}
                options={Object.entries(HUMIDIFIER_MODE_LABELS) as [HumidifierMode, string][]}
                disabled={!enabled || !state.power}
                onChange={(humidifier_mode) => onCommand({ humidifier_mode })}
              />
              {state.humidifier_mode === 'constant' && (
                <TargetStepper
                  value={state.target_humidity}
                  disabled={!enabled || !state.power}
                  onChange={(target_humidity) => onCommand({ target_humidity })}
                />
              )}
              {state.humidifier_mode === 'fan' && (
                <LevelPicker
                  value={state.humidifier_fan_level}
                  disabled={!enabled || !state.power}
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
                disabled={!enabled || !state.power}
                onChange={(purifier_mode) => onCommand({ purifier_mode })}
              />
              {state.purifier_mode === 'fan' && (
                <LevelPicker
                  value={state.purifier_fan_level}
                  disabled={!enabled || !state.power}
                  onChange={(purifier_fan_level) => onCommand({ purifier_fan_level })}
                />
              )}
            </>
          )}

          <div className="mt-1 grid grid-cols-2 gap-x-4">
            <Toggle
              label="Экран"
              checked={state.screen}
              disabled={!enabled}
              onChange={(screen) => onCommand({ screen })}
            />
            <Toggle
              label="Звук"
              checked={state.sound}
              disabled={!enabled}
              onChange={(sound) => onCommand({ sound })}
            />
            <Toggle
              label="Блокировка кнопок"
              checked={state.child_lock}
              disabled={!enabled}
              onChange={(child_lock) => onCommand({ child_lock })}
            />
          </div>

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

function filterTone(percent: number): string {
  return percent < FILTER_WARN_PERCENT ? 'text-rose-400' : ''
}

function Segmented<T extends string>({
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
    <div className="mt-2 flex items-center justify-between text-sm text-slate-200">
      <span>Целевая влажность</span>
      <div className="flex items-center gap-1">
        <StepButton label="суше" disabled={disabled || value <= TARGET_MIN} onClick={() => onChange(lower)}>
          −
        </StepButton>
        <span className="w-12 text-center font-semibold text-sky-400">{value}%</span>
        <StepButton label="влажнее" disabled={disabled || value >= TARGET_MAX} onClick={() => onChange(upper)}>
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
      className="size-7 rounded-lg bg-slate-800 text-slate-200 hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
    >
      {children}
    </button>
  )
}
