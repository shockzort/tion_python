import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { FoundBreezer } from '../api/types'
import PairWizard from './PairWizard'

const apiMock = vi.hoisted(() => vi.fn())
vi.mock('../api/client', () => ({
  api: apiMock,
  ApiError: class ApiError extends Error {
    status: number

    constructor(status: number, detail: string) {
      super(detail)
      this.status = status
    }
  },
}))

const found: FoundBreezer[] = [
  {
    mac: 'FA:KE:00:00:00:04',
    name: 'Breezer 4S (фейк 4)',
    rssi: -60,
    model_hint: 's4',
    pairing_mode: true,
    registered: false,
  },
  {
    mac: 'FA:KE:00:00:00:01',
    name: 'Breezer 4S (фейк 1)',
    rssi: -45,
    model_hint: 's4',
    pairing_mode: null,
    registered: true,
  },
]

function wrap(children: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { mutations: { retry: false } },
  })
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
}

beforeEach(() => {
  apiMock.mockReset()
})

describe('PairWizard', () => {
  it('полный проход: инструкция → скан → выбор → имя → готово', async () => {
    apiMock.mockImplementation((path: string) => {
      if (path === '/api/pairing/scan') return Promise.resolve(found)
      if (path === '/api/pairing/pair') {
        return Promise.resolve({ uuid: 'new', name: 'Кухня' })
      }
      return Promise.reject(new Error(`неожиданный вызов ${path}`))
    })
    render(wrap(<PairWizard onClose={vi.fn()} />))

    expect(screen.getByText(/режим сопряжения/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Начать поиск' }))

    // после скана — список: несопряжённый кликабелен, добавленный — нет
    const candidate = await screen.findByRole('button', {
      name: /фейк 4/,
    })
    expect(
      screen.getByRole('button', { name: /фейк 1/ }),
    ).toBeDisabled()
    expect(screen.getByText('уже добавлен')).toBeInTheDocument()
    fireEvent.click(candidate)

    // имя предзаполнено именем из эфира
    const nameInput = screen.getByRole('textbox', { name: 'Название' })
    expect(nameInput).toHaveValue('Breezer 4S (фейк 4)')
    fireEvent.change(nameInput, { target: { value: 'Кухня' } })
    fireEvent.click(screen.getByRole('button', { name: 'Сопрячь' }))

    await waitFor(() =>
      expect(screen.getByText(/«Кухня» добавлен/)).toBeInTheDocument(),
    )
    expect(apiMock).toHaveBeenCalledWith(
      '/api/pairing/pair',
      expect.objectContaining({
        json: { mac: 'FA:KE:00:00:00:04', name: 'Кухня' },
      }),
    )
  })

  it('пустой эфир: подсказка и повторный поиск', async () => {
    apiMock.mockResolvedValue([])
    render(wrap(<PairWizard onClose={vi.fn()} />))
    fireEvent.click(screen.getByRole('button', { name: 'Начать поиск' }))
    expect(await screen.findByText(/не найдены/)).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Искать снова' }),
    ).toBeInTheDocument()
  })

  it('ошибка пейринга показывает сообщение сервера', async () => {
    apiMock.mockImplementation((path: string) => {
      if (path === '/api/pairing/scan') return Promise.resolve(found)
      return Promise.reject(new Error('бонд не создан'))
    })
    render(wrap(<PairWizard onClose={vi.fn()} />))
    fireEvent.click(screen.getByRole('button', { name: 'Начать поиск' }))
    fireEvent.click(await screen.findByRole('button', { name: /фейк 4/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Сопрячь' }))
    await waitFor(() =>
      expect(screen.getByText(/сервер недоступен/)).toBeInTheDocument(),
    )
    expect(
      screen.getByRole('button', { name: 'Повторить поиск' }),
    ).toBeInTheDocument()
  })
})
