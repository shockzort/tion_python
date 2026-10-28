import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'

import { keys } from './api/queries'
import type { Appliance } from './api/types'
import { appliance } from './components/applianceFixture'
import { handleEvent } from './ws'

const event = (state: Partial<NonNullable<Appliance['state']>>) => ({
  topic: 'appliance.state_changed',
  data: { ...appliance, state: { ...appliance.state!, ...state } } as unknown as Record<string, unknown>,
})

const powerOf = (queryClient: QueryClient) =>
  queryClient.getQueryData<Appliance[]>(keys.appliances)?.[0].state?.power

describe('WS: appliance.state_changed', () => {
  it('применяет снапшот, когда команд в полёте нет', () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData(keys.appliances, [appliance])
    handleEvent(queryClient, event({ power: false }))
    expect(powerOf(queryClient)).toBe(false)
  })

  it('не перетирает optimistic-состояние, пока команда прибору в полёте', async () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData(keys.appliances, [{ ...appliance, state: { ...appliance.state!, power: false } }])
    let finish: (() => void) | null = null
    const pending = queryClient
      .getMutationCache()
      .build(queryClient, {
        mutationKey: ['appliance-command'],
        mutationFn: () => new Promise<void>((resolve) => (finish = resolve)),
      })
      .execute({ id: appliance.id, body: { power: false } })
    await vi.waitFor(() => expect(finish).not.toBeNull())
    // опрос, начатый до команды, принёс старое «включён»
    handleEvent(queryClient, event({ power: true }))
    expect(powerOf(queryClient)).toBe(false)
    finish!()
    await pending
    handleEvent(queryClient, event({ power: true }))
    expect(powerOf(queryClient)).toBe(true)
  })
})
