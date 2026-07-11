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
  Room,
  User,
} from './types'

export const keys = {
  me: ['me'] as const,
  authStatus: ['auth-status'] as const,
  devices: ['devices'] as const,
  rooms: ['rooms'] as const,
  groups: ['groups'] as const,
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
