import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import IntentBar from './IntentBar'

function renderBar() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <IntentBar />
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('IntentBar', () => {
  it('отправляет фразу и показывает ответ', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          reply: 'Готово: скорость 3 → Спальня.',
          executed: true,
          intent: 'device_command',
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    renderBar()
    fireEvent.change(screen.getByLabelText('текстовая команда'), {
      target: { value: 'поставь скорость три в спальне' },
    })
    fireEvent.click(screen.getByRole('button'))

    await waitFor(() =>
      expect(screen.getByText('Готово: скорость 3 → Спальня.')).toBeTruthy(),
    )
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/intents/execute',
      expect.objectContaining({ method: 'POST' }),
    )
    // исполненная команда очищает строку
    const input = screen.getByLabelText('текстовая команда') as HTMLInputElement
    expect(input.value).toBe('')
  })

  it('неисполненный ответ оставляет текст для правки', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ reply: 'Уточните, какой бризер…', executed: false, intent: null }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    renderBar()
    const input = screen.getByLabelText('текстовая команда') as HTMLInputElement
    fireEvent.change(input, { target: { value: 'поставь скорость три' } })
    fireEvent.click(screen.getByRole('button'))

    await waitFor(() =>
      expect(screen.getByText('Уточните, какой бризер…')).toBeTruthy(),
    )
    expect(input.value).toBe('поставь скорость три')
  })
})
