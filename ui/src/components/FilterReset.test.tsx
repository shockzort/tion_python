import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '../api/client'
import type { CommandResult, Device } from '../api/types'
import FilterReset from './FilterReset'

vi.mock('../api/client', () => ({ api: vi.fn() }))
const device: Device = {
  uuid: 'one', name: 'Спальня', mac: 'FA:KE:00:00:00:01', model: 's4',
  room_id: null, paired: true, connection: 'online', state: null,
  state_at: null, hold_until: null, filter_reset_supported: true,
}
const done: CommandResult = { command_id: 1, status: 'done', result_state: null, error: null }
function setup(overrides: Partial<Device> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><FilterReset device={{ ...device, ...overrides }} /></QueryClientProvider>)
  return userEvent.setup()
}
afterEach(() => { vi.restoreAllMocks(); vi.mocked(api).mockReset() })

describe('Смена фильтров', () => {
  it('не отправляет команду без подтверждения', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    const user = setup()
    await user.click(screen.getByRole('button', { name: 'Смена фильтров' }))
    expect(api).not.toHaveBeenCalled()
  })
  it('недоступна при потере связи', () => {
    setup({ connection: 'disconnected' })
    expect(screen.getByRole('button', { name: 'Смена фильтров' })).toBeDisabled()
  })
  it('202 остаётся в ожидании до подтверждённого итога', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    let finish!: (result: CommandResult) => void
    vi.mocked(api).mockImplementation((path) => path.endsWith('/filter-reset')
      ? Promise.resolve({ ...done, status: 'pending' })
      : new Promise<CommandResult>((resolve) => { finish = resolve }) as ReturnType<typeof api>)
    const user = setup()
    await user.click(screen.getByRole('button', { name: 'Смена фильтров' }))
    await waitFor(() => expect(finish).toBeDefined())
    expect(screen.getByRole('button', { name: 'Сбрасываем…' })).toBeDisabled()
    expect(screen.queryByText('Ресурс фильтров обновлён')).toBeNull()
    await act(async () => { finish(done) })
    await screen.findByText('Ресурс фильтров обновлён')
  })
  it('после потери HTTP-ответа повторяет прежний ключ', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.mocked(api).mockRejectedValueOnce(new Error('Ответ потерян')).mockResolvedValueOnce(done)
    const user = setup()
    await user.click(screen.getByRole('button', { name: 'Смена фильтров' }))
    await screen.findByText('Ответ потерян')
    await user.click(screen.getByRole('button', { name: 'Смена фильтров' }))
    await screen.findByText('Ресурс фильтров обновлён')
    expect(vi.mocked(api).mock.calls[0][1]?.headers).toEqual(vi.mocked(api).mock.calls[1][1]?.headers)
  })
  it('не выдаёт ошибку проверки за успех', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.mocked(api).mockResolvedValueOnce({ ...done, status: 'failed', error: 'Результат сброса не подтверждён' })
    const user = setup()
    await user.click(screen.getByRole('button', { name: 'Смена фильтров' }))
    await screen.findByText('Результат сброса не подтверждён')
    expect(screen.queryByText('Ресурс фильтров обновлён')).toBeNull()
  })
})
