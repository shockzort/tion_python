// Карточка бризера (план §11) — презентационная: мутации отдаёт страница

import { useEffect, useState } from 'react'

import type { CommandBody, Device } from '../api/types'
import { Badge, Card, Toggle } from './ui'

export type DeviceCardProps = {
  device: Device
  roomName?: string
  onCommand: (body: CommandBody) => void
  onReleaseHold: () => void
}

const HEATER_TEMP_MIN = 10
const HEATER_TEMP_MAX = 30
const FILTER_WARN_DAYS = 30

function holdLabel(holdUntil: number): string {
  const time = new Date(holdUntil * 1000)
  const hh = String(time.getHours()).padStart(2, '0')
  const mm = String(time.getMinutes()).padStart(2, '0')
  return `ручное до ${hh}:${mm}`
}

export default function DeviceCard({
  device,
  roomName,
  onCommand,
  onReleaseHold,
}: DeviceCardProps) {
  const { state } = device
  const online = device.connection === 'online'
  const controlsEnabled = online && state !== null

  return (
    <Card className="flex flex-col gap-3">
      <header className="flex items-start justify-between gap-2">
        <div>
          <h3 className="font-medium">{device.name}</h3>
          {roomName && <p className="text-xs text-slate-500">{roomName}</p>}
        </div>
        <div className="flex flex-wrap justify-end gap-1.5">
          <ConnectionBadge connection={device.connection} />
          {device.hold_until !== null && (
            <Badge tone="warn">
              {holdLabel(device.hold_until)}
              <button
                type="button"
                aria-label="вернуть автоматику"
                title="Вернуть автоматику"
                onClick={onReleaseHold}
                className="ml-0.5 hover:text-amber-200"
              >
                ✕
              </button>
            </Badge>
          )}
        </div>
      </header>

      {state === null ? (
        <p className="text-sm text-slate-500">Нет данных — ждём устройство…</p>
      ) : (
        <div className={online ? '' : 'opacity-60'}>
          <Toggle
            label={state.power ? 'Включён' : 'Выключен'}
            checked={state.power}
            disabled={!controlsEnabled}
            onChange={(power) => onCommand({ power })}
          />

          <FanSlider
            value={state.fan_speed}
            disabled={!controlsEnabled || !state.power}
            onCommit={(fan_speed) => onCommand({ fan_speed })}
          />

          <div className="mt-2 flex items-center justify-between gap-3">
            <Toggle
              label="Нагрев"
              checked={state.heater}
              disabled={!controlsEnabled || !state.power}
              onChange={(heater) => onCommand({ heater })}
            />
            <TempStepper
              value={state.heater_temp}
              disabled={!controlsEnabled || !state.power}
              onChange={(heater_temp) => onCommand({ heater_temp })}
            />
          </div>

          <ModeSwitch
            mode={state.mode}
            disabled={!controlsEnabled || !state.power}
            onChange={(mode) => onCommand({ mode })}
          />

          <div className="mt-1 grid grid-cols-2 gap-x-4">
            <Toggle
              label="Звук"
              checked={state.sound}
              disabled={!controlsEnabled}
              onChange={(sound) => onCommand({ sound })}
            />
            <Toggle
              label="Подсветка"
              checked={state.light}
              disabled={!controlsEnabled}
              onChange={(light) => onCommand({ light })}
            />
          </div>

          <footer className="mt-2 flex items-center justify-between border-t border-slate-800 pt-2 text-xs text-slate-500">
            <span>приток {state.out_temp}°C · улица {state.in_temp}°C</span>
            <span
              className={
                state.filter_remain_days < FILTER_WARN_DAYS
                  ? 'text-rose-400'
                  : ''
              }
            >
              фильтр {Math.round(state.filter_remain_days)} дн
            </span>
          </footer>
        </div>
      )}
    </Card>
  )
}

function ConnectionBadge({ connection }: { connection: Device['connection'] }) {
  if (connection === 'online') {
    return <Badge tone="ok">на связи</Badge>
  }
  if (connection === 'connecting') {
    return <Badge tone="muted">подключение…</Badge>
  }
  return <Badge tone="error">нет связи</Badge>
}

function FanSlider({
  value,
  disabled,
  onCommit,
}: {
  value: number
  disabled: boolean
  onCommit: (value: number) => void
}) {
  // локальное значение на время перетаскивания; команда — при отпускании
  const [dragValue, setDragValue] = useState(value)
  useEffect(() => setDragValue(value), [value])

  const commit = () => {
    if (dragValue !== value) onCommit(dragValue)
  }

  return (
    <label className="mt-1 flex items-center gap-3 text-sm text-slate-200">
      <span className="shrink-0">Скорость</span>
      <input
        type="range"
        min={1}
        max={6}
        step={1}
        value={dragValue}
        disabled={disabled}
        aria-label="Скорость"
        onChange={(event) => setDragValue(Number(event.target.value))}
        onPointerUp={commit}
        onKeyUp={commit}
        onBlur={commit}
        className="w-full accent-sky-500 disabled:opacity-50"
      />
      <span className="w-4 shrink-0 text-center font-semibold text-sky-400">
        {dragValue}
      </span>
    </label>
  )
}

function TempStepper({
  value,
  disabled,
  onChange,
}: {
  value: number
  disabled: boolean
  onChange: (value: number) => void
}) {
  return (
    <div className="flex items-center gap-1 text-sm">
      <StepButton
        label="холоднее"
        disabled={disabled || value <= HEATER_TEMP_MIN}
        onClick={() => onChange(value - 1)}
      >
        −
      </StepButton>
      <span className="w-10 text-center text-slate-200">{value}°C</span>
      <StepButton
        label="теплее"
        disabled={disabled || value >= HEATER_TEMP_MAX}
        onClick={() => onChange(value + 1)}
      >
        +
      </StepButton>
    </div>
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

function ModeSwitch({
  mode,
  disabled,
  onChange,
}: {
  mode: 'outside' | 'recirculation'
  disabled: boolean
  onChange: (mode: 'outside' | 'recirculation') => void
}) {
  return (
    <div className="mt-2 grid grid-cols-2 gap-1 rounded-xl bg-slate-800/60 p-1 text-sm">
      <ModeButton
        active={mode === 'outside'}
        disabled={disabled}
        onClick={() => onChange('outside')}
      >
        Приток
      </ModeButton>
      <ModeButton
        active={mode === 'recirculation'}
        disabled={disabled}
        onClick={() => onChange('recirculation')}
      >
        Рециркуляция
      </ModeButton>
    </div>
  )
}

function ModeButton({
  active,
  disabled,
  onClick,
  children,
}: {
  active: boolean
  disabled: boolean
  onClick: () => void
  children: string
}) {
  return (
    <button
      type="button"
      disabled={disabled || active}
      aria-pressed={active}
      onClick={onClick}
      className={`rounded-lg py-1.5 transition-colors ${
        active
          ? 'bg-sky-600 text-white'
          : 'text-slate-300 hover:bg-slate-700 disabled:opacity-50'
      }`}
    >
      {children}
    </button>
  )
}
