import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { t } from '../i18n'
import type { LangCode, Role, BrandingConfig } from '../types'

interface Props {
  lang: LangCode
  role: Role
  onContinue: () => void
  onBack: () => void
  branding?: BrandingConfig
}

export default function InstructionsPage({ lang, role, onContinue, onBack, branding }: Props) {
  const titleKey = `instructions_${role}_title` as Parameters<typeof t>[0]
  const textKey = `instructions_${role}_text` as Parameters<typeof t>[0]
  // Custom instructions text is the WHOLE page (title + body), authored in
  // Markdown; when set it replaces the default title + body entirely.
  const custom = branding?.instructions_text

  return (
    <div className="max-w-4xl mx-auto mt-8 p-6">
      <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
        <div className="flex justify-center mb-4">
          <img src={branding?.logo_url || '/uni-logo.png'} alt="UNI Global Union" className="h-[7.5rem]" />
        </div>
        {custom ? (
          <div className="prose prose-sm max-w-none prose-headings:text-gray-800 prose-p:text-gray-600 prose-li:text-gray-600 prose-strong:text-gray-800 mb-6">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{custom}</ReactMarkdown>
          </div>
        ) : (
          <>
            <h2 className="text-xl font-semibold text-gray-800 mb-4">
              {t(titleKey, lang)}
            </h2>
            <div className="text-sm text-gray-600 leading-relaxed whitespace-pre-line mb-6">
              {t(textKey, lang)}
            </div>
          </>
        )}
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs text-amber-800 mb-4">
          {t('instructions_no_reload', lang)}
        </div>
        <button
          onClick={onContinue}
          className="w-full bg-uni-blue text-white rounded-lg px-4 py-2.5 font-medium transition-colors hover:opacity-90"
        >
          {t('instructions_continue', lang)}
        </button>
        <button
          onClick={onBack}
          className="w-full text-gray-500 text-sm hover:text-gray-700 mt-2"
        >
          &larr; {t('nav_back', lang)}
        </button>
      </div>
    </div>
  )
}
