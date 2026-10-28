import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ApplianceCard from './ApplianceCard'
import { appliance, applianceSensor } from './applianceFixture'

beforeEach(() => localStorage.clear())

const withState = (patch: Partial<NonNullable<typeof appliance.state>>) => ({
  ...appliance,
  state: { ...appliance.state!, ...patch },
})

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

  it('«Избранный» режим увлажнения не предлагается, но виден, если включён', () => {
    const { rerender } = render(<ApplianceCard appliance={appliance} onCommand={vi.fn()} />)
    const modes = screen.getByRole('group', { name: 'Режим увлажнения' })
    expect(modes).not.toHaveTextContent('Избранный')
    rerender(<ApplianceCard appliance={withState({ humidifier_mode: 'favorite' })} onCommand={vi.fn()} />)
    expect(screen.getByRole('group', { name: 'Режим увлажнения' })).toHaveTextContent('Избранный')
  })

  it('свой уровень очистки 0–9', () => {
    const onCommand = vi.fn()
    render(
      <ApplianceCard
        appliance={withState({ function: 'purify', purifier_mode: 'favorite', purifier_favorite_level: 4 })}
        onCommand={onCommand}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'сильнее' }))
    expect(onCommand).toHaveBeenLastCalledWith({ purifier_favorite_level: 5 })
  })

  it('таймер выключения: длительность и включение одной командой', () => {
    const onCommand = vi.fn()
    const { rerender } = render(<ApplianceCard appliance={appliance} onCommand={onCommand} />)
    fireEvent.change(screen.getByRole('combobox', { name: 'Таймер выключения' }), { target: { value: '2' } })
    expect(onCommand).toHaveBeenLastCalledWith({ off_timer_hours: 2, off_timer: true })
    rerender(
      <ApplianceCard
        appliance={withState({ off_timer: true, off_timer_hours: 2, off_timer_remaining: 85 })}
        onCommand={onCommand}
      />,
    )
    expect(screen.getByText('(осталось 1 ч 25 мин)')).toBeInTheDocument()
    fireEvent.change(screen.getByRole('combobox', { name: 'Таймер выключения' }), { target: { value: '0' } })
    expect(onCommand).toHaveBeenLastCalledWith({ off_timer: false })
  })

  it('без связи блокирует управление и показывает проблемы воды', () => {
    render(
      <ApplianceCard appliance={{ ...withState({ water_state: 'no_tank' }), online: false }} onCommand={vi.fn()} />,
    )
    expect(screen.getByText('нет связи')).toBeInTheDocument()
    expect(screen.getByText('бак снят')).toBeInTheDocument()
    expect(screen.getByRole('switch', { name: 'Включён' })).toBeDisabled()
  })

  it('свёрнутая — показания как у датчика и режим, без органов управления', () => {
    render(<ApplianceCard appliance={appliance} sensor={applianceSensor} onCommand={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: /Хлюпик/ }))
    // строка показаний датчика (с цветом), а не сырые поля прибора
    expect(document.querySelector('[data-metric="humidity"]')).toHaveTextContent('52')
    expect(screen.getByText('Увлажнение · цель 55% · вода 75%')).toBeInTheDocument()
    expect(screen.queryByRole('switch')).toBeNull()
  })

  it('настройки открываются из развёрнутой карточки', () => {
    const onOpenSettings = vi.fn()
    render(<ApplianceCard appliance={appliance} onCommand={vi.fn()} onOpenSettings={onOpenSettings} />)
    fireEvent.click(screen.getByRole('button', { name: 'Настройки прибора…' }))
    expect(onOpenSettings).toHaveBeenCalled()
  })
})
