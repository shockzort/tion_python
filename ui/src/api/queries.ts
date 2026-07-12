// TanStack Query: ключи, запросы и мутации поверх REST

import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query'

import { api } from './client'
import type {
  AuthStatus,
  CommandBody,
  CommandResult,
  Device,
  FoundBreezer,
  Group,
  GroupCommandResult,
  Room,
  Scenario,
  ScenarioAction,
  Schedule,
  Sensor,
  TelemetrySeries,
  Trigger,
  TriggerKind,
  TriggerTarget,
  User,
} from './types'

export const keys = {
  me: ['me'] as const,
  authStatus: ['auth-status'] as const,
  devices: ['devices'] as const,
  rooms: ['rooms'] as const,
  groups: ['groups'] as const,
  scenarios: ['scenarios'] as const,
  schedules: ['schedules'] as const,
  sensors: ['sensors'] as const,
  triggers: ['triggers'] as const,
  telemetry: (params: Record<string, string>) => ['telemetry', params] as const,
  pref: (key: string) => ['pref', key] as const,
}

// --- auth ------------------------------------------------------------------

export function useMe() {
  return useQuery({
    queryKey: keys.me,
    queryFn: () => api<User>('/api/auth/me'),
    retry: false,
    staleTime: 5 * 60_000,
  })
}

export function useAuthStatus() {
  return useQuery({
    queryKey: keys.authStatus,
    queryFn: () => api<AuthStatus>('/api/auth/status'),
  })
}

export function useLogin() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { username: string; password: string }) =>
      api<User>('/api/auth/login', { method: 'POST', json: body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.me }),
  })
}

export function useSetup() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      setup_token: string
      username: string
      password: string
    }) => api<User>('/api/auth/setup', { method: 'POST', json: body }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.me })
      void queryClient.invalidateQueries({ queryKey: keys.authStatus })
    },
  })
}

export function useLogout() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api<undefined>('/api/auth/logout', { method: 'POST' }),
    onSettled: () => queryClient.resetQueries({ queryKey: keys.me }),
  })
}

// --- устройства ------------------------------------------------------------

export function useDevices() {
  return useQuery({
    queryKey: keys.devices,
    queryFn: () => api<Device[]>('/api/devices'),
    staleTime: 30_000, // WS-мост держит кэш свежим, это только страховка
  })
}

export function useRooms() {
  return useQuery({
    queryKey: keys.rooms,
    queryFn: () => api<Room[]>('/api/rooms'),
  })
}

export function useGroups() {
  return useQuery({
    queryKey: keys.groups,
    queryFn: () => api<Group[]>('/api/groups'),
  })
}

/** Команда с optimistic-обновлением; откат по ошибке или не-done итогу. */
export function useSendCommand() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ uuid, body }: { uuid: string; body: CommandBody }) =>
      api<CommandResult>(`/api/devices/${uuid}/command`, {
        method: 'POST',
        json: body,
        headers: { 'Idempotency-Key': `ui:${crypto.randomUUID()}` },
      }),
    onMutate: async ({ uuid, body }) => {
      await queryClient.cancelQueries({ queryKey: keys.devices })
      const previous = queryClient.getQueryData<Device[]>(keys.devices)
      queryClient.setQueryData<Device[]>(keys.devices, (devices) =>
        devices?.map((device) =>
          device.uuid === uuid && device.state !== null
            ? { ...device, state: { ...device.state, ...body } }
            : device,
        ),
      )
      return { previous }
    },
    onError: (_error, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(keys.devices, context.previous)
      }
    },
    onSuccess: (result, { uuid }) => {
      if (result.status === 'done' && result.result_state !== null) {
        // истина устройства (ADR-0004) вместо оптимистичной догадки
        queryClient.setQueryData<Device[]>(keys.devices, (devices) =>
          devices?.map((device) =>
            device.uuid === uuid
              ? { ...device, state: result.result_state }
              : device,
          ),
        )
      } else {
        void queryClient.invalidateQueries({ queryKey: keys.devices })
      }
    },
  })
}

export function useReleaseHold() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (uuid: string) =>
      api<undefined>(`/api/devices/${uuid}/hold`, { method: 'DELETE' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.devices }),
  })
}

export function useUpdateDevice() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      uuid,
      body,
    }: {
      uuid: string
      body: { name?: string; room_id?: number }
    }) => api<Device>(`/api/devices/${uuid}`, { method: 'PATCH', json: body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.devices }),
  })
}

export function useDeleteDevice() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (uuid: string) =>
      api<undefined>(`/api/devices/${uuid}`, { method: 'DELETE' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.devices }),
  })
}

// --- комнаты и группы --------------------------------------------------------

export function useAddRoom() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (name: string) =>
      api<Room>('/api/rooms', { method: 'POST', json: { name } }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.rooms }),
  })
}

export function useDeleteRoom() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      api<undefined>(`/api/rooms/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.rooms })
      void queryClient.invalidateQueries({ queryKey: keys.devices })
    },
  })
}

export function useAddGroup() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (name: string) =>
      api<Group>('/api/groups', { method: 'POST', json: { name } }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.groups }),
  })
}

export function useSetGroupMembers() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, device_uuids }: { id: number; device_uuids: string[] }) =>
      api<Group>(`/api/groups/${id}/members`, {
        method: 'PUT',
        json: { device_uuids },
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.groups }),
  })
}

export function useDeleteGroup() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      api<undefined>(`/api/groups/${id}`, { method: 'DELETE' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.groups }),
  })
}

// --- автоматизация -----------------------------------------------------------

export type ScenarioBody = { name: string; actions: ScenarioAction[] }

export type ScheduleBody = {
  name: string
  cron: string
  scenario_id: number | null
  actions?: ScenarioAction[] | null
  enabled: boolean
}

export function useScenarios() {
  return useQuery({
    queryKey: keys.scenarios,
    queryFn: () => api<Scenario[]>('/api/scenarios'),
  })
}

export function useSchedules() {
  return useQuery({
    queryKey: keys.schedules,
    queryFn: () => api<Schedule[]>('/api/schedules'),
  })
}

export function useSaveScenario() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id?: number; body: ScenarioBody }) =>
      id === undefined
        ? api<Scenario>('/api/scenarios', { method: 'POST', json: body })
        : api<Scenario>(`/api/scenarios/${id}`, { method: 'PUT', json: body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.scenarios }),
  })
}

export function useDeleteScenario() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      api<undefined>(`/api/scenarios/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.scenarios })
      void queryClient.invalidateQueries({ queryKey: keys.schedules })
    },
  })
}

export function useRunScenario() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      api<GroupCommandResult[]>(`/api/scenarios/${id}/run`, { method: 'POST' }),
    // состояния и hold-бейджи изменились у затронутых устройств
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.devices }),
  })
}

export function useSaveSchedule() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id?: number; body: ScheduleBody }) =>
      id === undefined
        ? api<Schedule>('/api/schedules', { method: 'POST', json: body })
        : api<Schedule>(`/api/schedules/${id}`, { method: 'PUT', json: body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.schedules }),
  })
}

export function useDeleteSchedule() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      api<undefined>(`/api/schedules/${id}`, { method: 'DELETE' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.schedules }),
  })
}

// --- датчики и триггеры ---------------------------------------------------------

export type TriggerBody = {
  name: string
  sensor_id: number
  metric: 'co2' | 'temperature' | 'humidity'
  kind?: TriggerKind
  op?: '>' | '<'
  threshold: number
  hysteresis?: number
  cooldown_s?: number
  window_start?: string | null
  window_end?: string | null
  speed_min?: number | null
  speed_max?: number | null
  targets?: TriggerTarget[] | null
  enter_scenario_id?: number | null
  enter_actions?: ScenarioAction[] | null
  exit_scenario_id?: number | null
  exit_actions?: ScenarioAction[] | null
  enabled: boolean
}

export function useSensors() {
  return useQuery({
    queryKey: keys.sensors,
    queryFn: () => api<Sensor[]>('/api/sensors'),
    refetchInterval: 60_000, // датчики опрашиваются раз в минуту
  })
}

export function useAddSensor() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { name: string; source_key: string }) =>
      api<Sensor>('/api/sensors', { method: 'POST', json: body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.sensors }),
  })
}

export function useUpdateSensor() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: { name?: string } }) =>
      api<Sensor>(`/api/sensors/${id}`, { method: 'PATCH', json: body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.sensors }),
  })
}

export function useDeleteSensor() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      api<undefined>(`/api/sensors/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.sensors })
      void queryClient.invalidateQueries({ queryKey: keys.triggers })
    },
  })
}

export function useTriggers() {
  return useQuery({
    queryKey: keys.triggers,
    queryFn: () => api<Trigger[]>('/api/triggers'),
  })
}

export function useSaveTrigger() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id?: number; body: TriggerBody }) =>
      id === undefined
        ? api<Trigger>('/api/triggers', { method: 'POST', json: body })
        : api<Trigger>(`/api/triggers/${id}`, { method: 'PUT', json: body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.triggers }),
  })
}

export function useDeleteTrigger() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      api<undefined>(`/api/triggers/${id}`, { method: 'DELETE' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.triggers }),
  })
}

// --- телеметрия ----------------------------------------------------------------

export function useTelemetry(params: {
  source_id: string
  metric: string
  agg: 'raw' | 'hourly'
  from_ts: number
  source_type?: 'device' | 'sensor'
}) {
  const query = {
    source_type: params.source_type ?? 'device',
    source_id: params.source_id,
    metric: params.metric,
    agg: params.agg,
    from_ts: String(params.from_ts),
  }
  return useQuery({
    queryKey: keys.telemetry(query),
    queryFn: () =>
      api<TelemetrySeries>(`/api/telemetry?${new URLSearchParams(query)}`),
    enabled: params.source_id !== '',
    refetchInterval: 60_000,
  })
}

// --- пользовательские предпочтения ----------------------------------------------

type PrefEnvelope<T> = { key: string; value: T | null }

/** Серверное per-user предпочтение (общее для всех устройств пользователя). */
export function usePref<T>(key: string) {
  return useQuery({
    queryKey: keys.pref(key),
    queryFn: () => api<PrefEnvelope<T>>(`/api/prefs/${key}`),
    select: (data) => data.value,
  })
}

/** Сохранение предпочтения с optimistic-обновлением и откатом по ошибке. */
export function useSavePref<T>(key: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (value: T) =>
      api<PrefEnvelope<T>>(`/api/prefs/${key}`, { method: 'PUT', json: { value } }),
    onMutate: async (value) => {
      await queryClient.cancelQueries({ queryKey: keys.pref(key) })
      const previous = queryClient.getQueryData<PrefEnvelope<T>>(keys.pref(key))
      queryClient.setQueryData<PrefEnvelope<T>>(keys.pref(key), { key, value })
      return { previous }
    },
    onError: (_error, _value, context) => {
      if (context?.previous) {
        queryClient.setQueryData(keys.pref(key), context.previous)
      }
    },
  })
}

// --- настройки -----------------------------------------------------------------

export function useChangePassword() {
  return useMutation({
    mutationFn: (body: { current_password: string; new_password: string }) =>
      api<User>('/api/auth/password', { method: 'POST', json: body }),
  })
}

// --- интенты ---------------------------------------------------------------------

export type IntentReply = {
  reply: string
  executed: boolean
  intent: string | null
}

export function useExecuteIntent() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (text: string) =>
      api<IntentReply>('/api/intents/execute', {
        method: 'POST',
        json: { text },
      }),
    onSuccess: (result) => {
      if (result.executed) {
        void queryClient.invalidateQueries({ queryKey: keys.devices })
      }
    },
  })
}

// --- мастер сопряжения -------------------------------------------------------

export function useScanAir() {
  return useMutation({
    mutationFn: (duration: number) =>
      api<FoundBreezer[]>('/api/pairing/scan', {
        method: 'POST',
        json: { duration },
      }),
  })
}

export function usePairDevice() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { mac: string; name: string }) =>
      api<Device>('/api/pairing/pair', { method: 'POST', json: body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.devices }),
  })
}

/** Общий помощник «Все выкл» с дашборда. */
export async function powerOffAll(queryClient: QueryClient, devices: Device[]) {
  await Promise.allSettled(
    devices
      .filter((device) => device.connection === 'online')
      .map((device) =>
        api<CommandResult>(`/api/devices/${device.uuid}/command`, {
          method: 'POST',
          json: { power: false },
          headers: { 'Idempotency-Key': `ui:${crypto.randomUUID()}` },
        }),
      ),
  )
  await queryClient.invalidateQueries({ queryKey: keys.devices })
}
