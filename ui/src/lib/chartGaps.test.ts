import { describe, expect, it } from 'vitest'

import { withGaps } from './chartGaps'

describe('withGaps', () => {
  it('разрывает линию через пропущенные измерения, сохраняя одинаковые значения', () => {
    expect(withGaps([{ ts: 0, value: 500 }, { ts: 30, value: 500 }, { ts: 601, value: 600 }], 300))
      .toEqual([{ ts: 0, value: 500 }, { ts: 30, value: 500 }, { ts: 330 }, { ts: 601, value: 600 }])
  })
  it('пропущенный час разрывает все три агрегата', () => {
    const first = { ts: 0, min: 1, max: 2, avg: 1.5 }
    const second = { ts: 7200, min: 2, max: 3, avg: 2.5 }
    expect(withGaps([first, second], 3600)).toEqual([first, { ts: 3600 }, second])
    expect(withGaps([], 300)).toEqual([])
  })
})
