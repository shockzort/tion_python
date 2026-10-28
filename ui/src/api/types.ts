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
  target_type: 'device' | 'group' | 'trigger' | 'appliance'
  target_id: string | number
  delta: CommandBody | TriggerToggle | ApplianceCommand
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
  transport: 'cloud' | 'mqtt' | 'ble' | 'wifi'
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
  target_type: 'device' | 'group' | 'appliance'
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

// --- приборы Xiaomi (miIO) ---------------------------------------------------

export type ApplianceFunction = 'humidify' | 'purify'
export type HumidifierMode = 'constant' | 'sleep' | 'favorite' | 'fan'
export type PurifierMode = 'auto' | 'sleep' | 'favorite' | 'fan'

export type ApplianceState = {
  power: boolean
  function: ApplianceFunction
  humidifier_mode: HumidifierMode
  purifier_mode: PurifierMode
  target_humidity: number
  humidifier_fan_level: number
  purifier_fan_level: number
  water_level: number
  water_state: 'no_tank' | 'low' | 'normal' | 'full' | 'unknown'
  fault: number
  humidity: number
  temperature: number
  pm25: number
  pm1: number
  air_quality: number
  purifier_filter_life: number
  humidifier_filter_life: number
  screen: boolean
  sound: boolean
  child_lock: boolean
  screen_brightness: ScreenBrightness
  auto_dry: boolean
  /** минут до конца сушки фильтра */
  dry_remaining: number
  overwet_protect: boolean
  status: 'idle' | 'drying' | 'cleaning' | 'clean_interrupted' | 'clean_finished' | 'unknown'
  /** минут до конца самоочистки */
  clean_remaining: number
  purifier_favorite_level: number
  off_timer: boolean
  off_timer_hours: number
  /** минут до выключения по таймеру */
  off_timer_remaining: number
  night_mode: boolean
  /** минуты от полуночи */
  night_start: number
  night_end: number
  display_metric: 'pm25' | 'pm1' | 'pm10'
}

export type ScreenBrightness = 'auto' | 'bright' | 'medium' | 'dim'

export type Appliance = {
  id: string
  name: string
  model: string
  online: boolean
  state: ApplianceState | null
  state_at: number | null
  error: string | null
}

export type ApplianceCommand = Partial<
  Pick<
    ApplianceState,
    | 'power'
    | 'function'
    | 'humidifier_mode'
    | 'purifier_mode'
    | 'target_humidity'
    | 'humidifier_fan_level'
    | 'purifier_fan_level'
    | 'screen'
    | 'sound'
    | 'child_lock'
    | 'screen_brightness'
    | 'auto_dry'
    | 'overwet_protect'
    | 'purifier_favorite_level'
    | 'off_timer'
    | 'off_timer_hours'
    | 'night_mode'
    | 'night_start'
    | 'night_end'
    | 'display_metric'
  >
>

export type ApplianceAction =
  | 'self_clean_start'
  | 'self_clean_stop'
  | 'dry_start'
  | 'dry_stop'
  | 'reset_purifier_filter'
  | 'reset_humidifier_filter'

// --- настройки Qingping на самом датчике ---------------------------------------

export type QingpingScreensaver = 'rotate' | 'current' | 'time_rotate' | 'time_current'

/** Настройки CGDN1 в единицах сервиса; поле, которого прошивка не прислала, — нет. */
export type QingpingSettings = Partial<{
  screensaver: QingpingScreensaver
  display_off_time: number
  auto_slide_time: number
  power_off_time: number
  night_start: number
  night_end: number
  temperature_unit: 'C' | 'F'
  is_12_hour: boolean
  timezone: number
  co2_asc: boolean
  temperature_offset: number
  humidity_offset: number
  co2_offset: number
  pm25_offset: number
  pm10_offset: number
  co2_led_th: number[]
  pm25_led_th: number[]
}>
