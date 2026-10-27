import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { Appliance } from '../api/types'
import ApplianceCard from './ApplianceCard'

beforeEach(() => localStorage.clear())

const appliance: Appliance = {
  id: '2232120756',
  name: 'Хлюпик',
  model: 'xiaomi.humidifier.ha2',
  online: true,
  state: {
    power: true,
    function: 'humidify',
    humidifier_mode: 'constant',
    purifier_mode: 'fan',
    target_humidity: 55,
    humidifier_fan_level: 1,
    purifier_fan_level: 1,
    water_level: 75,
    water_state: 'normal',
    fault: 0,
    humidity: 48,
    temperature: 24,
    pm25: 3,
    pm1: 1,
    air_quality: 0,
    purifier_filter_life: 100,
    humidifier_filter_life: 8,
    screen: true,
    sound: false,
    child_lock: false,
  },
  state_at: 1_000,
  error: null,
}

describe('ApplianceCard', () => {
  it('показывает состояние и предупреждает об износе фильтра', () => {
    render(<ApplianceCard appliance={appliance} onCommand={vi.fn()} />)
    expect(screen.getByText('Хлюпик')).toBeInTheDocument()
    expect(screen.getByText('на связи')).toBeInTheDocument()
    expect(screen.getByText('55%')).toBeInTheDocument()
    expect(screen.getByText(/48% · 24°C · PM2\.5 3/)).toBeInTheDocument()
    expect(screen.getByText('фильтр увлажнения 8%')).toHaveClass('text-rose-400')
  })

  it('шагает целевую влажность по 5 % и меняет функцию', () => {
    const onCommand = vi.fn()
    render(<ApplianceCard appliance={appliance} onCommand={onCommand} />)
    fireEvent.click(screen.getByRole('button', { name: 'влажнее' }))
    expect(onCommand).toHaveBeenLastCalledWith({ target_humidity: 60 })
    fireEvent.click(screen.getByRole('button', { name: 'суше' }))
    expect(onCommand).toHaveBeenLastCalledWith({ target_humidity: 50 })
    fireEvent.click(screen.getByRole('button', { name: 'Очистка' }))
    expect(onCommand).toHaveBeenLastCalledWith({ function: 'purify' })
  })

  it('без связи блокирует управление и показывает проблемы воды', () => {
    render(
      <ApplianceCard
        appliance={{
          ...appliance,
          online: false,
          state: { ...appliance.state!, water_state: 'no_tank' },
        }}
        onCommand={vi.fn()}
      />,
    )
    expect(screen.getByText('нет связи')).toBeInTheDocument()
    expect(screen.getByText('бак снят')).toBeInTheDocument()
    expect(screen.getByRole('switch', { name: 'Включён' })).toBeDisabled()
  })

  it('свёрнутая карточка — одна строка сводки', () => {
    render(<ApplianceCard appliance={appliance} onCommand={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: /Хлюпик/ }))
    expect(screen.getByText('Увлажнение · цель 55% · влажность 48%')).toBeInTheDocument()
  })
})
