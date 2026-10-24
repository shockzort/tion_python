// Справочник метрик датчиков: подписи, единицы, точность и оценка качества.
// Единственное место, где UI знает про конкретные метрики — карточки,
// графики и автоматика строятся по capabilities датчика.

export type SensorMetric = 'co2' | 'temperature' | 'humidity' | 'pm25' | 'pm10' | 'battery'

/** Опорная точка шкалы: значение метрики → цвет (#rrggbb). */
type Stop = [number, string]

// Палитра под тёмный фон (Tailwind *-400): холод/сырость — синий,
// норма — зелёный (комфорт температуры/влажности — тёплый салатовый), дальше жёлтый → оранжевый → красный.
const BLUE = '#60a5fa'
const GREEN = '#34d399'
const LIME = '#9bd86a'
const YELLOW = '#facc15'
const ORANGE = '#fb923c'
const RED = '#f87171'

type MetricInfo = {
  label: string
  short: string
  unit: string
  digits: number
  /** Шкала цвета по возрастанию значения; null — нейтральная метрика. */
  scale: Stop[] | null
}

export const METRIC_INFO: Record<SensorMetric, MetricInfo> = {
  // ≤ 700 свежо, 1000 — граница комфорта, 1400 душно, 2000 — плохо
  co2: {
    label: 'CO₂', short: 'CO₂', unit: 'ppm', digits: 0,
    scale: [[700, GREEN], [1000, YELLOW], [1400, ORANGE], [2000, RED]],
  },
  // < 20 прохладно, 20–25 комфорт, 26+ жарко
  temperature: {
    label: 'Температура', short: 'Темп.', unit: '°C', digits: 1,
    scale: [[17, BLUE], [20, LIME], [25, LIME], [26.5, YELLOW], [28, ORANGE], [30, RED]],
  },
  // < 30 сухо, 40–60 норма, 60+ сыро
  humidity: {
    label: 'Влажность', short: 'Влажн.', unit: '%', digits: 1,
    scale: [[20, ORANGE], [30, YELLOW], [40, LIME], [60, LIME], [70, BLUE]],
  },
  // пороги индекса AQI (EPA): 12 / 35 / 55 / 150 мкг/м³
  pm25: {
    label: 'PM2.5', short: 'PM2.5', unit: 'мкг/м³', digits: 0,
    scale: [[12, GREEN], [35, YELLOW], [55, ORANGE], [150, RED]],
  },
  // норматив ВОЗ (сутки) — 45 мкг/м³
  pm10: {
    label: 'PM10', short: 'PM10', unit: 'мкг/м³', digits: 0,
    scale: [[30, GREEN], [50, YELLOW], [100, ORANGE], [200, RED]],
  },
  // ≤ 10 % пора менять/заряжать, от 60 % — спокойно
  battery: {
    label: 'Батарея', short: 'Бат.', unit: '%', digits: 0,
    scale: [[10, RED], [25, ORANGE], [40, YELLOW], [60, GREEN]],
  },
}

export const METRIC_ORDER: SensorMetric[] = ['co2', 'temperature', 'humidity', 'pm25', 'pm10', 'battery']

/** Метрики, которые имеет смысл показывать крупно и строить по ним правила. */
export const AIR_METRICS: SensorMetric[] = ['co2', 'temperature', 'humidity', 'pm25', 'pm10']

export function isMetric(value: string): value is SensorMetric {
  return value in METRIC_INFO
}

export function formatValue(metric: SensorMetric, value: number): string {
  return value.toLocaleString('ru', {
    minimumFractionDigits: METRIC_INFO[metric].digits,
    maximumFractionDigits: METRIC_INFO[metric].digits,
  })
}

function mix(from: string, to: string, t: number): string {
  const channel = (hex: string, i: number) => parseInt(hex.slice(1 + 2 * i, 3 + 2 * i), 16)
  return `#${[0, 1, 2]
    .map((i) => Math.round(channel(from, i) + (channel(to, i) - channel(from, i)) * t).toString(16).padStart(2, '0'))
    .join('')}`
}

/** Цвет значения: линейная интерполяция между опорными точками; null — нейтрально. */
export function metricColor(metric: SensorMetric, value: number): string | null {
  const scale = METRIC_INFO[metric].scale
  if (scale === null) return null
  if (value <= scale[0][0]) return scale[0][1]
  for (let i = 1; i < scale.length; i++) {
    const [hi, hiColor] = scale[i]
    if (value <= hi) {
      const [lo, loColor] = scale[i - 1]
      return mix(loColor, hiColor, (value - lo) / (hi - lo))
    }
  }
  return scale[scale.length - 1][1]
}

/** Подпись для селектов: «CO₂, ppm». */
export function metricOption(metric: SensorMetric): string {
  return `${METRIC_INFO[metric].label}, ${METRIC_INFO[metric].unit}`
}
