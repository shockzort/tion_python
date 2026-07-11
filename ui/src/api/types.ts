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

export type ScenarioAction = {
  target_type: 'device' | 'group'
  target_id: string | number
  delta: CommandBody
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

export type Sensor = {
  id: number
  kind: 'magicair' | 'mqtt'
  name: string
  source_key: string
  room_id: number | null
  last_values: Partial<Record<'co2' | 'temperature' | 'humidity', number>> | null
  last_seen_at: number | null
  stale: boolean
}

export type SensorMetric = 'co2' | 'temperature' | 'humidity'

export type Trigger = {
  id: number
  name: string
  sensor_id: number
  metric: SensorMetric
  op: '>' | '<'
  threshold: number
  hysteresis: number
  cooldown_s: number
  window_start: string | null
  window_end: string | null
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
