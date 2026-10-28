// Настройки прибора Xiaomi на самом устройстве: экран, звук, ночной режим,
// увлажнение, обслуживание. Как и карточка, шлёт команду на каждое
// изменение — состояние берётся из общего кэша приборов (живое, по WS).

import { useState } from 'react'

import { useApplianceAction, useApplianceCommand, useAppliances } from '../api/queries'
import type { ApplianceAction, ApplianceCommand, ApplianceState, ScreenBrightness } from '../api/types'
import { formatMinutesLeft, minutesToTime, timeToMinutes } from '../lib/appliance'
import { Segmented } from './ApplianceCard'
import { Button, Dialog, FieldRow, Fieldset, Spinner, Toggle, inputClass } from './ui'

const BRIGHTNESS: [ScreenBrightness, string][] = [
  ['auto', 'Авто'],
  ['bright', 'Ярко'],
  ['medium', 'Средне'],
  ['dim', 'Тускло'],
]

const DISPLAY_METRICS: [ApplianceState['display_metric'], string][] = [
  ['pm25', 'PM2.5'],
  ['pm1', 'PM1'],
  ['pm10', 'PM10'],
]

const CONFIRM: Partial<Record<ApplianceAction, string>> = {
  reset_humidifier_filter: 'Сбросить ресурс фильтра увлажнения на 100 %? Делайте это только после замены фильтра.',
  reset_purifier_filter: 'Сбросить ресурс фильтра очистки на 100 %? Делайте это только после замены фильтра.',
  self_clean_start: 'Запустить самоочистку? Прибор будет занят, пока она идёт.',
}

export default function ApplianceSettings({ applianceId, onClose }: { applianceId: string; onClose: () => void }) {
  const appliances = useAppliances()
  const command = useApplianceCommand()
  const action = useApplianceAction()
  const appliance = appliances.data?.find((item) => item.id === applianceId)
  const state = appliance?.state ?? null
  const enabled = appliance?.online === true && state !== null

  const send = (body: ApplianceCommand) => command.mutate({ id: applianceId, body })
  const run = (name: ApplianceAction) => {
    const question = CONFIRM[name]
    if (question === undefined || confirm(question)) action.mutate({ id: applianceId, action: name })
  }

  return (
    <Dialog title={`Настройки · ${appliance?.name ?? 'прибор'}`} onClose={onClose}>
      {appliance === undefined ? (
        <Spinner label="Загрузка…" />
      ) : state === null ? (
        <p className="text-sm text-slate-500">Нет данных — ждём прибор…</p>
      ) : (
        <div className={`flex flex-col gap-3 ${enabled ? '' : 'opacity-60'}`}>
          {!appliance.online && <p className="text-sm text-amber-300">Прибор не на связи — настройки недоступны.</p>}
          {(command.isError || action.isError) && (
            <p className="text-sm text-rose-300">
              Не применилось: {(command.error ?? action.error)?.message}
            </p>
          )}

          <Fieldset title="Экран и звук">
            <Toggle label="Экран" checked={state.screen} disabled={!enabled} onChange={(screen) => send({ screen })} />
            <span className="text-xs text-slate-500">Яркость</span>
            <Segmented
              label="Яркость экрана"
              value={state.screen_brightness}
              options={BRIGHTNESS}
              disabled={!enabled}
              onChange={(screen_brightness) => send({ screen_brightness })}
            />
            <span className="mt-1 text-xs text-slate-500">Частицы на экране</span>
            <Segmented
              label="Показатель на экране"
              value={state.display_metric}
              options={DISPLAY_METRICS}
              disabled={!enabled}
              onChange={(display_metric) => send({ display_metric })}
            />
            <Toggle label="Звук кнопок" checked={state.sound} disabled={!enabled} onChange={(sound) => send({ sound })} />
            <Toggle
              label="Блокировка кнопок"
              checked={state.child_lock}
              disabled={!enabled}
              onChange={(child_lock) => send({ child_lock })}
            />
          </Fieldset>

          <Fieldset title="Ночной режим" hint="Расписание ночного режима самого прибора (как в Mi Home).">
            <Toggle
              label="Включён"
              checked={state.night_mode}
              disabled={!enabled}
              onChange={(night_mode) => send({ night_mode })}
            />
            <TimeRange
              start={state.night_start}
              end={state.night_end}
              disabled={!enabled}
              onChange={(range) => send(range)}
            />
          </Fieldset>

          <Fieldset title="Увлажнение">
            <Toggle
              label="Сушка фильтра после выключения"
              checked={state.auto_dry}
              disabled={!enabled}
              onChange={(auto_dry) => send({ auto_dry })}
            />
            <Toggle
              label="Защита от переувлажнения"
              checked={state.overwet_protect}
              disabled={!enabled}
              onChange={(overwet_protect) => send({ overwet_protect })}
            />
          </Fieldset>

          <Fieldset title="Обслуживание">
            <MaintenanceRow
              label="Самоочистка"
              running={state.status === 'cleaning'}
              left={state.clean_remaining}
              disabled={!enabled || action.isPending}
              onStart={() => run('self_clean_start')}
              onStop={() => run('self_clean_stop')}
            />
            <MaintenanceRow
              label="Сушка фильтра"
              running={state.status === 'drying'}
              left={state.dry_remaining}
              disabled={!enabled || action.isPending}
              onStart={() => run('dry_start')}
              onStop={() => run('dry_stop')}
            />
            <FieldRow label={`Фильтр увлажнения · ${state.humidifier_filter_life}%`}>
              <Button variant="ghost" disabled={!enabled || action.isPending} onClick={() => run('reset_humidifier_filter')}>
                Сбросить
              </Button>
            </FieldRow>
            <FieldRow label={`Фильтр очистки · ${state.purifier_filter_life}%`}>
              <Button variant="ghost" disabled={!enabled || action.isPending} onClick={() => run('reset_purifier_filter')}>
                Сбросить
              </Button>
            </FieldRow>
          </Fieldset>
        </div>
      )}
    </Dialog>
  )
}

function MaintenanceRow({
  label,
  running,
  left,
  disabled,
  onStart,
  onStop,
}: {
  label: string
  running: boolean
  left: number
  disabled: boolean
  onStart: () => void
  onStop: () => void
}) {
  return (
    <FieldRow label={running ? `${label} · осталось ${formatMinutesLeft(left)}` : label}>
      <Button variant="ghost" disabled={disabled} onClick={running ? onStop : onStart}>
        {running ? 'Остановить' : 'Запустить'}
      </Button>
    </FieldRow>
  )
}

/** «с … по …» в минутах от полуночи; уходит, только когда время введено целиком. */
export function TimeRange({
  start,
  end,
  disabled,
  onChange,
}: {
  start: number
  end: number
  disabled: boolean
  onChange: (range: { night_start?: number; night_end?: number }) => void
}) {
  const [draft, setDraft] = useState<{ start: string; end: string } | null>(null)
  const shown = draft ?? { start: minutesToTime(start), end: minutesToTime(end) }
  const commit = (field: 'start' | 'end', value: string) => {
    setDraft({ ...shown, [field]: value })
    const minutes = timeToMinutes(value)
    if (minutes === null || minutes === (field === 'start' ? start : end)) return
    onChange(field === 'start' ? { night_start: minutes } : { night_end: minutes })
  }
  return (
    <div className="flex items-center justify-between gap-3 py-1 text-sm text-slate-200">
      <span>С</span>
      <input
        type="time"
        aria-label="Начало ночного режима"
        disabled={disabled}
        value={shown.start}
        onChange={(event) => commit('start', event.target.value)}
        onBlur={() => setDraft(null)}
        className={inputClass}
      />
      <span>до</span>
      <input
        type="time"
        aria-label="Конец ночного режима"
        disabled={disabled}
        value={shown.end}
        onChange={(event) => commit('end', event.target.value)}
        onBlur={() => setDraft(null)}
        className={inputClass}
      />
    </div>
  )
}
