/** Пустая точка разрывает линии Recharts при пропуске измерений. */
export function withGaps<T extends { ts: number }>(points: T[], maxGap: number): (T | { ts: number })[] {
  return points.flatMap((point, index) => {
    const previous = points[index - 1]
    return previous && point.ts - previous.ts > maxGap
      ? [{ ts: previous.ts + maxGap }, point]
      : [point]
  })
}
