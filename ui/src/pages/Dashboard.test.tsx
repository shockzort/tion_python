import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import Dashboard from './Dashboard'

const json = (body: unknown) =>
  new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })

const device = (uuid: string, connection: string) => ({
  uuid,
  name: `Бризер ${uuid}`,
  mac: '00:00:00:00:00:00',
  model: '4S',
  room_id: null,
  connection,
  state: null,
})

function mockApi() {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const url = String(input)
    if (url.endsWith('/command')) return json({ status: 'done', result_state: null })
    if (url.startsWith('/api/devices')) return json([device('a', 'online'), device('b', 'offline')])
    if (url.startsWith('/api/scenarios')) return json([{ id: 3, name: 'Проветривание', actions: [] }])
    return json([])
  })
}

function renderDashboard() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Dashboard', () => {
  it('«Тихий режим» стоит после сценариев и шлёт команду только бризерам на связи', async () => {
    const fetchMock = mockApi()
    renderDashboard()

    await screen.findByText('Проветривание')
    const buttons = screen.getAllByRole('button').map((button) => button.textContent)
    expect(buttons.indexOf('Тихий режим')).toBe(buttons.indexOf('Проветривание') + 1)
    expect(screen.queryByText('Все выкл')).toBeNull()

    fireEvent.click(screen.getByText('Тихий режим'))
    await waitFor(() => {
      const commands = fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/command'))
      expect(commands).toHaveLength(1)
      expect(String(commands[0][0])).toBe('/api/devices/a/command')
      expect(JSON.parse(String(commands[0][1]?.body))).toEqual({
        power: true,
        fan_speed: 1,
        sound: false,
        light: false,
      })
    })
  })
})
