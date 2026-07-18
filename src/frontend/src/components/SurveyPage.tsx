import { useState } from 'react'
import { t } from '../i18n'
import type { LangCode, Role, ConsultationMode, SurveyData, DeploymentConfig } from '../types'

interface Props {
  lang: LangCode
  config: DeploymentConfig
  role: Role
  onSubmit: (data: SurveyData) => void
  onBack: () => void
}

// Modes available per profile
const MODES_BY_ROLE: Record<Role, ConsultationMode[]> = {
  worker: [],        // No mode selection — single prompt
  representative: [], // No mode selection — single prompt
  organizer: ['documentation', 'interview', 'advisory', 'submit'],
  officer: ['documentation', 'interview', 'advisory', 'submit', 'training'],
}

export default function SurveyPage({ lang, config, role, onSubmit, onBack }: Props) {
  // Active modes: the configured subset for this profile, else the full wired set.
  const configuredModes = config.modes?.[role]
  const availableModes = (configuredModes && configuredModes.length > 0) ? configuredModes : MODES_BY_ROLE[role]
  // Hide the selector when a single mode is active (REFACTOR §0.2)
  const showMode = availableModes.length > 1

  const [mode, setMode] = useState<ConsultationMode>(availableModes[0] ?? 'documentation')
  const [name, setName] = useState('')
  const [position, setPosition] = useState('')
  const [union, setUnion] = useState('')
  const [email, setEmail] = useState('')
  const [company, setCompany] = useState('')
  const [countryRegion, setCountryRegion] = useState('')
  const [description, setDescription] = useState('')

  // Identity requirement is intrinsic to the profile (REFACTOR §0.3), not the
  // frontend: organizer/officer require it, worker/representative don't.
  const isOrganizerRole = role === 'organizer' || role === 'officer'

  // Worker/Rep: only company, country, description required. Identity optional.
  // Organizer/Officer: all required, except company optional in advisory/training
  const identityRequired = isOrganizerRole
  const companyRequired = mode !== 'advisory' && mode !== 'training'

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const data: SurveyData = {
      role,
      description,
      type: mode,
      ...(name && { name }),
      ...(position && { position }),
      ...(union && { union }),
      ...(email && { email }),
      ...(company && { company }),
      ...(countryRegion && { countryRegion }),
    }
    onSubmit(data)
  }

  return (
    <div className="max-w-4xl mx-auto mt-8 p-6">
      <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
        <h2 className="text-xl font-semibold text-gray-800 mb-6">{t('survey_title', lang)}</h2>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Mode select — organizer/officer only */}
          {showMode && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('survey_mode', lang)}</label>
              <div className={`grid gap-2 ${availableModes.length <= 3 ? 'grid-cols-3' : availableModes.length <= 4 ? 'grid-cols-2 sm:grid-cols-4' : 'grid-cols-2 sm:grid-cols-3'}`}>
                {availableModes.map(m => (
                  <button
                    key={m}
                    type="button"
                    onClick={() => setMode(m)}
                    className={`px-3 py-2.5 rounded-lg border text-sm font-medium transition-colors ${
                      mode === m
                        ? 'bg-uni-blue text-white border-uni-blue'
                        : 'border-gray-300 text-gray-700 hover:border-uni-blue hover:bg-blue-50'
                    }`}
                  >
                    {config.display_names?.modes?.[m] || t(`mode_${m}` as Parameters<typeof t>[0], lang)}
                  </button>
                ))}
              </div>
              <p className="mt-2 text-xs text-gray-500">
                {t(`mode_${mode}_desc` as Parameters<typeof t>[0], lang)}
              </p>
            </div>
          )}

          {/* Privacy note for worker/rep */}
          {!isOrganizerRole && (
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-xs text-gray-600">
              {t('survey_privacy_note', lang)}
            </div>
          )}

          {/* Name */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              {t('survey_name', lang)}{identityRequired && <span className="text-uni-red ml-0.5">*</span>}
            </label>
            <input type="text" value={name} onChange={e => setName(e.target.value)}
              required={identityRequired}
              className="w-full border border-gray-300 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none" />
          </div>

          {/* Position */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              {t('survey_position', lang)}{identityRequired && <span className="text-uni-red ml-0.5">*</span>}
            </label>
            <input type="text" value={position} onChange={e => setPosition(e.target.value)}
              required={identityRequired}
              className="w-full border border-gray-300 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none" />
          </div>

          {/* Union */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              {t('survey_union', lang)}{identityRequired && <span className="text-uni-red ml-0.5">*</span>}
            </label>
            <input type="text" value={union} onChange={e => setUnion(e.target.value)}
              required={identityRequired}
              className="w-full border border-gray-300 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none" />
          </div>

          {/* Email */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              {t('survey_email', lang)}{identityRequired && <span className="text-uni-red ml-0.5">*</span>}
            </label>
            <input type="email" value={email} onChange={e => setEmail(e.target.value)}
              required={identityRequired}
              className="w-full border border-gray-300 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none" />
          </div>

          {/* Company */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              {t('survey_company', lang)}{companyRequired && <span className="text-uni-red ml-0.5">*</span>}
            </label>
            <input type="text" value={company} onChange={e => setCompany(e.target.value)}
              required={companyRequired}
              className="w-full border border-gray-300 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none" />
          </div>

          {/* Country/Region */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              {t('survey_country', lang)}<span className="text-uni-red ml-0.5">*</span>
            </label>
            <input type="text" value={countryRegion} onChange={e => setCountryRegion(e.target.value)}
              required
              className="w-full border border-gray-300 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none" />
          </div>

          {/* Situation description */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              {t('survey_description', lang)}<span className="text-uni-red ml-0.5">*</span>
            </label>
            <textarea
              value={description}
              onChange={e => setDescription(e.target.value)}
              rows={4}
              className="w-full border border-gray-300 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none resize-none"
              required
            />
          </div>

          <button
            type="submit"
            className="w-full bg-uni-blue text-white rounded-lg px-4 py-2.5 font-medium transition-colors hover:opacity-90"
          >
            {t('survey_submit', lang)}
          </button>
          <button
            type="button"
            onClick={onBack}
            className="w-full text-gray-500 text-sm hover:text-gray-700 mt-2"
          >
            &larr; {t('nav_back', lang)}
          </button>
        </form>
      </div>
    </div>
  )
}
