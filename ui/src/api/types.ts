import type { SensorMetric } from '../lib/metrics'
// DTO REST-API (зеркало pydantic-схем сервера)

export type Mode = 'outside' | 'recirculation'
export type Connection = 'disconnected' | 'connecting' | 'online'

export type DeviceState = {
  power: boolean
  sound: boolean
  light: boolean
  heater: boolean
  mode: Mode
  heater_temp: number
  fan_speed: number
  in_temp: number
  out_temp: number
  filter_remain_days: number
}

export type Device = {
  uuid: string
  mac: string
  name: string
  model: string
  room_id: number | null
  paired: boolean
  connection: Connection
  state: DeviceState | null
  state_at: number | null
  hold_until: number | null
  filter_reset_supported?: boolean
}

export type Room = { id: number; name: string }

export type Group = { id: number; name: string; device_uuids: string[] }

export type CommandBody = Partial<{
  power: boolean
  sound: boolean
  light: boolean
  heater: boolean
  mode: Mode
  heater_temp: number
  fan_speed: number
}>

export type CommandResult = {
  command_id: number
  status: string
  result_state: DeviceState | null
  error: string | null
}

export type FoundBreezer = {
  mac: string
  name: string
  rssi: number | null
  model_hint: string | null
  pairing_mode: boolean | null
  registered: boolean
}

/** Дельта действия над триггером: включить/выключить. */
export type TriggerToggle = { enabled: boolean }

export type ScenarioAction = {
  target_type: 'device' | 'group' | 'trigger'
  target_id: string | number
  delta: CommandBody | TriggerToggle
}

export type Scenario = { id: number; name: string; actions: ScenarioAction[] }

export type Schedule = {
  id: number
  name: string
  cron: string
  scenario_id: number | null
  actions: ScenarioAction[] | null
  enabled: boolean
}

export type GroupCommandResult = {
  device_uuid: string
  result: CommandResult | null
  rejected: string | null
}

export type { SensorMetric } from '../lib/metrics'

export type Sensor = {
  id: number
  kind: string
  name: string
  source_key: string
  room_id: number | null
  last_values: Partial<Record<SensorMetric, number>> | null
  last_seen_at: number | null
  last_metric_at?: Partial<Record<SensorMetric, number>> | null
  capabilities: SensorMetric[]
  metric_stale?: Partial<Record<SensorMetric, boolean>>
  stale: boolean
}

export type SensorProvider = {
  kind: string
  title: string
  transport: 'cloud' | 'mqtt' | 'ble'
  description: string
  metrics: SensorMetric[]
  manual: boolean
  discoverable: boolean
  address_label: string | null
  address_placeholder: string | null
  available: boolean
  unavailable_reason: string | null
}

export type DiscoveredSensor = {
  kind: string
  source_key: string
  address: string
  model: string | null
  signal_dbm: number | null
  metrics: Partial<Record<SensorMetric, number>>
  registered: boolean
}

export type TriggerKind = 'threshold' | 'maintain'

export type TriggerTarget = {
  target_type: 'device' | 'group'
  target_id: string | number
}

export type Trigger = {
  id: number
  name: string
  sensor_id: number
  metric: SensorMetric
  kind: TriggerKind
  op: '>' | '<'
  threshold: number
  hysteresis: number
  cooldown_s: number
  window_start: string | null
  window_end: string | null
  speed_min: number | null
  speed_max: number | null
  targets: TriggerTarget[] | null
  enter_scenario_id: number | null
  enter_actions: ScenarioAction[] | null
  exit_scenario_id: number | null
  exit_actions: ScenarioAction[] | null
  enabled: boolean
  is_active: boolean
}

export type RawPoint = { ts: number; value: number }

export type HourlyPoint = { ts: number; min: number; max: number; avg: number }

export type TelemetrySeries = {
  source_type: string
  source_id: string
  metric: string
  agg: 'raw' | 'hourly'
  raw: RawPoint[] | null
  hourly: HourlyPoint[] | null
}

export type User = { id: number; username: string }

export type AuthStatus = { setup_required: boolean }

export type WsEvent = {
  topic: string
  data: Record<string, unknown>
}
