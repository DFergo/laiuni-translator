// LAIUNI Translator — user portal types (Sprint 6).

export interface Language {
  code: string
  name: string
}

export interface FormatTier {
  ext: string
  tier: 'tier1' | 'tier2' | 'tier3'
}

export interface LanguagesResponse {
  languages: Language[]
  formats: FormatTier[]
}

export type JobStatus =
  | 'pending' | 'queued' | 'scheduled' | 'running'
  | 'done' | 'failed' | 'rejected' | 'error'

export interface JobProgress {
  total: number
  done: number
  langs_done: string[]
}

export interface JobState {
  ref: string
  job_id?: string
  status: JobStatus
  progress?: JobProgress
  estimate_s?: number
  run_at?: number
  langs_done?: string[]
  error?: string
  warning?: string
}

export interface Branding {
  app_title?: string
  logo_url?: string
  colors?: Record<string, string>
}

export type Step = 'auth' | 'portal' | 'status' | 'done'
