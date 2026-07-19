// LAIUNI Translator — portal UI strings, hardcoded i18n in the 17 languages
// (Sprint 12 / ADR-015). The portal is not customised beyond branding, so the
// UI is not auto-translated: strings live here. The app language comes from the
// frontend config (global default + per-frontend override); English is the
// fallback for any missing key.

export type Lang =
  | 'en' | 'ar' | 'de' | 'es' | 'fr' | 'hi' | 'hr' | 'id' | 'it'
  | 'ja' | 'ne' | 'nl' | 'pl' | 'pt' | 'sv' | 'th' | 'ur'

export type Key =
  | 'auth.title' | 'auth.intro' | 'auth.email' | 'auth.emailPlaceholder'
  | 'auth.sendCode' | 'auth.sending' | 'auth.codeSent' | 'auth.code'
  | 'auth.verify' | 'auth.verifying' | 'auth.differentEmail'
  | 'auth.errServer' | 'auth.errCode' | 'auth.errNotAuthorized'
  | 'portal.title' | 'portal.intro' | 'portal.glossaryShow' | 'portal.glossaryHide'
  | 'portal.glossary' | 'portal.glossaryHint' | 'portal.glossaryPlaceholder'
  | 'portal.when' | 'portal.scheduled' | 'portal.immediate' | 'portal.scheduleNote'
  | 'portal.start' | 'portal.submitting' | 'portal.errSubmit' | 'portal.errRejected' | 'portal.multiple'
  | 'upload.drop' | 'upload.tier1' | 'upload.tier2' | 'upload.tier3' | 'upload.unsupported'
  | 'lang.source' | 'lang.targets'
  | 'opt.footnotes' | 'opt.speakerNotes' | 'opt.contextual'
  | 'status.title' | 'status.intro' | 'status.estimated' | 'status.progress'
  | 'status.scheduledAt' | 'status.failed'
  | 'status.queued' | 'status.scheduledLabel' | 'status.running' | 'status.done' | 'status.pending'
  | 'done.title' | 'done.intro' | 'done.download' | 'done.preparing'
  | 'done.another' | 'done.errExpired'
  | 'footer'

type Dict = Record<Key, string>

const en: Dict = {
  'auth.title': 'Sign in',
  'auth.intro': 'Access is limited to approved addresses. Enter your email to receive a one-time code.',
  'auth.email': 'Email',
  'auth.emailPlaceholder': 'you@organization.org',
  'auth.sendCode': 'Send code',
  'auth.sending': 'Sending…',
  'auth.codeSent': 'If your address is approved, a 6-digit code is on its way. Check your email.',
  'auth.code': 'Verification code',
  'auth.verify': 'Verify',
  'auth.verifying': 'Verifying…',
  'auth.differentEmail': 'Use a different email',
  'auth.errServer': 'Could not reach the server. Please try again.',
  'auth.errCode': 'That code is invalid or has expired.',
  'auth.errNotAuthorized': 'This email is not authorized to sign in.',
  'portal.title': 'Translate a document',
  'portal.intro': 'One file, one or more of {n} languages. Results are emailed to you.',
  'portal.glossaryShow': '+ Add a glossary (optional)',
  'portal.glossaryHide': '– Hide glossary',
  'portal.glossary': 'Glossary',
  'portal.glossaryHint': 'One term per line, e.g. collective bargaining -> negociación colectiva',
  'portal.glossaryPlaceholder': 'source term -> preferred translation',
  'portal.when': 'When to run',
  'portal.scheduled': 'Scheduled (overnight)',
  'portal.immediate': 'Immediate',
  'portal.scheduleNote': 'Scheduled jobs run overnight to keep the service responsive during the day.',
  'portal.start': 'Start translation',
  'portal.submitting': 'Submitting…',
  'portal.errSubmit': 'Submission failed. Please try again.',
  'portal.errRejected': 'That file could not be accepted.',
  'portal.multiple': 'Translate several documents at once (up to {n})',
  'upload.drop': 'Drop a document here, or click to choose one file.',
  'upload.tier1': 'Plain text — recommended for the cleanest result.',
  'upload.tier2': 'Word / RTF — supported; minor formatting shifts are possible.',
  'upload.tier3': 'PowerPoint — experimental; recomposition may fail. Review the output.',
  'upload.unsupported': 'Unsupported format {ext}. Try .txt or .md.',
  'lang.source': 'Source language',
  'lang.targets': 'Target languages ({n} selected)',
  'opt.footnotes': 'Translate footnotes and endnotes',
  'opt.speakerNotes': 'Translate speaker notes',
  'opt.contextual': 'Read the document first for better context',
  'status.title': 'Your translation',
  'status.intro': 'You can leave this page — the result is emailed when ready.',
  'status.estimated': 'Estimated {t}',
  'status.progress': '{done} of {total} languages',
  'status.scheduledAt': 'Scheduled to run at {time}.',
  'status.failed': 'The translation failed. Please try again or contact your administrator.',
  'status.queued': 'Queued',
  'status.scheduledLabel': 'Scheduled',
  'status.running': 'Translating…',
  'status.done': 'Done',
  'status.pending': 'Submitting…',
  'done.title': 'Translation ready',
  'done.intro': 'We’ve emailed you the original and all translations. You can also download them here while they’re available.',
  'done.download': 'Download all (.zip)',
  'done.preparing': 'Preparing…',
  'done.another': 'Translate another document',
  'done.errExpired': 'This download is no longer available (it may have expired).',
  'footer': '© 2026 UNI Global Union',
}

// Non-English dictionaries (Sprint 12). Any missing key falls back to English.
import { LOCALES } from './locales'

const DICTS: Partial<Record<Lang, Partial<Dict>>> = { en, ...LOCALES }

export type TFn = (key: Key, vars?: Record<string, string | number>) => string

export function translator(lang: Lang): TFn {
  const dict = DICTS[lang] || {}
  return (key: Key, vars?: Record<string, string | number>): string => {
    let s = (dict[key] ?? en[key] ?? key) as string
    if (vars) for (const [k, v] of Object.entries(vars)) s = s.replace(`{${k}}`, String(v))
    return s
  }
}

export const LANGS_RTL: Lang[] = ['ar', 'ur']

import { createContext, useContext } from 'react'
export const TContext = createContext<TFn>(translator('en'))
export const useT = (): TFn => useContext(TContext)
