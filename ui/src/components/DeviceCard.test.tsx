import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { Device } from '../api/types'
import DeviceCard from './DeviceCard'

const onlineDevice: Device = {
  uuid: 'dev-1',
  mac: 'FA:KE:00:00:00:01',
  name: 'Спальня',
  model: 's4',
  room_id: null,
  paired: true,
  connection: 'online',
  state: {
    power: true,
    sound: false,
    light: true,
    heater: true,
    mode: 'outside',
    heater_temp: 22,
    fan_speed: 3,
    in_temp: 5,
    out_temp: 21,
    filter_remain_days: 55.5,
  },
  state_at: 1_000,
  hold_until: null,
}

describe('DeviceCard', () => {
  it('показывает состояние устройства', () => {
    render(
      <DeviceCard
        device={onlineDevice}
        roomName="Спальня (комната)"
        onCommand={vi.fn()}
        onReleaseHold={vi.fn()}
      />,
    )
    expect(screen.getByText('Спальня')).toBeInTheDocument()
    expect(screen.getByText('на связи')).toBeInTheDocument()
    expect(screen.getByRole('slider', { name: 'Скорость' })).toHaveValue('3')
    expect(screen.getByText('22°C')).toBeInTheDocument()
    expect(screen.getByText(/фильтр 56 дн/)).toBeInTheDocument()
    expect(screen.getByText(/приток 21°C/)).toBeInTheDocument()
  })

  it('переключение питания шлёт команду', () => {
    const onCommand = vi.fn()
    render(
      <DeviceCard
        device={onlineDevice}
        onCommand={onCommand}
        onReleaseHold={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByRole('switch', { name: 'Включён' }))
    expect(onCommand).toHaveBeenCalledWith({ power: false })
  })

  it('слайдер шлёт скорость при отпускании, а не при каждом движении', () => {
    const onCommand = vi.fn()
    render(
      <DeviceCard
        device={onlineDevice}
        onCommand={onCommand}
        onReleaseHold={vi.fn()}
      />,
    )
    const slider = screen.getByRole('slider', { name: 'Скорость' })
    fireEvent.change(slider, { target: { value: '5' } })
    fireEvent.change(slider, { target: { value: '6' } })
    expect(onCommand).not.toHaveBeenCalled()
    fireEvent.pointerUp(slider)
    expect(onCommand).toHaveBeenCalledTimes(1)
    expect(onCommand).toHaveBeenCalledWith({ fan_speed: 6 })
  })

  it('смена режима и шаг температуры', () => {
    const onCommand = vi.fn()
    render(
      <DeviceCard
        device={onlineDevice}
        onCommand={onCommand}
        onReleaseHold={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Рециркуляция' }))
    expect(onCommand).toHaveBeenCalledWith({ mode: 'recirculation' })
    fireEvent.click(screen.getByRole('button', { name: 'теплее' }))
    expect(onCommand).toHaveBeenCalledWith({ heater_temp: 23 })
  })

  it('бейдж ручного управления и снятие hold', () => {
    const onReleaseHold = vi.fn()
    render(
      <DeviceCard
        device={{ ...onlineDevice, hold_until: 4_102_444_800 }}
        onCommand={vi.fn()}
        onReleaseHold={onReleaseHold}
      />,
    )
    expect(screen.getByText(/ручное до \d{2}:\d{2}/)).toBeInTheDocument()
    fireEvent.click(
      screen.getByRole('button', { name: 'вернуть автоматику' }),
    )
    expect(onReleaseHold).toHaveBeenCalled()
  })

  it('офлайн: бейдж «нет связи», управление заблокировано', () => {
    render(
      <DeviceCard
        device={{ ...onlineDevice, connection: 'disconnected' }}
        onCommand={vi.fn()}
        onReleaseHold={vi.fn()}
      />,
    )
    expect(screen.getByText('нет связи')).toBeInTheDocument()
    expect(screen.getByRole('switch', { name: 'Включён' })).toBeDisabled()
    expect(screen.getByRole('slider', { name: 'Скорость' })).toBeDisabled()
  })

  it('без данных состояния — заглушка вместо контролов', () => {
    render(
      <DeviceCard
        device={{ ...onlineDevice, state: null, connection: 'connecting' }}
        onCommand={vi.fn()}
        onReleaseHold={vi.fn()}
      />,
    )
    expect(screen.getByText(/Нет данных/)).toBeInTheDocument()
    expect(screen.queryByRole('slider')).not.toBeInTheDocument()
  })
})
