import { useState } from 'react'
import type { Language, FormatTier } from '../types'
import type { SchedulingPolicy } from '../api'
import { useT } from '../i18n'
import { Button, Card, Field, inputClass } from './ui'
import { UploadZone, tierInfo } from './UploadZone'
import { LanguagePicker } from './LanguagePicker'

export interface SharedOpts {
  sourceLang: string
  targetLangs: string[]
  glossary: string
  mode: 'immediate' | 'scheduled'
  options: Record<string, boolean>
}

export function PortalForm({
  languages, formats, busy, scheduling, onSubmit,
}: {
  languages: Language[]
  formats: FormatTier[]
  busy: boolean
  scheduling: SchedulingPolicy | null
  onSubmit: (files: File[], shared: SharedOpts) => void
}) {
  const t = useT()
  const policy = scheduling?.mode ?? 'both'
  const mayChoose = policy === 'both'
  const batchMax = scheduling?.batch_max ?? 5
  const [files, setFiles] = useState<File[]>([])
  const [multiple, setMultiple] = useState(false)
  const [source, setSource] = useState('en')
  const [targets, setTargets] = useState<Set<string>>(new Set())
  const [glossary, setGlossary] = useState('')
  const [showGlossary, setShowGlossary] = useState(false)
  const [mode, setMode] = useState<'immediate' | 'scheduled'>(policy === 'immediate' ? 'immediate' : 'scheduled')
  // Per-job document options (§13.2) — shown only for the relevant format(s) present.
  const [translateFootnotes, setTranslateFootnotes] = useState(true)   // docx, default ON
  const [translateSpeakerNotes, setTranslateSpeakerNotes] = useState(false)  // pptx, default OFF
  const [contextual, setContextual] = useState(true)   // docx/pptx, default ON

  const exts = files.map((f) => f.name.slice(f.name.lastIndexOf('.')).toLowerCase())
  const hasDocx = exts.includes('.docx')
  const hasPptx = exts.includes('.pptx')
  const hasStructured = hasDocx || hasPptx
  const anyBlocked = files.some((f) => tierInfo(f.name, formats).blocked)
  const canSubmit = files.length > 0 && !anyBlocked && targets.size > 0 && !busy

  function toggle(code: string) {
    setTargets((prev) => {
      const next = new Set(prev)
      next.has(code) ? next.delete(code) : next.add(code)
      return next
    })
  }

  return (
    <Card>
      <h1 className="mb-1 text-[1.5rem] font-semibold text-primary">{t('portal.title')}</h1>
      <p className="mb-5 text-sm text-text-secondary">{t('portal.intro', { n: languages.length })}</p>

      <div className="space-y-6">
        {batchMax > 1 && (
          <label className="flex items-center gap-2 text-sm text-text-primary">
            <input type="checkbox" checked={multiple}
              onChange={(e) => { setMultiple(e.target.checked); if (!e.target.checked) setFiles((f) => f.slice(0, 1)) }}
              className="h-4 w-4 rounded border-border accent-accent" />
            {t('portal.multiple', { n: batchMax })}
          </label>
        )}

        <UploadZone files={files} onFiles={setFiles} formats={formats} multiple={multiple} max={batchMax} />

        {hasDocx && (
          <label className="flex items-center gap-2 text-sm text-text-primary">
            <input type="checkbox" checked={translateFootnotes} onChange={(e) => setTranslateFootnotes(e.target.checked)}
              className="h-4 w-4 rounded border-border accent-accent" />
            {t('opt.footnotes')}
          </label>
        )}
        {hasPptx && (
          <label className="flex items-center gap-2 text-sm text-text-primary">
            <input type="checkbox" checked={translateSpeakerNotes} onChange={(e) => setTranslateSpeakerNotes(e.target.checked)}
              className="h-4 w-4 rounded border-border accent-accent" />
            {t('opt.speakerNotes')}
          </label>
        )}
        {hasStructured && (
          <label className="flex items-center gap-2 text-sm text-text-primary">
            <input type="checkbox" checked={contextual} onChange={(e) => setContextual(e.target.checked)}
              className="h-4 w-4 rounded border-border accent-accent" />
            {t('opt.contextual')}
          </label>
        )}

        <LanguagePicker
          languages={languages}
          source={source}
          onSource={(c) => { setSource(c); setTargets((p) => { const n = new Set(p); n.delete(c); return n }) }}
          targets={targets}
          onToggleTarget={toggle}
        />

        <div>
          <button
            type="button"
            className="text-[0.8125rem] font-medium text-text-secondary hover:underline"
            onClick={() => setShowGlossary((s) => !s)}
          >
            {showGlossary ? t('portal.glossaryHide') : t('portal.glossaryShow')}
          </button>
          {showGlossary && (
            <div className="mt-2">
              <Field label={t('portal.glossary')} hint={t('portal.glossaryHint')}>
                <textarea
                  className={`${inputClass} h-24 resize-y`}
                  value={glossary}
                  onChange={(e) => setGlossary(e.target.value)}
                  placeholder={t('portal.glossaryPlaceholder')}
                />
              </Field>
            </div>
          )}
        </div>

        {mayChoose && (
          <Field label={t('portal.when')}>
            <div className="flex gap-2">
              {(['scheduled', 'immediate'] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  aria-pressed={mode === m}
                  onClick={() => setMode(m)}
                  className={`flex-1 rounded-md border px-3 py-2 text-sm transition ${
                    mode === m ? 'border-primary bg-primary text-white' : 'border-border bg-surface text-text-primary'
                  }`}
                >
                  {m === 'scheduled' ? t('portal.scheduled') : t('portal.immediate')}
                </button>
              ))}
            </div>
          </Field>
        )}
        {mode === 'scheduled' && (
          <p className="-mt-3 text-[0.8125rem] text-text-secondary">
            {t('portal.scheduleNote')}
          </p>
        )}

        <Button
          variant="accent"
          disabled={!canSubmit}
          onClick={() =>
            files.length > 0 && onSubmit(files, {
              sourceLang: source, targetLangs: [...targets], glossary, mode,
              options: { translate_footnotes: translateFootnotes, translate_speaker_notes: translateSpeakerNotes, contextual },
            })
          }
        >
          {busy ? t('portal.submitting') : t('portal.start')}
        </Button>
      </div>
    </Card>
  )
}
