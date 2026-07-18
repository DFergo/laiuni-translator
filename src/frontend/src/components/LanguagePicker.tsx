import type { Language } from '../types'
import { useT } from '../i18n'
import { Field, inputClass } from './ui'

export function LanguagePicker({
  languages, source, onSource, targets, onToggleTarget,
}: {
  languages: Language[]
  source: string
  onSource: (code: string) => void
  targets: Set<string>
  onToggleTarget: (code: string) => void
}) {
  const t = useT()
  return (
    <div className="space-y-4">
      <Field label={t('lang.source')}>
        <select className={inputClass} value={source} onChange={(e) => onSource(e.target.value)}>
          {languages.map((l) => (
            <option key={l.code} value={l.code}>{l.name}</option>
          ))}
        </select>
      </Field>

      <Field label={t('lang.targets', { n: targets.size })}>
        <div className="flex flex-wrap gap-2">
          {languages
            .filter((l) => l.code !== source)
            .map((l) => {
              const on = targets.has(l.code)
              return (
                <button
                  key={l.code}
                  type="button"
                  aria-pressed={on}
                  onClick={() => onToggleTarget(l.code)}
                  className={`rounded-sm border px-3 py-1.5 text-[0.8125rem] transition ${
                    on
                      ? 'border-accent bg-accent text-white'
                      : 'border-border bg-surface text-text-primary hover:border-accent'
                  }`}
                >
                  {l.name}
                </button>
              )
            })}
        </div>
      </Field>
    </div>
  )
}
