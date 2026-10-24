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
    if (url.endsWith('/run')) return json([])
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
  it('кнопки быстрых действий — это сценарии, статических кнопок нет', async () => {
    const fetchMock = mockApi()
    renderDashboard()

    await screen.findByText('Проветривание')
    expect(screen.queryByText('Тихий режим')).toBeNull()
    expect(screen.queryByText('Все выкл')).toBeNull()

    fireEvent.click(screen.getByText('Проветривание'))
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith('/api/scenarios/3/run', expect.objectContaining({ method: 'POST' })),
    )
  })
})
