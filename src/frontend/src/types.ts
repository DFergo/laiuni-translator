// LAIUNI Translator — user portal types (Sprint 6).

export interface Language {
  code: string
  name: string
}

export interface FormatTier {
  ext: string
  tier: 'tier1' | 'tier2' | 'tier3'
}

// Accepted formats are a fixed product constant (mirrors backend
// core/config.py `supported_formats`) — the portal owns them, so file
// acceptance never depends on the backend having pushed the catalogue.
export const SUPPORTED_FORMATS: FormatTier[] = [
  { ext: '.txt', tier: 'tier1' },
  { ext: '.md', tier: 'tier1' },
  { ext: '.markdown', tier: 'tier1' },
  { ext: '.docx', tier: 'tier2' },
  { ext: '.rtf', tier: 'tier2' },
  { ext: '.pptx', tier: 'tier3' },
]

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
