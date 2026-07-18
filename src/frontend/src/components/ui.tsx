import React from 'react'

export function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="w-full max-w-flow rounded-lg border border-border bg-surface p-6 shadow-sm">
      {children}
    </div>
  )
}

type Variant = 'accent' | 'primary' | 'ghost'

export function Button({
  children, onClick, disabled, variant = 'accent', type = 'button',
}: {
  children: React.ReactNode
  onClick?: () => void
  disabled?: boolean
  variant?: Variant
  type?: 'button' | 'submit'
}) {
  const base =
    'w-full rounded-md px-4 py-2.5 text-sm font-medium transition disabled:opacity-50 disabled:cursor-not-allowed'
  const v: Record<Variant, string> = {
    accent: 'bg-accent text-white hover:brightness-95',
    primary: 'bg-primary text-white hover:brightness-110',
    ghost: 'border border-border text-text-primary hover:bg-bg',
  }
  return (
    <button type={type} onClick={onClick} disabled={disabled} className={`${base} ${v[variant]}`}>
      {children}
    </button>
  )
}

export function Field({
  label, children, hint,
}: {
  label: string
  children: React.ReactNode
  hint?: string
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-[0.8125rem] font-medium text-text-secondary">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[0.8125rem] text-text-secondary">{hint}</span>}
    </label>
  )
}

export const inputClass =
  'w-full rounded-md border border-border bg-surface px-3 py-2 text-sm outline-none focus:border-primary'
