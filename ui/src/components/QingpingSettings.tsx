// Настройки Qingping CGDN1 на самом датчике (по MQTT вместо штатного
// приложения). Конфиг читается с датчика при открытии; правки копятся в
// черновике и уходят одной записью — каждая запись это обмен по MQTT до 10 с.

import { useState } from 'react'

import { useSaveSensorSettings, useSensorSettings } from '../api/queries'
import type { QingpingScreensaver, QingpingSettings as Settings } from '../api/types'
import { minutesToTime, timeToMinutes } from '../lib/appliance'
import { Button, Dialog, FieldRow, Fieldset, Spinner, Toggle, inputClass } from './ui'

const SCREENSAVERS: [QingpingScreensaver, string][] = [
  ['rotate', 'Показатели по очереди'],
  ['current', 'Текущий показатель'],
  ['time_rotate', 'Время + по очереди'],
  ['time_current', 'Время + текущий'],
]

const DISPLAY_OFF: [number, string][] = [
  [0, 'не гасить'],
  [30, '30 с'],
  [60, '1 мин'],
  [120, '2 мин'],
  [300, '5 мин'],
  [600, '10 мин'],
]

const SLIDE: [number, string][] = [
  [10, '10 с'],
  [30, '30 с'],
  [60, '1 мин'],
  [120, '2 мин'],
]

const POWER_OFF: [number, string][] = [
  [0, 'никогда'],
  [15, '15 мин'],
  [30, '30 мин'],
  [60, '1 ч'],
]

const DEFAULT_NIGHT = { night_start: 23 * 60, night_end: 7 * 60 }

export default function QingpingSettings({
  sensorId,
  name,
  onClose,
}: {
  sensorId: number
  name: string
  onClose: () => void
}) {
  const current = useSensorSettings(sensorId)
  const save = useSaveSensorSettings()
  const [draft, setDraft] = useState<Settings>({})

  const base = current.data?.settings
  const value = { ...base, ...draft }
  const changed = (Object.keys(draft) as (keyof Settings)[]).filter(
    (key) => JSON.stringify(draft[key]) !== JSON.stringify(base?.[key]),
  )
  const set = (patch: Settings) => setDraft((prev) => ({ ...prev, ...patch }))
  const nightOn = value.night_start !== undefined && value.night_start !== value.night_end

  const submit = () => {
    const body = Object.fromEntries(changed.map((key) => [key, draft[key]])) as Settings
    save.mutate({ id: sensorId, body }, { onSuccess: () => setDraft({}) })
  }

  return (
    <Dialog title={`Настройки · ${name}`} onClose={onClose}>
      {current.isPending ? (
        <Spinner label="Читаем настройки с датчика…" />
      ) : current.isError || base === undefined ? (
        <div className="flex flex-col gap-2 text-sm">
          <p className="text-rose-300">Не удалось прочитать настройки: {current.error?.message}</p>
          <Button variant="ghost" onClick={() => void current.refetch()}>
            Повторить
          </Button>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <Fieldset title="Экран" hint="Яркость экрана по MQTT не настраивается — её нет в протоколе датчика.">
            {value.screensaver !== undefined && (
              <FieldRow label="Заставка">
                <Select
                  label="Заставка"
                  value={value.screensaver}
                  options={SCREENSAVERS}
                  onChange={(screensaver) => set({ screensaver })}
                />
              </FieldRow>
            )}
            {value.display_off_time !== undefined && (
              <FieldRow label="Гасить экран через">
                <Select
                  label="Гасить экран через"
                  value={value.display_off_time}
                  options={withCurrent(DISPLAY_OFF, value.display_off_time, 'с')}
                  onChange={(display_off_time) => set({ display_off_time })}
                />
              </FieldRow>
            )}
            {value.auto_slide_time !== undefined && (
              <FieldRow label="Смена показателя">
                <Select
                  label="Смена показателя"
                  value={value.auto_slide_time}
                  options={withCurrent(SLIDE, value.auto_slide_time, 'с')}
                  onChange={(auto_slide_time) => set({ auto_slide_time })}
                />
              </FieldRow>
            )}
          </Fieldset>

          {value.night_start !== undefined && value.night_end !== undefined && (
            <Fieldset title="Ночной режим" hint="В эти часы подсветка выключена.">
              <Toggle
                label="Включён"
                checked={nightOn}
                onChange={(on) => set(on ? DEFAULT_NIGHT : { night_start: 0, night_end: 0 })}
              />
              {nightOn && (
                <div className="flex items-center justify-between gap-3 py-1 text-sm text-slate-200">
                  <span>С</span>
                  <TimeInput
                    label="Начало ночного режима"
                    minutes={value.night_start}
                    onChange={(night_start) => set({ night_start })}
                  />
                  <span>до</span>
                  <TimeInput
                    label="Конец ночного режима"
                    minutes={value.night_end}
                    onChange={(night_end) => set({ night_end })}
                  />
                </div>
              )}
            </Fieldset>
          )}

          <Fieldset title="Поправки показаний" hint="Прибавляются к измерению на самом датчике — графики и автоматика получат уже исправленные значения.">
            <OffsetRow label="Температура, °C" step={0.1} value={value.temperature_offset} onChange={(temperature_offset) => set({ temperature_offset })} />
            <OffsetRow label="Влажность, %" step={0.1} value={value.humidity_offset} onChange={(humidity_offset) => set({ humidity_offset })} />
            <OffsetRow label="CO₂, ppm" step={1} value={value.co2_offset} onChange={(co2_offset) => set({ co2_offset })} />
            <OffsetRow label="PM2.5, мкг/м³" step={1} value={value.pm25_offset} onChange={(pm25_offset) => set({ pm25_offset })} />
            <OffsetRow label="PM10, мкг/м³" step={1} value={value.pm10_offset} onChange={(pm10_offset) => set({ pm10_offset })} />
            {value.co2_asc !== undefined && (
              <Toggle
                label="Автокалибровка CO₂"
                checked={value.co2_asc}
                onChange={(co2_asc) => set({ co2_asc })}
              />
            )}
          </Fieldset>

          <Fieldset title="Подсветка" hint="Пороги смены цвета индикатора, по возрастанию.">
            <Thresholds label="CO₂, ppm" values={value.co2_led_th} onChange={(co2_led_th) => set({ co2_led_th })} />
            <Thresholds label="PM2.5" values={value.pm25_led_th} onChange={(pm25_led_th) => set({ pm25_led_th })} />
          </Fieldset>

          <Fieldset title="Прочее">
            {value.temperature_unit !== undefined && (
              <FieldRow label="Температура в">
                <Select
                  label="Единицы температуры"
                  value={value.temperature_unit}
                  options={[
                    ['C', '°C'],
                    ['F', '°F'],
                  ]}
                  onChange={(temperature_unit) => set({ temperature_unit })}
                />
              </FieldRow>
            )}
            {value.is_12_hour !== undefined && (
              <Toggle label="12-часовой формат" checked={value.is_12_hour} onChange={(is_12_hour) => set({ is_12_hour })} />
            )}
            {value.timezone !== undefined && (
              <FieldRow label="Часовой пояс, UTC±ч">
                <input
                  type="number"
                  aria-label="Часовой пояс"
                  step={0.5}
                  min={-12}
                  max={14}
                  value={value.timezone}
                  onChange={(event) => set({ timezone: Number(event.target.value) })}
                  className={`${inputClass} w-20`}
                />
              </FieldRow>
            )}
            {value.power_off_time !== undefined && (
              <FieldRow label="Выключаться от батареи через">
                <Select
                  label="Автовыключение от батареи"
                  value={value.power_off_time}
                  options={withCurrent(POWER_OFF, value.power_off_time, 'мин')}
                  onChange={(power_off_time) => set({ power_off_time })}
                />
              </FieldRow>
            )}
          </Fieldset>

          {save.isError && <p className="text-sm text-rose-300">Не сохранилось: {save.error.message}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" disabled={changed.length === 0 || save.isPending} onClick={() => setDraft({})}>
              Сбросить
            </Button>
            <Button disabled={changed.length === 0 || save.isPending} onClick={submit}>
              {save.isPending ? 'Сохраняем…' : 'Сохранить'}
            </Button>
          </div>
        </div>
      )}
    </Dialog>
  )
}

/** Значение датчика, которого нет в списке, остаётся выбранным. */
function withCurrent(options: [number, string][], current: number, unit: string): [number, string][] {
  return options.some(([option]) => option === current)
    ? options
    : [...options, [current, `${current} ${unit}`] as [number, string]].sort((a, b) => a[0] - b[0])
}

function Select<T extends string | number>({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: T
  options: [T, string][]
  onChange: (value: T) => void
}) {
  return (
    <select
      aria-label={label}
      value={String(value)}
      onChange={(event) => {
        const picked = options.find(([option]) => String(option) === event.target.value)
        if (picked) onChange(picked[0])
      }}
      className={inputClass}
    >
      {options.map(([option, title]) => (
        <option key={String(option)} value={String(option)}>
          {title}
        </option>
      ))}
    </select>
  )
}

function TimeInput({ label, minutes, onChange }: { label: string; minutes: number; onChange: (minutes: number) => void }) {
  return (
    <input
      type="time"
      aria-label={label}
      value={minutesToTime(minutes)}
      onChange={(event) => {
        const parsed = timeToMinutes(event.target.value)
        if (parsed !== null) onChange(parsed)
      }}
      className={inputClass}
    />
  )
}

function OffsetRow({
  label,
  step,
  value,
  onChange,
}: {
  label: string
  step: number
  value: number | undefined
  onChange: (value: number) => void
}) {
  if (value === undefined) return null
  return (
    <FieldRow label={label}>
      <input
        type="number"
        aria-label={`Поправка: ${label}`}
        step={step}
        value={value}
        onChange={(event) => {
          const parsed = Number(event.target.value)
          if (event.target.value !== '' && Number.isFinite(parsed)) onChange(parsed)
        }}
        className={`${inputClass} w-24 text-right`}
      />
    </FieldRow>
  )
}

function Thresholds({
  label,
  values,
  onChange,
}: {
  label: string
  values: number[] | undefined
  onChange: (values: number[]) => void
}) {
  if (values === undefined) return null
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 py-1 text-sm text-slate-200">
      <span>{label}</span>
      <div className="flex gap-1">
        {values.map((threshold, index) => (
          <input
            key={index}
            type="number"
            aria-label={`${label}: порог ${index + 1}`}
            value={threshold}
            onChange={(event) => {
              const next = [...values]
              next[index] = Number(event.target.value)
              onChange(next)
            }}
            className={`${inputClass} w-16 text-right`}
          />
        ))}
      </div>
    </div>
  )
}
