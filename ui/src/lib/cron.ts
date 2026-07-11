// Конструктор расписаний «время + дни» ↔ cron (5 полей).
// Дни — ISO: 1=пн … 7=вс; пустой список означает «ежедневно».

export type SchedulePreset = { time: string; days: number[] }

export const DAY_LABELS = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс'] as const

export function cronFromPreset(preset: SchedulePreset): string {
  const [hours, minutes] = preset.time.split(':').map(Number)
  const days =
    preset.days.length === 0 || preset.days.length === 7
      ? '*'
      : [...preset.days]
          .map((day) => day % 7) // ISO вс=7 → cron вс=0
          .sort((a, b) => a - b)
          .join(',')
  return `${minutes} ${hours} * * ${days}`
}

/** Разбор cron обратно в конструктор; null — выражение сложнее пресета. */
export function presetFromCron(cron: string): SchedulePreset | null {
  const parts = cron.trim().split(/\s+/)
  if (parts.length !== 5) return null
  const [minuteRaw, hourRaw, dom, month, dowRaw] = parts
  if (dom !== '*' || month !== '*') return null
  const minute = Number(minuteRaw)
  const hour = Number(hourRaw)
  if (!Number.isInteger(minute) || minute < 0 || minute > 59) return null
  if (!Number.isInteger(hour) || hour < 0 || hour > 23) return null

  let days: number[] = []
  if (dowRaw !== '*') {
    const seen = new Set<number>()
    for (const token of dowRaw.split(',')) {
      const value = Number(token)
      if (!Number.isInteger(value) || value < 0 || value > 7) return null
      seen.add(value === 0 ? 7 : value) // cron вс=0/7 → ISO 7
    }
    days = [...seen].sort((a, b) => a - b)
    if (days.length === 7) days = []
  }
  const pad = (value: number) => String(value).padStart(2, '0')
  return { time: `${pad(hour)}:${pad(minute)}`, days }
}

/** Человекочитаемое описание; нераспознанный cron показывается как есть. */
export function describeCron(cron: string): string {
  const preset = presetFromCron(cron)
  if (preset === null) return cron
  const days =
    preset.days.length === 0
      ? 'ежедневно'
      : preset.days.map((day) => DAY_LABELS[day - 1]).join(', ')
  return `${preset.time} · ${days}`
}
