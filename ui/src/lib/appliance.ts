// Подписи режимов прибора Xiaomi: карточка, настройки и редактор сценариев

import type { HumidifierMode, PurifierMode } from '../api/types'

export const HUMIDIFIER_MODE_LABELS: Record<HumidifierMode, string> = {
  constant: 'По влажности',
  sleep: 'Сон',
  // включается только из Mi Home; своей скорости в протоколе нет
  favorite: 'Избранный',
  fan: 'Скорость',
}

export const PURIFIER_MODE_LABELS: Record<PurifierMode, string> = {
  auto: 'Авто',
  sleep: 'Сон',
  // «Favorite» прибора: постоянный обдув с уровнем 0–9 (10:1)
  favorite: 'Свой уровень',
  fan: 'Скорость',
}

/** «1 ч 25 мин» / «40 мин». */
export function formatMinutesLeft(minutes: number): string {
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  if (hours === 0) return `${rest} мин`
  return rest === 0 ? `${hours} ч` : `${hours} ч ${rest} мин`
}

/** Минуты от полуночи ↔ «HH:MM» для <input type="time">. */
export function minutesToTime(minutes: number): string {
  const hours = Math.floor(minutes / 60) % 24
  return `${String(hours).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`
}

export function timeToMinutes(value: string): number | null {
  const match = /^(\d{1,2}):(\d{2})$/.exec(value)
  if (!match) return null
  const hours = Number(match[1])
  const minutes = Number(match[2])
  return hours < 24 && minutes < 60 ? hours * 60 + minutes : null
}
