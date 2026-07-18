import { LANGUAGES } from '../i18n'
import type { LangCode, BrandingConfig } from '../types'

interface Props {
  onSelect: (lang: LangCode) => void
  branding?: BrandingConfig
  languages?: LangCode[]
}

export default function LanguageSelector({ onSelect, branding, languages }: Props) {
  // Show only the configured subset (empty/undefined = all), always sorted
  // alphabetically by English name (REFACTOR §0.2).
  const shown = (languages && languages.length > 0
    ? LANGUAGES.filter(l => languages.includes(l.code))
    : LANGUAGES
  ).slice().sort((a, b) => a.name.localeCompare(b.name))

  return (
    <div className="max-w-4xl mx-auto mt-8 p-6">
      <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
        <div className="flex justify-center mb-4">
          <img src={branding?.logo_url || '/uni-logo.png'} alt="UNI Global Union" className="h-28" />
        </div>
        <h2 className="text-xl font-semibold text-gray-800 mb-1 text-center">Select your language</h2>
        <p className="text-sm text-gray-400 mb-6 text-center">Choose your preferred language to continue</p>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {shown.map(lang => (
            <button
              key={lang.code}
              onClick={() => onSelect(lang.code)}
              className="flex flex-col items-center justify-center px-3 py-4 rounded-lg border border-gray-200 hover:border-uni-blue hover:bg-blue-50 transition-colors"
            >
              <span className="text-sm font-medium text-gray-800">{lang.nativeName}</span>
              <span className="text-xs text-gray-400 mt-0.5">{lang.name}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
