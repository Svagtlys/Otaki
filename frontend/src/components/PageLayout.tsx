import React from 'react'

interface PageLayoutProps {
  title: React.ReactNode
  headerActions?: React.ReactNode
  actionBar?: React.ReactNode
  children: React.ReactNode
}

export default function PageLayout({
  title,
  headerActions,
  actionBar,
  children,
}: PageLayoutProps) {
  return (
    <div style={{ padding: '28px 32px' }}>
      {/* Header row: [title] [right-aligned actions] */}
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: actionBar ? 16 : 24 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: 'var(--text)', flexShrink: 0 }}>{title}</h1>
        {headerActions && (
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
            {headerActions}
          </div>
        )}
      </div>

      {/* Action bar under title */}
      {actionBar && (
        <div style={{ display: 'flex', gap: 4, marginBottom: 24 }}>
          {actionBar}
        </div>
      )}

      {children}
    </div>
  )
}
