import React from 'react'

type Kind = 'danger' | 'info' | 'success'

export function Banner({ kind, children }: { kind: Kind; children: React.ReactNode }) {
  const styles: Record<Kind, string> = {
    danger: 'border-danger text-danger',
    info: 'border-border text-text-secondary',
    success: 'border-secondary text-secondary',
  }
  return (
    <div className={`rounded-md border bg-surface px-4 py-3 text-sm ${styles[kind]}`} role="status">
      {children}
    </div>
  )
}
