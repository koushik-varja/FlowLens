export function formatMetric(value: unknown): string {
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(2)
  if (value === null || value === undefined) return '—'
  return String(value)
}
export function isImprovement(baseline: number, proposed: number): boolean { return proposed < baseline }
