// Справочник метрик датчиков: подписи, единицы, точность и оценка качества.
// Единственное место, где UI знает про конкретные метрики — карточки,
// графики и автоматика строятся по capabilities датчика.

export type SensorMetric = 'co2' | 'temperature' | 'humidity' | 'pm25' | 'pm10' | 'battery'

export type Quality = 'good' | 'fair' | 'poor' | 'neutral'

type MetricInfo = {
  label: string
  short: string
  unit: string
  digits: number
  /** Границы «хорошо → средне → плохо»; null — нейтральная метрика. */
  bands: [number, number] | null
}

export const METRIC_INFO: Record<SensorMetric, MetricInfo> = {
  co2: { label: 'CO₂', short: 'CO₂', unit: 'ppm', digits: 0, bands: [800, 1000] },
  temperature: { label: 'Температура', short: 'Темп.', unit: '°C', digits: 1, bands: null },
  humidity: { label: 'Влажность', short: 'Влажн.', unit: '%', digits: 1, bands: null },
  pm25: { label: 'PM2.5', short: 'PM2.5', unit: 'мкг/м³', digits: 0, bands: [15, 35] },
  pm10: { label: 'PM10', short: 'PM10', unit: 'мкг/м³', digits: 0, bands: [45, 100] },
  battery: { label: 'Батарея', short: 'Бат.', unit: '%', digits: 0, bands: null },
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

export function quality(metric: SensorMetric, value: number): Quality {
  const bands = METRIC_INFO[metric].bands
  if (bands === null) return 'neutral'
  if (value > bands[1]) return 'poor'
  if (value > bands[0]) return 'fair'
  return 'good'
}

/** Подпись для селектов: «CO₂, ppm». */
export function metricOption(metric: SensorMetric): string {
  return `${METRIC_INFO[metric].label}, ${METRIC_INFO[metric].unit}`
}
