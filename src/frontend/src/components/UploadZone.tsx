import { useRef, useState } from 'react'
import type { FormatTier } from '../types'
import { useT, type Key } from '../i18n'
import { Banner } from './Banner'

export interface TierInfo {
  tier: 'tier1' | 'tier2' | 'tier3' | null
  ext: string
  messageKey: Key
  kind: 'info' | 'danger'
  blocked: boolean
}

export function tierInfo(filename: string, formats: FormatTier[]): TierInfo {
  const dot = filename.lastIndexOf('.')
  const ext = dot >= 0 ? filename.slice(dot).toLowerCase() : ''
  const match = formats.find((f) => f.ext === ext)
  switch (match?.tier) {
    case 'tier1':
      return { tier: 'tier1', ext, messageKey: 'upload.tier1', kind: 'info', blocked: false }
    case 'tier2':
      return { tier: 'tier2', ext, messageKey: 'upload.tier2', kind: 'info', blocked: false }
    case 'tier3':
      return { tier: 'tier3', ext, messageKey: 'upload.tier3', kind: 'danger', blocked: false }
    default:
      return { tier: null, ext, messageKey: 'upload.unsupported', kind: 'danger', blocked: true }
  }
}

export function UploadZone({
  file, onFile, formats,
}: {
  file: File | null
  onFile: (f: File | null) => void
  formats: FormatTier[]
}) {
  const t = useT()
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const info = file ? tierInfo(file.name, formats) : null

  return (
    <div>
      <div
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault(); setDragging(false)
          if (e.dataTransfer.files[0]) onFile(e.dataTransfer.files[0])
        }}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && inputRef.current?.click()}
        className={`cursor-pointer rounded-md border-2 border-dashed px-4 py-8 text-center text-sm transition ${
          dragging ? 'border-accent bg-bg' : 'border-border'
        }`}
      >
        {file ? (
          <span className="font-medium text-text-primary">{file.name}</span>
        ) : (
          <span className="text-text-secondary">{t('upload.drop')}</span>
        )}
      </div>
      <input
        ref={inputRef}
        type="file"
        className="hidden"
        onChange={(e) => onFile(e.target.files?.[0] ?? null)}
      />
      {info && (
        <div className="mt-3">
          <Banner kind={info.kind}>{t(info.messageKey, { ext: info.ext || '—' })}</Banner>
        </div>
      )}
    </div>
  )
}
