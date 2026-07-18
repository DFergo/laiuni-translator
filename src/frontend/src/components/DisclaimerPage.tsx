import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { t } from '../i18n'
import type { LangCode, BrandingConfig } from '../types'

interface Props {
  lang: LangCode
  onAccept: () => void
  onBack: () => void
  branding?: BrandingConfig
  dataProtectionEmail?: string
}

export default function DisclaimerPage({ lang, onAccept, onBack, branding, dataProtectionEmail }: Props) {
  const email = dataProtectionEmail || 'dataprotection@uniglobalunion.org'
  // Custom disclaimer text is the WHOLE page (headings + body), authored in
  // Markdown; when set it replaces the default sections entirely.
  const custom = (branding?.disclaimer_text || '').replace('[DATA_PROTECTION_EMAIL]', email)

  return (
    <div className="max-w-4xl mx-auto mt-8 p-6">
      <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6 max-h-[80vh] overflow-y-auto">
        <div className="flex justify-center mb-4">
          <img src={branding?.logo_url || '/uni-logo.png'} alt="UNI Global Union" className="h-[7.5rem]" />
        </div>

        {custom ? (
          <div className="prose prose-sm max-w-none prose-headings:text-gray-800 prose-p:text-gray-600 prose-li:text-gray-600 prose-strong:text-gray-800 mb-6">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{custom}</ReactMarkdown>
          </div>
        ) : (
          <>
            {/* Section 1: What Is This Tool? */}
            <h2 className="text-xl font-semibold text-gray-800 mb-3">{t('disclaimer_what_heading', lang)}</h2>
            <div className="text-sm text-gray-600 leading-relaxed whitespace-pre-line mb-6">
              {t('disclaimer_what_body', lang)}
            </div>

            {/* Section 2: How Your Data Is Handled */}
            <h2 className="text-xl font-semibold text-gray-800 mb-3">{t('disclaimer_data_heading', lang)}</h2>
            <div className="text-sm text-gray-600 leading-relaxed whitespace-pre-line mb-6">
              {t('disclaimer_data_body', lang)}
            </div>

            {/* Section 3: Disclaimer (legal) */}
            <h2 className="text-xl font-semibold text-gray-800 mb-3">{t('disclaimer_legal_heading', lang)}</h2>
            <div className="text-sm text-gray-600 leading-relaxed whitespace-pre-line mb-6">
              {t('disclaimer_legal_body', lang)}
            </div>
          </>
        )}

        {/* Fixed data-rights line (i18n, safely translated) — the email is
            substituted here so it never depends on the editable/LLM-translated text. */}
        <div className="text-sm text-gray-600 leading-relaxed whitespace-pre-line mb-6">
          {t('disclaimer_data_rights', lang).replace('[DATA_PROTECTION_EMAIL]', email)}
        </div>

        <button
          onClick={onAccept}
          className="w-full bg-uni-blue text-white rounded-lg px-4 py-2.5 font-medium transition-colors hover:opacity-90"
        >
          {t('disclaimer_accept', lang)}
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
