import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import ApplianceSettings from './ApplianceSettings'
import { appliance } from './applianceFixture'
import QingpingSettings from './QingpingSettings'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

function wrap(children: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(<QueryClientProvider client={queryClient}>{children}</QueryClientProvider>)
}

const bodyOf = (call: unknown[]) => JSON.parse(String((call[1] as RequestInit).body)) as unknown

afterEach(() => {
  vi.restoreAllMocks()
})

describe('ApplianceSettings', () => {
  it('каждая настройка — отдельная команда прибору', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url.endsWith('/command') || url.endsWith('/action')) return json(appliance)
      return json([appliance])
    })
    wrap(<ApplianceSettings applianceId={appliance.id} onClose={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Тускло' }))
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        `/api/appliances/${appliance.id}/command`,
        expect.objectContaining({ method: 'POST' }),
      ),
    )
    expect(bodyOf(fetchMock.mock.calls.at(-1)!)).toEqual({ screen_brightness: 'dim' })

    expect(screen.getByLabelText('Начало ночного режима')).toHaveValue('23:00')
    fireEvent.change(screen.getByLabelText('Конец ночного режима'), { target: { value: '07:30' } })
    await waitFor(() => expect(bodyOf(fetchMock.mock.calls.at(-1)!)).toEqual({ night_end: 450 }))

    // сброс фильтра — только после подтверждения
    const confirmMock = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const calls = fetchMock.mock.calls.length
    fireEvent.click(screen.getAllByRole('button', { name: 'Сбросить' })[0])
    expect(confirmMock).toHaveBeenCalled()
    expect(fetchMock.mock.calls.length).toBe(calls)
    confirmMock.mockReturnValue(true)
    fireEvent.click(screen.getAllByRole('button', { name: 'Сбросить' })[0])
    await waitFor(() => expect(bodyOf(fetchMock.mock.calls.at(-1)!)).toEqual({ action: 'reset_humidifier_filter' }))
  })
})

const QINGPING = {
  screensaver: 'time_rotate',
  display_off_time: 600,
  auto_slide_time: 120,
  power_off_time: 30,
  night_start: 0,
  night_end: 0,
  temperature_unit: 'C',
  is_12_hour: false,
  timezone: 3,
  co2_asc: true,
  temperature_offset: 0,
  humidity_offset: 0,
  co2_offset: 0,
  pm25_offset: 0,
  pm10_offset: 0,
  co2_led_th: [1000, 2000, 3000],
  pm25_led_th: [35, 75, 115, 150, 250],
}

describe('QingpingSettings', () => {
  it('читает конфиг с датчика и сохраняет только изменённое', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (_input, init) => {
      if (init?.method === 'PUT') {
        return json({ settings: { ...QINGPING, ...(JSON.parse(String(init.body)) as object) } })
      }
      return json({ settings: QINGPING })
    })
    wrap(<QingpingSettings sensorId={4} name="Станция" onClose={vi.fn()} />)
    const save = await screen.findByRole('button', { name: 'Сохранить' })
    expect(save).toBeDisabled()

    fireEvent.change(screen.getByLabelText('Поправка: Влажность, %'), { target: { value: '-2.5' } })
    fireEvent.click(screen.getByRole('switch', { name: 'Включён' }))
    expect(screen.getByLabelText('Начало ночного режима')).toHaveValue('23:00')
    fireEvent.click(save)

    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'PUT')).toBe(true))
    const put = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')!
    expect(put[0]).toBe('/api/sensors/4/settings')
    expect(bodyOf(put)).toEqual({ humidity_offset: -2.5, night_start: 1380, night_end: 420 })
    // ответ датчика стал новой базой — черновик пуст
    await waitFor(() => expect(screen.getByRole('button', { name: 'Сохранить' })).toBeDisabled())
  })

  it('датчик не ответил — ошибка и повтор', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () =>
      json({ detail: 'датчик не ответил за 10 с — он в сети?' }, 504),
    )
    wrap(<QingpingSettings sensorId={4} name="Станция" onClose={vi.fn()} />)
    expect(await screen.findByText(/Не удалось прочитать настройки/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Повторить' })).toBeInTheDocument()
  })
})
