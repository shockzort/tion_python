import { describe, expect, it } from 'vitest'

import { cronFromPreset, describeCron, presetFromCron } from './cron'

describe('cronFromPreset', () => {
  it('ежедневно', () => {
    expect(cronFromPreset({ time: '23:00', days: [] })).toBe('0 23 * * *')
  })

  it('будни', () => {
    expect(cronFromPreset({ time: '07:30', days: [1, 2, 3, 4, 5] })).toBe(
      '30 7 * * 1,2,3,4,5',
    )
  })

  it('воскресенье — cron 0', () => {
    expect(cronFromPreset({ time: '09:05', days: [7, 6] })).toBe('5 9 * * 0,6')
  })

  it('все 7 дней схлопываются в *', () => {
    expect(
      cronFromPreset({ time: '12:00', days: [1, 2, 3, 4, 5, 6, 7] }),
    ).toBe('0 12 * * *')
  })
})

describe('presetFromCron', () => {
  it('обратен конструктору', () => {
    expect(presetFromCron('30 7 * * 1,2,3,4,5')).toEqual({
      time: '07:30',
      days: [1, 2, 3, 4, 5],
    })
    expect(presetFromCron('0 23 * * *')).toEqual({ time: '23:00', days: [] })
    expect(presetFromCron('5 9 * * 0,6')).toEqual({ time: '09:05', days: [6, 7] })
  })

  it('cron сложнее пресета не разбирается', () => {
    expect(presetFromCron('*/5 8-22 * * *')).toBeNull()
    expect(presetFromCron('0 23 1 * *')).toBeNull()
    expect(presetFromCron('0 23 * 6 *')).toBeNull()
    expect(presetFromCron('мусор')).toBeNull()
  })
})

describe('describeCron', () => {
  it('описывает пресет по-русски', () => {
    expect(describeCron('0 23 * * *')).toBe('23:00 · ежедневно')
    expect(describeCron('30 7 * * 1,5')).toBe('07:30 · пн, пт')
  })

  it('нераспознанный cron показывает как есть', () => {
    expect(describeCron('*/10 * * * *')).toBe('*/10 * * * *')
  })
})
