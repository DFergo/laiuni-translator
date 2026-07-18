export type Phase = 'loading' | 'unconfigured' | 'language' | 'disclaimer' | 'session' | 'role_select' | 'auth' | 'instructions' | 'survey' | 'chat'

export type Role = 'worker' | 'representative' | 'organizer' | 'officer'

export type ConsultationMode = 'documentation' | 'interview' | 'advisory' | 'submit' | 'training'

export interface BrandingConfig {
  app_title?: string
  logo_url?: string
  custom?: boolean
  disclaimer_text?: string
  instructions_text?: string
}

export interface DeploymentConfig {
  role: string
  configured: boolean
  profiles: Role[]
  auth?: Partial<Record<Role, boolean>>
  languages?: LangCode[]
  modes?: Partial<Record<Role, ConsultationMode[]>>
  display_names?: {
    profiles?: Partial<Record<Role, string>>
    modes?: Partial<Record<ConsultationMode, string>>
  }
  session_resume_window_hours: number
  disclaimer_enabled: boolean
  auth_required: boolean
  data_protection_email?: string
  branding?: BrandingConfig
}

export interface SurveyData {
  role: Role
  type: ConsultationMode
  name?: string
  position?: string
  union?: string
  email?: string
  company?: string
  countryRegion?: string
  description?: string
}

export interface RecoveryData {
  survey: SurveyData
  language: LangCode
  role: Role
  mode: ConsultationMode
  message_count: number
  status?: string
  recovery_type: 'full' | 'summary'
  messages?: { role: 'user' | 'assistant'; content: string }[]
  summary?: string
}

export type LangCode =
  | 'en' | 'zh' | 'hi' | 'es' | 'ar' | 'fr'
  | 'bn' | 'pt' | 'ru' | 'id' | 'de' | 'mr'
  | 'ja' | 'te' | 'tr' | 'ta' | 'vi' | 'ko'
  | 'ur' | 'th' | 'it' | 'pl' | 'nl' | 'el'
  | 'uk' | 'ro' | 'hr' | 'xh' | 'sw' | 'hu'
  | 'sv'
