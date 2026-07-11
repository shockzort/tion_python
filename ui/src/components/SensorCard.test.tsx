import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { Sensor } from '../api/types'
import SensorCard from './SensorCard'

function makeSensor(overrides: Partial<Sensor> = {}): Sensor {
  return {
    id: 1,
    kind: 'magicair',
    name: 'Гостиная CO₂',
    source_key: 'magicair:guid-1',
    room_id: null,
    last_values: { co2: 950, temperature: 24.3, humidity: 41 },
    last_seen_at: 1_000,
    stale: false,
    ...overrides,
  }
}

describe('SensorCard', () => {
  it('показывает метрики с округлением', () => {
    render(<SensorCard sensor={makeSensor()} roomName="Гостиная" />)
    expect(screen.getByText('Гостиная CO₂')).toBeTruthy()
    expect(screen.getByText('950')).toBeTruthy()
    expect(screen.getByText('24.3 °C')).toBeTruthy()
    expect(screen.getByText('41 %')).toBeTruthy()
    expect(screen.getByText('Гостиная')).toBeTruthy()
  })

  it('подсвечивает CO₂ по бытовой шкале', () => {
    const { rerender } = render(
      <SensorCard sensor={makeSensor({ last_values: { co2: 600 } })} />,
    )
    expect(screen.getByText('600').parentElement?.className).toContain(
      'text-emerald-400',
    )
    rerender(<SensorCard sensor={makeSensor({ last_values: { co2: 900 } })} />)
    expect(screen.getByText('900').parentElement?.className).toContain(
      'text-amber-400',
    )
    rerender(<SensorCard sensor={makeSensor({ last_values: { co2: 1400 } })} />)
    expect(screen.getByText('1400').parentElement?.className).toContain(
      'text-rose-400',
    )
  })

  it('стейл гасит значение и показывает бейдж', () => {
    render(
      <SensorCard
        sensor={makeSensor({ stale: true, last_values: { co2: 700 } })}
      />,
    )
    expect(screen.getByText('нет данных')).toBeTruthy()
    expect(screen.getByText('700').parentElement?.className).toContain(
      'text-slate-500',
    )
  })

  it('без данных пишет «ждём данные»', () => {
    render(<SensorCard sensor={makeSensor({ last_values: null, stale: true })} />)
    expect(screen.getByText('ждём данные…')).toBeTruthy()
  })
})
