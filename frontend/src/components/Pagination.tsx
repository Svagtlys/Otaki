interface PaginationProps {
  page: number
  total: number
  perPage: number
  onChange: (p: number) => void
}

export default function Pagination({ page, total, perPage, onChange }: PaginationProps) {
  const totalPages = Math.max(1, Math.ceil(total / perPage))
  if (totalPages <= 1) return null

  const pages: (number | '…')[] = []
  if (totalPages <= 7) {
    for (let i = 1; i <= totalPages; i++) pages.push(i)
  } else {
    pages.push(1)
    if (page > 3) pages.push('…')
    for (let i = Math.max(2, page - 1); i <= Math.min(totalPages - 1, page + 1); i++) pages.push(i)
    if (page < totalPages - 2) pages.push('…')
    pages.push(totalPages)
  }

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
      <button className="btn" onClick={() => onChange(page - 1)} disabled={page === 1}
        style={{ opacity: page === 1 ? 0.4 : 1 }}><i className="bx bx-chevron-left" /> Prev</button>
      {pages.map((p, i) =>
        p === '…'
          ? <span key={`e${i}`} style={{ color: 'var(--text-3)', padding: '0 4px' }}>…</span>
          : <button
              key={p}
              className={`btn${p === page ? ' primary' : ''}`}
              onClick={() => onChange(p as number)}
              style={{ minWidth: 36 }}
            >{p}</button>
      )}
      <button className="btn" onClick={() => onChange(page + 1)} disabled={page === totalPages}
        style={{ opacity: page === totalPages ? 0.4 : 1 }}>Next <i className="bx bx-chevron-right" /></button>
    </div>
  )
}
