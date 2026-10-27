import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import Automation from './Automation'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const trigger = {
  id: 1,
  name: 'День, спальня',
  sensor_id: 3,
  metric: 'co2',
  kind: 'maintain',
  op: '>',
  threshold: 1100,
  hysteresis: 80,
  cooldown_s: 600,
  window_start: '09:00',
  window_end: '23:00',
  speed_min: 1,
  speed_max: 6,
  targets: [{ device_uuid: 'a' }],
  enter_scenario_id: null,
  enter_actions: null,
  exit_scenario_id: null,
  exit_actions: null,
  enabled: true,
  is_active: false,
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Automation · триггеры', () => {
  it('кнопка копирования создаёт выключенную копию и открывает её редактор', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      if (url === '/api/triggers' && init?.method === 'POST') {
        return json({ ...trigger, ...JSON.parse(String(init.body)), id: 2 }, 201)
      }
      if (url.startsWith('/api/triggers')) return json([trigger])
      if (url.startsWith('/api/sensors')) {
        return json([{ id: 3, name: 'CO₂', kind: 'magicair', capabilities: ['co2'], room_id: 2, last_values: null, stale: false }])
      }
      if (url.startsWith('/api/rooms')) return json([{ id: 1, name: 'Гостиная' }, { id: 2, name: 'Спальня' }])
      if (url.startsWith('/api/groups')) return json([{ id: 1, name: 'Все бризеры', device_uuids: ['a', 'b'] }])
      if (url.startsWith('/api/devices')) {
        return json([
          { uuid: 'a', name: 'Бризер 4S', room_id: 2, connection: 'online', state: null },
          { uuid: 'b', name: 'Бризер 4S', room_id: 1, connection: 'online', state: null },
        ])
      }
      return json([])
    })
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <Automation />
      </QueryClientProvider>,
    )
    fireEvent.click(screen.getByText('Триггеры'))
    fireEvent.click(await screen.findByRole('button', { name: 'Копировать' }))

    await waitFor(() => expect(screen.getByDisplayValue('День, спальня (копия)')).toBeTruthy())
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')
    expect(JSON.parse(String(post?.[1]?.body))).toMatchObject({
      name: 'День, спальня (копия)',
      enabled: false,
      threshold: 1100,
      targets: [{ device_uuid: 'a' }],
    })
  })

  it('в редакторе триггера цели и датчики подписаны комнатой', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url.startsWith('/api/triggers')) return json([trigger])
      if (url.startsWith('/api/sensors')) {
        return json([{ id: 3, name: 'CO₂', kind: 'magicair', capabilities: ['co2'], room_id: 2, last_values: null, stale: false }])
      }
      if (url.startsWith('/api/rooms')) return json([{ id: 1, name: 'Гостиная' }, { id: 2, name: 'Спальня' }])
      if (url.startsWith('/api/groups')) return json([{ id: 1, name: 'Все бризеры', device_uuids: ['a', 'b'] }])
      if (url.startsWith('/api/devices')) {
        return json([
          { uuid: 'a', name: 'Бризер 4S', room_id: 2, connection: 'online', state: null },
          { uuid: 'b', name: 'Бризер 4S', room_id: 1, connection: 'online', state: null },
        ])
      }
      return json([])
    })
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <Automation />
      </QueryClientProvider>,
    )
    fireEvent.click(screen.getByText('Триггеры'))
    fireEvent.click(await screen.findByRole('button', { name: 'Изменить' }))

    expect(await screen.findByRole('button', { name: 'Бризер 4S · Спальня' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Бризер 4S · Гостиная' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Группа · Все бризеры (Спальня, Гостиная)' })).toBeTruthy()
    expect(screen.getByRole('option', { name: 'CO₂ · Спальня' })).toBeTruthy()
  })
})

describe('Automation · влажность', () => {
  const appliance = { id: '2232120756', name: 'Хлюпик', model: 'xiaomi.humidifier.ha2', online: true, state: null, state_at: null, error: null }

  const mockApi = () =>
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      if (init?.method === 'POST') return json({ id: 9, ...JSON.parse(String(init.body)) }, 201)
      if (url.startsWith('/api/appliances')) return json([appliance])
      if (url.startsWith('/api/sensors')) {
        return json([
          { id: 3, name: 'CO₂', kind: 'magicair', capabilities: ['co2'], room_id: null, last_values: null, stale: false },
          { id: 4, name: 'Qingping', kind: 'qingping_mqtt', capabilities: ['co2', 'humidity'], room_id: null, last_values: null, stale: false },
        ])
      }
      return json([])
    })

  const renderPage = () =>
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <Automation />
      </QueryClientProvider>,
    )

  it('сценарий: пресет «поддерживать влажность» уходит одной командой прибору', async () => {
    const fetchMock = mockApi()
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: '+ Новый сценарий' }))
    fireEvent.change(screen.getByPlaceholderText(/Название/), { target: { value: 'Ночь' } })
    const option = await screen.findByRole('option', { name: 'Прибор · Хлюпик' })
    fireEvent.change(option.closest('select')!, { target: { value: 'appliance:2232120756' } })
    fireEvent.change(screen.getByLabelText(/Поддерживать влажность/), { target: { value: '55' } })
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(true))
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({
      name: 'Ночь',
      actions: [
        {
          target_type: 'appliance',
          target_id: '2232120756',
          delta: { power: true, function: 'humidify', humidifier_mode: 'constant', target_humidity: 55 },
        },
      ],
    })
  })

  it('триггер: регулятор влажности берёт только датчики влажности и приборы', async () => {
    const fetchMock = mockApi()
    renderPage()
    fireEvent.click(screen.getByText('Триггеры'))
    fireEvent.click(await screen.findByRole('button', { name: '+ Новый триггер' }))
    fireEvent.click(screen.getByRole('button', { name: 'Поддержание влажности' }))
    fireEvent.change(screen.getByPlaceholderText(/Название/), { target: { value: 'Влажность' } })
    expect(screen.queryByRole('option', { name: 'CO₂' })).toBeNull()
    fireEvent.click(await screen.findByRole('switch', { name: 'Хлюпик' }))
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(true))
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')
    expect(JSON.parse(String(post?.[1]?.body))).toMatchObject({
      name: 'Влажность',
      sensor_id: 4,
      metric: 'humidity',
      kind: 'maintain',
      threshold: 50,
      hysteresis: 3,
      cooldown_s: 300,
      speed_max: 2,
      targets: [{ target_type: 'appliance', target_id: '2232120756' }],
    })
  })
})
