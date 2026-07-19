import { useState } from 'react'
import type { Language, FormatTier } from '../types'
import type { SubmitOpts, SchedulingPolicy } from '../api'
import { useT } from '../i18n'
import { Button, Card, Field, inputClass } from './ui'
import { UploadZone, tierInfo } from './UploadZone'
import { LanguagePicker } from './LanguagePicker'

export function PortalForm({
  languages, formats, busy, scheduling, onSubmit,
}: {
  languages: Language[]
  formats: FormatTier[]
  busy: boolean
  scheduling: SchedulingPolicy | null
  onSubmit: (o: SubmitOpts) => void
}) {
  const t = useT()
  // Scheduling policy (§12.6): one mode drives the buttons. 'both' shows the
  // toggle (default scheduled); 'immediate'/'scheduled' force that mode with no
  // toggle — so the UI never hides a policy the user can't see.
  const policy = scheduling?.mode ?? 'both'
  const mayChoose = policy === 'both'
  const [file, setFile] = useState<File | null>(null)
  const [source, setSource] = useState('en')
  const [targets, setTargets] = useState<Set<string>>(new Set())
  const [glossary, setGlossary] = useState('')
  const [showGlossary, setShowGlossary] = useState(false)
  const [mode, setMode] = useState<'immediate' | 'scheduled'>(policy === 'immediate' ? 'immediate' : 'scheduled')
  // Per-job document options (§13.2) — shown only for the relevant format.
  const [translateFootnotes, setTranslateFootnotes] = useState(true)   // docx, default ON
  const [translateSpeakerNotes, setTranslateSpeakerNotes] = useState(false)  // pptx, default OFF

  const ext = file ? file.name.slice(file.name.lastIndexOf('.')).toLowerCase() : ''
  const blocked = file ? tierInfo(file.name, formats).blocked : false
  const canSubmit = !!file && !blocked && targets.size > 0 && !busy

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
        <UploadZone file={file} onFile={setFile} formats={formats} />

        {ext === '.docx' && (
          <label className="flex items-center gap-2 text-sm text-text-primary">
            <input type="checkbox" checked={translateFootnotes} onChange={(e) => setTranslateFootnotes(e.target.checked)}
              className="h-4 w-4 rounded border-border accent-accent" />
            {t('opt.footnotes')}
          </label>
        )}
        {ext === '.pptx' && (
          <label className="flex items-center gap-2 text-sm text-text-primary">
            <input type="checkbox" checked={translateSpeakerNotes} onChange={(e) => setTranslateSpeakerNotes(e.target.checked)}
              className="h-4 w-4 rounded border-border accent-accent" />
            {t('opt.speakerNotes')}
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
            file && onSubmit({
              file, sourceLang: source, targetLangs: [...targets], glossary, mode,
              options: { translate_footnotes: translateFootnotes, translate_speaker_notes: translateSpeakerNotes },
            })
          }
        >
          {busy ? t('portal.submitting') : t('portal.start')}
        </Button>
      </div>
    </Card>
  )
}
