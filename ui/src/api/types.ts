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

export type User = { id: number; username: string }

export type AuthStatus = { setup_required: boolean }

export type WsEvent = {
  topic: string
  data: Record<string, unknown>
}
