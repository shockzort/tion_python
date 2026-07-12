import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import { usePersistentState } from './usePersistentState'

beforeEach(() => localStorage.clear())

describe('usePersistentState', () => {
  it('без сохранённого значения возвращает initial', () => {
    const { result } = renderHook(() => usePersistentState('eb:test', 42))
    expect(result.current[0]).toBe(42)
  })

  it('значение переживает повторный маунт', () => {
    const first = renderHook(() =>
      usePersistentState<string[]>('eb:test', []),
    )
    act(() => first.result.current[1](['a', 'b']))
    first.unmount()

    const second = renderHook(() =>
      usePersistentState<string[]>('eb:test', []),
    )
    expect(second.result.current[0]).toEqual(['a', 'b'])
  })

  it('битый JSON в localStorage — откат к initial', () => {
    localStorage.setItem('eb:test', '{кривой json')
    const { result } = renderHook(() => usePersistentState('eb:test', 'ok'))
    expect(result.current[0]).toBe('ok')
  })
})
