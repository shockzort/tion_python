import { useState } from 'react'

import { ApiError } from '../api/client'
import {
  useDeleteScenario,
  useDeleteSchedule,
  useDeleteTrigger,
  useDevices,
  useGroups,
  useRunScenario,
  useSaveScenario,
  useSaveSchedule,
  useSaveTrigger,
  useScenarios,
  useSchedules,
  useSensors,
  useTriggers,
  type ScenarioBody,
  type ScheduleBody,
  type TriggerBody,
} from '../api/queries'
import type {
  CommandBody,
  Scenario,
  ScenarioAction,
  Schedule,
  Sensor,
  SensorMetric,
  Trigger,
  TriggerKind,
  TriggerTarget,
  TriggerToggle,
} from '../api/types'
import { Badge, Button, Card, Spinner, Toggle } from '../components/ui'
import { cronFromPreset, DAY_LABELS, describeCron, presetFromCron } from '../lib/cron'

const METRIC_LABELS: Record<SensorMetric, string> = {
  co2: 'CO₂, ppm',
  temperature: 'температура, °C',
  humidity: 'влажность, %',
}

export default function Automation() {
  const [tab, setTab] = useState<'scenarios' | 'schedules' | 'triggers'>(
    'scenarios',
  )
  return (
    <div className="flex flex-col gap-4">
      <div className="flex gap-2">
        <TabButton
          active={tab === 'scenarios'}
          label="Сценарии"
          onClick={() => setTab('scenarios')}
        />
        <TabButton
          active={tab === 'schedules'}
          label="Расписания"
          onClick={() => setTab('schedules')}
        />
        <TabButton
          active={tab === 'triggers'}
          label="Триггеры"
          onClick={() => setTab('triggers')}
        />
      </div>
      {tab === 'scenarios' && <ScenariosTab />}
      {tab === 'schedules' && <SchedulesTab />}
      {tab === 'triggers' && <TriggersTab />}
    </div>
  )
}

function TabButton({
  active,
  label,
  onClick,
}: {
  active: boolean
  label: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-xl px-4 py-2 text-sm font-medium transition-colors ${
        active
          ? 'bg-sky-600 text-white'
          : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
      }`}
    >
      {label}
    </button>
  )
}

// --- сценарии ----------------------------------------------------------------

function ScenariosTab() {
  const scenarios = useScenarios()
  const runScenario = useRunScenario()
  const deleteScenario = useDeleteScenario()
  const [editing, setEditing] = useState<Scenario | 'new' | null>(null)

  if (scenarios.isPending) return <Spinner label="Загружаем сценарии…" />
  if (scenarios.isError)
    return <p className="text-rose-400">Не удалось загрузить сценарии.</p>

  if (editing !== null) {
    return (
      <ScenarioEditor
        scenario={editing === 'new' ? null : editing}
        onClose={() => setEditing(null)}
      />
    )
  }

  return (
    <div className="flex flex-col gap-3">
      {scenarios.data.length === 0 && (
        <p className="text-sm text-slate-400">
          Сценарий — именованный набор действий: «Ночной режим», «Проветривание».
          Запускается кнопкой с дашборда, расписанием или голосом.
        </p>
      )}
      {scenarios.data.map((scenario) => (
        <Card
          key={scenario.id}
          className="flex flex-wrap items-center justify-between gap-3"
        >
          <div className="w-full min-w-0 sm:w-auto sm:flex-1">
            <p className="font-medium">{scenario.name}</p>
            <p className="truncate text-xs text-slate-400">
              {scenario.actions.length}{' '}
              {plural(scenario.actions.length, 'действие', 'действия', 'действий')}
            </p>
          </div>
          <div className="ml-auto flex shrink-0 gap-2">
            <Button
              variant="primary"
              disabled={runScenario.isPending}
              onClick={() => runScenario.mutate(scenario.id)}
            >
              Запустить
            </Button>
            <Button variant="ghost" onClick={() => setEditing(scenario)}>
              Изменить
            </Button>
            <Button
              variant="danger"
              disabled={deleteScenario.isPending}
              onClick={() => deleteScenario.mutate(scenario.id)}
            >
              Удалить
            </Button>
          </div>
        </Card>
      ))}
      <Button variant="ghost" onClick={() => setEditing('new')}>
        + Новый сценарий
      </Button>
    </div>
  )
}

/** Черновик дельты: '' — поле не менять. */
type DeltaDraft = {
  power: '' | 'on' | 'off'
  fan_speed: '' | '1' | '2' | '3' | '4' | '5' | '6'
  heater: '' | 'on' | 'off'
  heater_temp: string
  sound: '' | 'on' | 'off'
  light: '' | 'on' | 'off'
}

type ActionDraft = { target: string; delta: DeltaDraft; toggle: '' | 'on' | 'off' }

const EMPTY_DELTA: DeltaDraft = {
  power: '',
  fan_speed: '',
  heater: '',
  heater_temp: '',
  sound: '',
  light: '',
}

function isTriggerToggle(delta: CommandBody | TriggerToggle): delta is TriggerToggle {
  return 'enabled' in delta
}

function draftFromAction(action: ScenarioAction): ActionDraft {
  if (action.target_type === 'trigger' && isTriggerToggle(action.delta)) {
    return {
      target: `trigger:${action.target_id}`,
      delta: EMPTY_DELTA,
      toggle: action.delta.enabled ? 'on' : 'off',
    }
  }
  const delta = action.delta as CommandBody
  const onOff = (value: boolean | undefined): '' | 'on' | 'off' =>
    value === undefined ? '' : value ? 'on' : 'off'
  return {
    target: `${action.target_type}:${action.target_id}`,
    delta: {
      power: onOff(delta.power),
      fan_speed:
        delta.fan_speed === undefined
          ? ''
          : (String(delta.fan_speed) as DeltaDraft['fan_speed']),
      heater: onOff(delta.heater),
      heater_temp: delta.heater_temp === undefined ? '' : String(delta.heater_temp),
      sound: onOff(delta.sound),
      light: onOff(delta.light),
    },
    toggle: '',
  }
}

function actionFromDraft(draft: ActionDraft): ScenarioAction | string {
  const [targetType, targetId] = draft.target.split(':', 2)
  if (targetType === 'trigger') {
    if (draft.toggle === '') {
      return 'выберите: включить или выключить триггер'
    }
    return {
      target_type: 'trigger',
      target_id: Number(targetId),
      delta: { enabled: draft.toggle === 'on' },
    }
  }
  if (targetType !== 'device' && targetType !== 'group') {
    return 'выберите цель действия'
  }
  const delta: CommandBody = {}
  if (draft.delta.power !== '') delta.power = draft.delta.power === 'on'
  if (draft.delta.fan_speed !== '') delta.fan_speed = Number(draft.delta.fan_speed)
  if (draft.delta.heater !== '') delta.heater = draft.delta.heater === 'on'
  if (draft.delta.heater_temp !== '') {
    delta.heater_temp = Number(draft.delta.heater_temp)
  }
  if (draft.delta.sound !== '') delta.sound = draft.delta.sound === 'on'
  if (draft.delta.light !== '') delta.light = draft.delta.light === 'on'
  if (Object.keys(delta).length === 0) {
    return 'задайте хотя бы одно поле'
  }
  return {
    target_type: targetType,
    target_id: targetType === 'group' ? Number(targetId) : targetId,
    delta,
  }
}

function ScenarioEditor({
  scenario,
  onClose,
}: {
  scenario: Scenario | null
  onClose: () => void
}) {
  const devices = useDevices()
  const groups = useGroups()
  const triggers = useTriggers()
  const saveScenario = useSaveScenario()
  const [name, setName] = useState(scenario?.name ?? '')
  const [actions, setActions] = useState<ActionDraft[]>(
    scenario === null
      ? [{ target: '', delta: EMPTY_DELTA, toggle: '' }]
      : scenario.actions.map(draftFromAction),
  )
  const [error, setError] = useState<string | null>(null)

  const patchAction = (index: number, patch: Partial<ActionDraft>) => {
    setActions((current) =>
      current.map((action, i) => (i === index ? { ...action, ...patch } : action)),
    )
  }

  const save = async () => {
    setError(null)
    if (name.trim() === '') {
      setError('дайте сценарию имя')
      return
    }
    const parsed: ScenarioAction[] = []
    for (const [index, draft] of actions.entries()) {
      const result = actionFromDraft(draft)
      if (typeof result === 'string') {
        setError(`действие ${index + 1}: ${result}`)
        return
      }
      parsed.push(result)
    }
    if (parsed.length === 0) {
      setError('добавьте хотя бы одно действие')
      return
    }
    const body: ScenarioBody = { name: name.trim(), actions: parsed }
    try {
      await saveScenario.mutateAsync({ id: scenario?.id, body })
      onClose()
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : 'не удалось сохранить')
    }
  }

  return (
    <Card className="flex flex-col gap-4">
      <p className="font-medium">
        {scenario === null ? 'Новый сценарий' : `Сценарий «${scenario.name}»`}
      </p>
      <input
        value={name}
        onChange={(event) => setName(event.target.value)}
        placeholder="Название (например, Ночной режим)"
        className="rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm outline-none focus:border-sky-500"
      />

      {actions.map((action, index) => (
        <div
          key={index}
          className="flex flex-col gap-2 rounded-xl border border-slate-800 p-3"
        >
          <div className="flex items-center justify-between gap-2">
            <select
              value={action.target}
              onChange={(event) => patchAction(index, { target: event.target.value })}
              className="min-w-0 flex-1 rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm"
            >
              <option value="">Цель: устройство, группа или триггер…</option>
              {groups.data?.map((group) => (
                <option key={`g${group.id}`} value={`group:${group.id}`}>
                  Группа · {group.name}
                </option>
              ))}
              {devices.data?.map((device) => (
                <option key={device.uuid} value={`device:${device.uuid}`}>
                  {device.name}
                </option>
              ))}
              {triggers.data?.map((trigger) => (
                <option key={`t${trigger.id}`} value={`trigger:${trigger.id}`}>
                  Триггер · {trigger.name}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() =>
                setActions((current) => current.filter((_, i) => i !== index))
              }
              className="text-sm text-slate-500 hover:text-rose-400"
            >
              убрать
            </button>
          </div>
          {action.target.startsWith('trigger:') ? (
            <DeltaSelect
              label="Действие с триггером"
              value={action.toggle}
              options={[
                ['on', 'включить'],
                ['off', 'выключить'],
              ]}
              onChange={(toggle) =>
                patchAction(index, { toggle: toggle as ActionDraft['toggle'] })
              }
            />
          ) : (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            <DeltaSelect
              label="Питание"
              value={action.delta.power}
              options={ON_OFF_OPTIONS}
              onChange={(power) =>
                patchAction(index, {
                  delta: { ...action.delta, power: power as DeltaDraft['power'] },
                })
              }
            />
            <DeltaSelect
              label="Скорость"
              value={action.delta.fan_speed}
              options={['1', '2', '3', '4', '5', '6'].map((v) => [v, v])}
              onChange={(fan_speed) =>
                patchAction(index, {
                  delta: {
                    ...action.delta,
                    fan_speed: fan_speed as DeltaDraft['fan_speed'],
                  },
                })
              }
            />
            <DeltaSelect
              label="Нагрев"
              value={action.delta.heater}
              options={ON_OFF_OPTIONS}
              onChange={(heater) =>
                patchAction(index, {
                  delta: { ...action.delta, heater: heater as DeltaDraft['heater'] },
                })
              }
            />
            <DeltaSelect
              label="Температура"
              value={action.delta.heater_temp}
              options={TEMP_OPTIONS}
              onChange={(heater_temp) =>
                patchAction(index, { delta: { ...action.delta, heater_temp } })
              }
            />
            <DeltaSelect
              label="Звук"
              value={action.delta.sound}
              options={ON_OFF_OPTIONS}
              onChange={(sound) =>
                patchAction(index, {
                  delta: { ...action.delta, sound: sound as DeltaDraft['sound'] },
                })
              }
            />
            <DeltaSelect
              label="Подсветка"
              value={action.delta.light}
              options={ON_OFF_OPTIONS}
              onChange={(light) =>
                patchAction(index, {
                  delta: { ...action.delta, light: light as DeltaDraft['light'] },
                })
              }
            />
          </div>
          )}
        </div>
      ))}

      <Button
        variant="ghost"
        onClick={() =>
          setActions((current) => [
            ...current,
            { target: '', delta: EMPTY_DELTA, toggle: '' },
          ])
        }
      >
        + Действие
      </Button>

      {error !== null && <p className="text-sm text-rose-400">{error}</p>}
      <div className="flex gap-2">
        <Button onClick={save} disabled={saveScenario.isPending}>
          {saveScenario.isPending ? 'Сохраняем…' : 'Сохранить'}
        </Button>
        <Button variant="ghost" onClick={onClose}>
          Отмена
        </Button>
      </div>
    </Card>
  )
}

const ON_OFF_OPTIONS: [string, string][] = [
  ['on', 'вкл'],
  ['off', 'выкл'],
]

const TEMP_OPTIONS: [string, string][] = Array.from({ length: 21 }, (_, i) => {
  const value = String(10 + i)
  return [value, `${value} °C`]
})

function DeltaSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string
  options: [string, string][]
  onChange: (value: string) => void
}) {
  return (
    <label className="flex flex-col gap-1 text-xs text-slate-400">
      {label}
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-200"
      >
        <option value="">— не менять</option>
        {options.map(([optionValue, optionLabel]) => (
          <option key={optionValue} value={optionValue}>
            {optionLabel}
          </option>
        ))}
      </select>
    </label>
  )
}

// --- расписания ----------------------------------------------------------------

function SchedulesTab() {
  const schedules = useSchedules()
  const scenarios = useScenarios()
  const saveSchedule = useSaveSchedule()
  const deleteSchedule = useDeleteSchedule()
  const [editing, setEditing] = useState<Schedule | 'new' | null>(null)

  if (schedules.isPending || scenarios.isPending)
    return <Spinner label="Загружаем расписания…" />
  if (schedules.isError || scenarios.isError)
    return <p className="text-rose-400">Не удалось загрузить расписания.</p>

  if (editing !== null) {
    return (
      <ScheduleEditor
        schedule={editing === 'new' ? null : editing}
        scenarios={scenarios.data}
        onClose={() => setEditing(null)}
      />
    )
  }

  const scenarioNames = new Map(scenarios.data.map((s) => [s.id, s.name]))

  return (
    <div className="flex flex-col gap-3">
      {schedules.data.length === 0 && (
        <p className="text-sm text-slate-400">
          Расписание запускает сценарий по времени: «ночной режим в 23:00
          ежедневно». Ручное управление ставит паузу автоматике на час.
        </p>
      )}
      {schedules.data.map((schedule) => (
        <Card
          key={schedule.id}
          className="flex flex-wrap items-center justify-between gap-3"
        >
          <div className="w-full min-w-0 sm:w-auto sm:flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <p className="font-medium">{schedule.name}</p>
              {!schedule.enabled && <Badge tone="muted">выключено</Badge>}
            </div>
            <p className="truncate text-xs text-slate-400">
              {describeCron(schedule.cron)}
              {schedule.scenario_id !== null &&
                ` → ${scenarioNames.get(schedule.scenario_id) ?? 'сценарий'}`}
            </p>
          </div>
          <div className="ml-auto flex shrink-0 items-center gap-2">
            <Toggle
              label=""
              checked={schedule.enabled}
              disabled={saveSchedule.isPending}
              onChange={(enabled) =>
                saveSchedule.mutate({
                  id: schedule.id,
                  body: {
                    name: schedule.name,
                    cron: schedule.cron,
                    scenario_id: schedule.scenario_id,
                    actions: schedule.actions,
                    enabled,
                  },
                })
              }
            />
            <Button variant="ghost" onClick={() => setEditing(schedule)}>
              Изменить
            </Button>
            <Button
              variant="danger"
              disabled={deleteSchedule.isPending}
              onClick={() => deleteSchedule.mutate(schedule.id)}
            >
              Удалить
            </Button>
          </div>
        </Card>
      ))}
      <Button variant="ghost" onClick={() => setEditing('new')}>
        + Новое расписание
      </Button>
    </div>
  )
}

function ScheduleEditor({
  schedule,
  scenarios,
  onClose,
}: {
  schedule: Schedule | null
  scenarios: Scenario[]
  onClose: () => void
}) {
  const saveSchedule = useSaveSchedule()
  const initialPreset =
    schedule !== null ? presetFromCron(schedule.cron) : { time: '23:00', days: [] }
  const [name, setName] = useState(schedule?.name ?? '')
  const [scenarioId, setScenarioId] = useState<string>(
    schedule?.scenario_id !== null && schedule !== undefined
      ? String(schedule?.scenario_id ?? '')
      : '',
  )
  const [time, setTime] = useState(initialPreset?.time ?? '23:00')
  const [days, setDays] = useState<number[]>(initialPreset?.days ?? [])
  // произвольный cron (не из конструктора) правится как текст
  const [rawCron, setRawCron] = useState(
    schedule !== null && initialPreset === null ? schedule.cron : null,
  )
  const [error, setError] = useState<string | null>(null)

  const toggleDay = (day: number) => {
    setDays((current) =>
      current.includes(day)
        ? current.filter((d) => d !== day)
        : [...current, day].sort((a, b) => a - b),
    )
  }

  const save = async () => {
    setError(null)
    if (name.trim() === '') {
      setError('дайте расписанию имя')
      return
    }
    if (scenarioId === '') {
      setError('выберите сценарий')
      return
    }
    const cron = rawCron !== null ? rawCron.trim() : cronFromPreset({ time, days })
    const body: ScheduleBody = {
      name: name.trim(),
      cron,
      scenario_id: Number(scenarioId),
      enabled: schedule?.enabled ?? true,
    }
    try {
      await saveSchedule.mutateAsync({ id: schedule?.id, body })
      onClose()
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : 'не удалось сохранить')
    }
  }

  return (
    <Card className="flex flex-col gap-4">
      <p className="font-medium">
        {schedule === null ? 'Новое расписание' : `Расписание «${schedule.name}»`}
      </p>
      <input
        value={name}
        onChange={(event) => setName(event.target.value)}
        placeholder="Название (например, Ночь)"
        className="rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm outline-none focus:border-sky-500"
      />
      <label className="flex flex-col gap-1 text-xs text-slate-400">
        Сценарий
        <select
          value={scenarioId}
          onChange={(event) => setScenarioId(event.target.value)}
          className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-2 text-sm text-slate-200"
        >
          <option value="">— выберите…</option>
          {scenarios.map((scenario) => (
            <option key={scenario.id} value={scenario.id}>
              {scenario.name}
            </option>
          ))}
        </select>
      </label>

      {rawCron !== null ? (
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          Cron-выражение (5 полей)
          <input
            value={rawCron}
            onChange={(event) => setRawCron(event.target.value)}
            className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-2 font-mono text-sm text-slate-200"
          />
        </label>
      ) : (
        <>
          <label className="flex flex-col gap-1 text-xs text-slate-400">
            Время
            <input
              type="time"
              value={time}
              onChange={(event) => setTime(event.target.value)}
              className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-2 text-sm text-slate-200"
            />
          </label>
          <div className="flex flex-col gap-1 text-xs text-slate-400">
            Дни (пусто — ежедневно)
            <div className="flex flex-wrap gap-1.5">
              {DAY_LABELS.map((label, index) => {
                const day = index + 1
                const active = days.includes(day)
                return (
                  <button
                    key={day}
                    type="button"
                    onClick={() => toggleDay(day)}
                    className={`rounded-lg px-2.5 py-1.5 text-sm transition-colors ${
                      active
                        ? 'bg-sky-600 text-white'
                        : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
                    }`}
                  >
                    {label}
                  </button>
                )
              })}
            </div>
          </div>
        </>
      )}

      {error !== null && <p className="text-sm text-rose-400">{error}</p>}
      <div className="flex gap-2">
        <Button onClick={save} disabled={saveSchedule.isPending}>
          {saveSchedule.isPending ? 'Сохраняем…' : 'Сохранить'}
        </Button>
        <Button variant="ghost" onClick={onClose}>
          Отмена
        </Button>
      </div>
    </Card>
  )
}

function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return one
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few
  return many
}

// --- триггеры ------------------------------------------------------------------

function TriggersTab() {
  const triggers = useTriggers()
  const sensors = useSensors()
  const scenarios = useScenarios()
  const deleteTrigger = useDeleteTrigger()
  const saveTrigger = useSaveTrigger()
  const [editing, setEditing] = useState<Trigger | 'new' | null>(null)

  if (triggers.isPending || sensors.isPending || scenarios.isPending)
    return <Spinner label="Загружаем триггеры…" />
  if (triggers.isError || sensors.isError || scenarios.isError)
    return <p className="text-rose-400">Не удалось загрузить триггеры.</p>

  if (sensors.data.length === 0) {
    return (
      <p className="text-sm text-slate-400">
        Триггеры реагируют на датчики (CO₂, температура, влажность), а датчиков
        пока нет. MagicAir появится сам после ввода учётки Tion в настройках
        сервера; MQTT-датчик добавляется на вкладке «Устройства».
      </p>
    )
  }
  if (editing !== null) {
    return (
      <TriggerEditor
        trigger={editing === 'new' ? null : editing}
        sensors={sensors.data}
        scenarios={scenarios.data}
        onClose={() => setEditing(null)}
      />
    )
  }

  const sensorNames = new Map(sensors.data.map((s) => [s.id, s.name]))
  const scenarioNames = new Map(scenarios.data.map((s) => [s.id, s.name]))

  return (
    <div className="flex flex-col gap-3">
      {triggers.data.length === 0 && (
        <p className="text-sm text-slate-400">
          Пример: «CO₂ &gt; 1000 → Турбо, при возврате ниже 800 → Обычный».
          Гистерезис защищает от дребезга на границе порога.
        </p>
      )}
      {triggers.data.map((trigger) => (
        <Card
          key={trigger.id}
          className="flex flex-wrap items-center justify-between gap-3"
        >
          <div className="w-full min-w-0 sm:w-auto sm:flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <p className="font-medium">{trigger.name}</p>
              {trigger.kind === 'maintain' && <Badge tone="ok">поддержание</Badge>}
              {trigger.is_active && <Badge tone="warn">сработал</Badge>}
              {!trigger.enabled && <Badge tone="muted">выключен</Badge>}
            </div>
            <p className="truncate text-xs text-slate-400">
              {trigger.kind === 'maintain' ? (
                <>
                  {sensorNames.get(trigger.sensor_id) ?? 'датчик'} · CO₂ ≈{' '}
                  {trigger.threshold} ppm · скорость{' '}
                  {trigger.speed_min === 0 ? 'выкл' : trigger.speed_min}–
                  {trigger.speed_max}
                </>
              ) : (
                <>
                  {sensorNames.get(trigger.sensor_id) ?? 'датчик'} ·{' '}
                  {METRIC_LABELS[trigger.metric]} {trigger.op} {trigger.threshold}
                  {trigger.enter_scenario_id !== null &&
                    ` → ${scenarioNames.get(trigger.enter_scenario_id) ?? 'сценарий'}`}
                </>
              )}
              {trigger.window_start !== null &&
                ` · ${trigger.window_start}–${trigger.window_end}`}
            </p>
          </div>
          <div className="ml-auto flex shrink-0 items-center gap-2">
            <Toggle
              label=""
              checked={trigger.enabled}
              disabled={saveTrigger.isPending}
              onChange={(enabled) =>
                saveTrigger.mutate({
                  id: trigger.id,
                  body: { ...triggerToBody(trigger), enabled },
                })
              }
            />
            <Button variant="ghost" onClick={() => setEditing(trigger)}>
              Изменить
            </Button>
            <Button
              variant="danger"
              disabled={deleteTrigger.isPending}
              onClick={() => deleteTrigger.mutate(trigger.id)}
            >
              Удалить
            </Button>
          </div>
        </Card>
      ))}
      <Button variant="ghost" onClick={() => setEditing('new')}>
        + Новый триггер
      </Button>
    </div>
  )
}

/** Полное тело для PUT: ни одно поле не теряется (в т.ч. inline-действия). */
function triggerToBody(trigger: Trigger): TriggerBody {
  return {
    name: trigger.name,
    sensor_id: trigger.sensor_id,
    metric: trigger.metric,
    kind: trigger.kind,
    op: trigger.op,
    threshold: trigger.threshold,
    hysteresis: trigger.hysteresis,
    cooldown_s: trigger.cooldown_s,
    window_start: trigger.window_start,
    window_end: trigger.window_end,
    speed_min: trigger.speed_min,
    speed_max: trigger.speed_max,
    targets: trigger.targets,
    enter_scenario_id: trigger.enter_scenario_id,
    enter_actions: trigger.enter_actions,
    exit_scenario_id: trigger.exit_scenario_id,
    exit_actions: trigger.exit_actions,
    enabled: trigger.enabled,
  }
}

function TriggerEditor({
  trigger,
  sensors,
  scenarios,
  onClose,
}: {
  trigger: Trigger | null
  sensors: Sensor[]
  scenarios: Scenario[]
  onClose: () => void
}) {
  const saveTrigger = useSaveTrigger()
  const devices = useDevices()
  const groups = useGroups()
  const maintainInitial = trigger !== null && trigger.kind === 'maintain'
  const [kind, setKind] = useState<TriggerKind>(trigger?.kind ?? 'threshold')
  const [name, setName] = useState(trigger?.name ?? '')
  const [sensorId, setSensorId] = useState(
    String(trigger?.sensor_id ?? sensors[0]?.id ?? ''),
  )
  const [metric, setMetric] = useState<SensorMetric>(trigger?.metric ?? 'co2')
  const [op, setOp] = useState<'>' | '<'>(trigger?.op ?? '>')
  const [threshold, setThreshold] = useState(String(trigger?.threshold ?? 1000))
  const [hysteresis, setHysteresis] = useState(
    String(maintainInitial ? 200 : (trigger?.hysteresis ?? 200)),
  )
  const [cooldownS, setCooldownS] = useState(
    String(maintainInitial ? 0 : (trigger?.cooldown_s ?? 0)),
  )
  const [useWindow, setUseWindow] = useState(trigger?.window_start != null)
  const [windowStart, setWindowStart] = useState(trigger?.window_start ?? '08:00')
  const [windowEnd, setWindowEnd] = useState(trigger?.window_end ?? '22:00')
  const [enterScenario, setEnterScenario] = useState(
    trigger?.enter_scenario_id != null ? String(trigger.enter_scenario_id) : '',
  )
  const [exitScenario, setExitScenario] = useState(
    trigger?.exit_scenario_id != null ? String(trigger.exit_scenario_id) : '',
  )
  // поля поддержания CO₂ (kind = maintain)
  const [deadband, setDeadband] = useState(
    String(maintainInitial ? (trigger?.hysteresis ?? 50) : 50),
  )
  const [maintainCooldownS, setMaintainCooldownS] = useState(
    String(maintainInitial ? (trigger?.cooldown_s ?? 120) : 120),
  )
  const [speedMin, setSpeedMin] = useState(String(trigger?.speed_min ?? 1))
  const [speedMax, setSpeedMax] = useState(String(trigger?.speed_max ?? 6))
  const [targets, setTargets] = useState<string[]>(
    (trigger?.targets ?? []).map((t) => `${t.target_type}:${t.target_id}`),
  )
  const [error, setError] = useState<string | null>(null)

  const inputClass =
    'rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-200'

  const toggleTarget = (value: string) => {
    setTargets((current) =>
      current.includes(value)
        ? current.filter((v) => v !== value)
        : [...current, value],
    )
  }

  const save = async () => {
    setError(null)
    if (name.trim() === '') {
      setError('дайте триггеру имя')
      return
    }
    const body =
      kind === 'maintain' ? buildMaintainBody() : buildThresholdBody()
    if (typeof body === 'string') {
      setError(body)
      return
    }
    try {
      await saveTrigger.mutateAsync({ id: trigger?.id, body })
      onClose()
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : 'не удалось сохранить')
    }
  }

  const buildThresholdBody = (): TriggerBody | string => {
    const parsedThreshold = Number(threshold)
    const parsedHysteresis = Number(hysteresis)
    const parsedCooldown = Number(cooldownS)
    if (!Number.isFinite(parsedThreshold)) return 'порог — число'
    if (!Number.isFinite(parsedHysteresis) || parsedHysteresis < 0) {
      return 'гистерезис — неотрицательное число'
    }
    // inline-действия (созданные через API) сохраняются, если сценарий не выбран
    const enterActions = enterScenario === '' ? (trigger?.enter_actions ?? null) : null
    const exitActions = exitScenario === '' ? (trigger?.exit_actions ?? null) : null
    if (
      enterScenario === '' &&
      exitScenario === '' &&
      enterActions === null &&
      exitActions === null
    ) {
      return 'выберите сценарий на вход и/или на выход'
    }
    return {
      name: name.trim(),
      sensor_id: Number(sensorId),
      metric,
      kind: 'threshold',
      op,
      threshold: parsedThreshold,
      hysteresis: parsedHysteresis,
      cooldown_s: Math.max(0, Math.round(parsedCooldown)),
      window_start: useWindow ? windowStart : null,
      window_end: useWindow ? windowEnd : null,
      enter_scenario_id: enterScenario === '' ? null : Number(enterScenario),
      enter_actions: enterActions,
      exit_scenario_id: exitScenario === '' ? null : Number(exitScenario),
      exit_actions: exitActions,
      enabled: trigger?.enabled ?? true,
    }
  }

  const buildMaintainBody = (): TriggerBody | string => {
    const parsedTarget = Number(threshold)
    const parsedDeadband = Number(deadband)
    const parsedCooldown = Number(maintainCooldownS)
    const min = Number(speedMin)
    const max = Number(speedMax)
    if (!Number.isFinite(parsedTarget) || parsedTarget <= 0) {
      return 'целевой CO₂ — положительное число'
    }
    if (!Number.isFinite(parsedDeadband) || parsedDeadband <= 0) {
      return 'зона покоя — положительное число'
    }
    if (min > max) return 'минимальная скорость больше максимальной'
    if (targets.length === 0) return 'выберите хотя бы одно устройство'
    return {
      name: name.trim(),
      sensor_id: Number(sensorId),
      metric: 'co2',
      kind: 'maintain',
      threshold: parsedTarget,
      hysteresis: parsedDeadband,
      cooldown_s: Math.max(0, Math.round(parsedCooldown)),
      window_start: useWindow ? windowStart : null,
      window_end: useWindow ? windowEnd : null,
      speed_min: min,
      speed_max: max,
      targets: targets.map((value): TriggerTarget => {
        const [targetType, targetId] = value.split(':', 2)
        return {
          target_type: targetType as TriggerTarget['target_type'],
          target_id: targetType === 'group' ? Number(targetId) : targetId,
        }
      }),
      enabled: trigger?.enabled ?? true,
    }
  }

  return (
    <Card className="flex flex-col gap-3">
      <p className="font-medium">
        {trigger === null ? 'Новый триггер' : `Триггер «${trigger.name}»`}
      </p>
      {trigger === null && (
        <div className="flex gap-2">
          <TabButton
            active={kind === 'threshold'}
            label="Порог"
            onClick={() => setKind('threshold')}
          />
          <TabButton
            active={kind === 'maintain'}
            label="Поддержание CO₂"
            onClick={() => setKind('maintain')}
          />
        </div>
      )}
      {kind === 'maintain' && (
        <p className="text-xs text-slate-400">
          Бризер сам подбирает скорость в заданном диапазоне, удерживая CO₂
          около цели. Включение одного регулятора выключает другой на тех же
          устройствах — ночной и дневной режимы удобно переключать сценариями.
        </p>
      )}
      <input
        value={name}
        onChange={(event) => setName(event.target.value)}
        placeholder={
          kind === 'maintain'
            ? 'Название (например, Ночь · спальня)'
            : 'Название (например, Душно в спальне)'
        }
        className="rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm outline-none focus:border-sky-500"
      />
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          Датчик
          <select
            value={sensorId}
            onChange={(event) => setSensorId(event.target.value)}
            className={inputClass}
          >
            {sensors.map((sensor) => (
              <option key={sensor.id} value={sensor.id}>
                {sensor.name}
              </option>
            ))}
          </select>
        </label>
        {kind === 'threshold' ? (
          <>
            <label className="flex flex-col gap-1 text-xs text-slate-400">
              Метрика
              <select
                value={metric}
                onChange={(event) => setMetric(event.target.value as SensorMetric)}
                className={inputClass}
              >
                {Object.entries(METRIC_LABELS).map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-slate-400">
              Условие входа
              <div className="flex gap-1">
                <select
                  value={op}
                  onChange={(event) => setOp(event.target.value as '>' | '<')}
                  className={inputClass}
                  aria-label="оператор"
                >
                  <option value=">">&gt;</option>
                  <option value="<">&lt;</option>
                </select>
                <input
                  value={threshold}
                  onChange={(event) => setThreshold(event.target.value)}
                  inputMode="decimal"
                  className={`${inputClass} w-full`}
                  aria-label="порог"
                />
              </div>
            </label>
            <label className="flex flex-col gap-1 text-xs text-slate-400">
              Гистерезис (выход)
              <input
                value={hysteresis}
                onChange={(event) => setHysteresis(event.target.value)}
                inputMode="decimal"
                className={inputClass}
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-slate-400">
              Кулдаун, с
              <input
                value={cooldownS}
                onChange={(event) => setCooldownS(event.target.value)}
                inputMode="numeric"
                className={inputClass}
              />
            </label>
          </>
        ) : (
          <>
            <label className="flex flex-col gap-1 text-xs text-slate-400">
              Целевой CO₂, ppm
              <input
                value={threshold}
                onChange={(event) => setThreshold(event.target.value)}
                inputMode="numeric"
                className={inputClass}
                aria-label="целевой CO₂"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-slate-400">
              Зона покоя, ppm
              <input
                value={deadband}
                onChange={(event) => setDeadband(event.target.value)}
                inputMode="numeric"
                className={inputClass}
                aria-label="зона покоя"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-slate-400">
              Скорость от
              <select
                value={speedMin}
                onChange={(event) => setSpeedMin(event.target.value)}
                className={inputClass}
                aria-label="минимальная скорость"
              >
                {['0', '1', '2', '3', '4', '5', '6'].map((v) => (
                  <option key={v} value={v}>
                    {v === '0' ? 'выкл' : v}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-slate-400">
              Скорость до
              <select
                value={speedMax}
                onChange={(event) => setSpeedMax(event.target.value)}
                className={inputClass}
                aria-label="максимальная скорость"
              >
                {['1', '2', '3', '4', '5', '6'].map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-slate-400">
              Кулдаун, с
              <input
                value={maintainCooldownS}
                onChange={(event) => setMaintainCooldownS(event.target.value)}
                inputMode="numeric"
                className={inputClass}
                aria-label="кулдаун поддержания"
              />
            </label>
          </>
        )}
      </div>

      {kind === 'maintain' && (
        <div className="flex flex-col gap-1 text-xs text-slate-400">
          Что регулируем
          <div className="flex flex-wrap gap-1.5">
            {groups.data?.map((group) => {
              const value = `group:${group.id}`
              const active = targets.includes(value)
              return (
                <button
                  key={value}
                  type="button"
                  onClick={() => toggleTarget(value)}
                  className={`rounded-lg px-2.5 py-1.5 text-sm transition-colors ${
                    active
                      ? 'bg-sky-600 text-white'
                      : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
                  }`}
                >
                  Группа · {group.name}
                </button>
              )
            })}
            {devices.data?.map((device) => {
              const value = `device:${device.uuid}`
              const active = targets.includes(value)
              return (
                <button
                  key={value}
                  type="button"
                  onClick={() => toggleTarget(value)}
                  className={`rounded-lg px-2.5 py-1.5 text-sm transition-colors ${
                    active
                      ? 'bg-sky-600 text-white'
                      : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
                  }`}
                >
                  {device.name}
                </button>
              )
            })}
          </div>
        </div>
      )}

      <Toggle label="Только в окне времени" checked={useWindow} onChange={setUseWindow} />
      {useWindow && (
        <div className="flex gap-2">
          <input
            type="time"
            value={windowStart}
            onChange={(event) => setWindowStart(event.target.value)}
            className={inputClass}
            aria-label="начало окна"
          />
          <span className="self-center text-slate-500">—</span>
          <input
            type="time"
            value={windowEnd}
            onChange={(event) => setWindowEnd(event.target.value)}
            className={inputClass}
            aria-label="конец окна"
          />
        </div>
      )}

      {kind === 'threshold' && (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-xs text-slate-400">
            Сценарий при срабатывании
            <select
              value={enterScenario}
              onChange={(event) => setEnterScenario(event.target.value)}
              className={inputClass}
            >
              <option value="">— ничего</option>
              {scenarios.map((scenario) => (
                <option key={scenario.id} value={scenario.id}>
                  {scenario.name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-slate-400">
            Сценарий при возврате к норме
            <select
              value={exitScenario}
              onChange={(event) => setExitScenario(event.target.value)}
              className={inputClass}
            >
              <option value="">— ничего</option>
              {scenarios.map((scenario) => (
                <option key={scenario.id} value={scenario.id}>
                  {scenario.name}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}

      {error !== null && <p className="text-sm text-rose-400">{error}</p>}
      <div className="flex gap-2">
        <Button onClick={save} disabled={saveTrigger.isPending}>
          {saveTrigger.isPending ? 'Сохраняем…' : 'Сохранить'}
        </Button>
        <Button variant="ghost" onClick={onClose}>
          Отмена
        </Button>
      </div>
    </Card>
  )
}
