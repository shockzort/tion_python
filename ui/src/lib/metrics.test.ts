import { describe, expect, it } from 'vitest'

import { metricColor } from './metrics'

describe('metricColor', () => {
  it('за краями шкалы — крайние цвета', () => {
    expect(metricColor('co2', 400)).toBe('#34d399')
    expect(metricColor('co2', 5000)).toBe('#f87171')
  })

  it('между опорными точками — плавный переход', () => {
    expect(metricColor('co2', 1000)).toBe('#facc15')
    // середина 700→1000: между зелёным и жёлтым
    expect(metricColor('co2', 850)).toBe('#97d057')
  })

  it('температура: холод синий, комфорт зелёный, жара красная', () => {
    expect(metricColor('temperature', 16)).toBe('#60a5fa')
    expect(metricColor('temperature', 23)).toBe('#34d399')
    expect(metricColor('temperature', 31)).toBe('#f87171')
  })

  it('влажность: сухо оранжевый, норма зелёный, сыро синий', () => {
    expect(metricColor('humidity', 15)).toBe('#fb923c')
    expect(metricColor('humidity', 50)).toBe('#34d399')
    expect(metricColor('humidity', 80)).toBe('#60a5fa')
  })

  it('батарея: разряд красный, полный заряд зелёный', () => {
    expect(metricColor('battery', 5)).toBe('#f87171')
    expect(metricColor('battery', 100)).toBe('#34d399')
  })
})
