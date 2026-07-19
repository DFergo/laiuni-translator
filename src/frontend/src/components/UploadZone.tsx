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
  files, onFiles, formats, multiple = false, max = 1,
}: {
  files: File[]
  onFiles: (f: File[]) => void
  formats: FormatTier[]
  multiple?: boolean
  max?: number
}) {
  const t = useT()
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  const add = (list: FileList | null) => {
    if (!list || list.length === 0) return
    const incoming = Array.from(list)
    onFiles(multiple ? [...files, ...incoming].slice(0, max) : incoming.slice(0, 1))
  }
  const remove = (idx: number) => onFiles(files.filter((_, i) => i !== idx))

  return (
    <div>
      <div
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); add(e.dataTransfer.files) }}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && inputRef.current?.click()}
        className={`cursor-pointer rounded-md border-2 border-dashed px-4 py-8 text-center text-sm transition ${
          dragging ? 'border-accent bg-bg' : 'border-border'
        }`}
      >
        <span className="text-text-secondary">{t('upload.drop')}</span>
      </div>
      <input
        ref={inputRef}
        type="file"
        multiple={multiple}
        className="hidden"
        onChange={(e) => { add(e.target.files); e.target.value = '' }}
      />
      {files.map((f, i) => {
        const info = tierInfo(f.name, formats)
        return (
          <div key={i} className="mt-3">
            <div className="flex items-center justify-between gap-2">
              <span className="truncate text-sm font-medium text-text-primary">{f.name}</span>
              <button type="button" onClick={() => remove(i)} className="text-[0.8125rem] text-text-secondary hover:underline">✕</button>
            </div>
            <div className="mt-1"><Banner kind={info.kind}>{t(info.messageKey, { ext: info.ext || '—' })}</Banner></div>
          </div>
        )
      })}
    </div>
  )
}
