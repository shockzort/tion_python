// Подписи режимов прибора Xiaomi: карточка и редактор сценариев

import type { HumidifierMode, PurifierMode } from '../api/types'

export const HUMIDIFIER_MODE_LABELS: Record<HumidifierMode, string> = {
  constant: 'По влажности',
  sleep: 'Сон',
  favorite: 'Избранный',
  fan: 'Скорость',
}

export const PURIFIER_MODE_LABELS: Record<PurifierMode, string> = {
  auto: 'Авто',
  sleep: 'Сон',
  favorite: 'Избранный',
  fan: 'Скорость',
}
