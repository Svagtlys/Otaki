export function formatRelative(isoString: string | null): string {
  if (!isoString) return '—'
  const diffMs = new Date(isoString).getTime() - Date.now()
  if (diffMs <= 0) return 'overdue'
  const diffHours = diffMs / (1000 * 60 * 60)
  if (diffHours < 1) return 'in < 1 hour'
  if (diffHours < 24) return `in ${Math.round(diffHours)} hours`
  return `in ${Math.round(diffHours / 24)} days`
}
