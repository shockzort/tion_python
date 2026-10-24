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
    capabilities: ['co2', 'temperature', 'humidity'],
    stale: false,
    ...overrides,
  }
}

const value = (text: string) => screen.getByText(text).className
const color = (text: string) => screen.getByText(text).style.color

describe('SensorCard', () => {
  it('новая температура не делает старый CO₂ свежим', () => {
    render(
      <SensorCard
        sensor={makeSensor({
          stale: true,
          metric_stale: { co2: true, temperature: false, humidity: false },
        })}
      />,
    )
    expect(value('950')).toContain('text-slate-500')
    expect(color('950')).toBe('')
    expect(color('24,3')).toBe('rgb(155, 216, 106)')
    expect(screen.getByText('часть данных устарела')).toBeTruthy()
  })

  it('показывает метрики с точностью справочника и комнату', () => {
    render(<SensorCard sensor={makeSensor({ last_values: { co2: 950, temperature: 24.84, humidity: 57.46 } })} roomName="Гостиная" />)
    expect(screen.getByText('Гостиная CO₂')).toBeTruthy()
    expect(screen.getByText('950')).toBeTruthy()
    expect(screen.getByText('24,8')).toBeTruthy()
    expect(screen.getByText('57,5')).toBeTruthy()
    expect(screen.getByText(/^Гостиная · обновлено/)).toBeTruthy()
  })

  it('показывает пыль и заряд, если датчик их передаёт', () => {
    render(
      <SensorCard
        sensor={makeSensor({
          kind: 'qingping_mqtt',
          capabilities: ['co2', 'temperature', 'humidity', 'pm25', 'pm10', 'battery'],
          last_values: { co2: 817, pm25: 48, pm10: 8, battery: 64 },
        })}
      />,
    )
    expect(screen.getByText('PM2.5')).toBeTruthy()
    expect(color('48')).toBe('rgb(251, 166, 46)')
    expect(screen.getByText('64 %')).toBeTruthy()
  })

  it('красит значение по шкале метрики, устаревшее — без цвета', () => {
    render(<SensorCard sensor={makeSensor({ last_values: { co2: 600, temperature: 22.5 } })} />)
    expect(color('600')).toBe('rgb(52, 211, 153)')
    expect(color('22,5')).toBe('rgb(155, 216, 106)')
  })

  it('стейл гасит значение и показывает бейдж', () => {
    render(<SensorCard sensor={makeSensor({ stale: true, last_values: { co2: 700 } })} />)
    expect(screen.getByText('нет данных')).toBeTruthy()
    expect(value('700')).toContain('text-slate-500')
  })

  it('без данных пишет «ждём данные»', () => {
    render(<SensorCard sensor={makeSensor({ last_values: null, stale: true })} />)
    expect(screen.getByText('ждём данные…')).toBeTruthy()
  })
})
