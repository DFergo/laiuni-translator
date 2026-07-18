import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { t } from '../i18n'
import type { LangCode, SurveyData, RecoveryData } from '../types'

interface Message {
  role: 'user' | 'assistant'
  content: string
  isSummary?: boolean
  // Sprint 16: filenames "shipped" with this user turn (chips)
  attachments?: string[]
}

// Sprint 16: attachment chip state
type AttachmentStatus = 'uploading' | 'processing' | 'ready' | 'error'
interface Attachment {
  id: string         // local-only React key
  filename: string   // canonical filename used by backend
  status: AttachmentStatus
  errorMsg?: string
}

interface Props {
  lang: LangCode
  sessionToken: string
  survey: SurveyData
  recoveryData?: RecoveryData | null
}

export default function ChatShell({ lang, sessionToken, survey, recoveryData }: Props) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [streamingText, setStreamingText] = useState('')
  const [queuePosition, setQueuePosition] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [sessionEnded, setSessionEnded] = useState(recoveryData?.status === 'completed')
  const [showEndConfirm, setShowEndConfirm] = useState(false)
  // Sprint 16: chip-based attachment flow. The legacy uploadStatus banner
  // is gone; per-chip status is the source of truth.
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [isDragging, setIsDragging] = useState(false)
  const dragCounter = useRef(0)
  const chatEndRef = useRef<HTMLDivElement>(null)
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const isFirstMessage = useRef(!recoveryData)  // Not first if recovering
  const hasSentInitial = useRef(!!recoveryData)  // Don't auto-send on recovery
  const eventSourceRef = useRef<EventSource | null>(null)
  const userScrolledUp = useRef(false)

  // Auto-scroll only if user is at the bottom
  useEffect(() => {
    if (!userScrolledUp.current) {
      chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages, streamingText])

  // Auto-resize textarea up to 50vh, then internal scroll
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    const maxHeight = Math.floor(window.innerHeight * 0.5)
    const newHeight = Math.min(el.scrollHeight, maxHeight)
    el.style.height = newHeight + 'px'
    el.style.overflowY = el.scrollHeight > maxHeight ? 'auto' : 'hidden'
  }, [input])

  const handleScroll = () => {
    const el = scrollContainerRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80
    userScrolledUp.current = !atBottom
  }

  // Auto-send survey situation as first message on mount (new sessions only)
  useEffect(() => {
    if (hasSentInitial.current) return
    hasSentInitial.current = true
    const situation = survey.description || ''
    if (situation) {
      submitMessage(situation)
    }
  }, [])

  const submitMessage = async (text: string, shippedAttachments: string[] = []) => {
    userScrolledUp.current = false
    setError('')
    // Render the user bubble: text and/or attached filenames
    setMessages(prev => [...prev, {
      role: 'user',
      content: text,
      attachments: shippedAttachments.length > 0 ? shippedAttachments : undefined,
    }])
    setIsStreaming(true)
    setStreamingText('')
    setQueuePosition(null)

    // crypto.randomUUID() requires HTTPS — use fallback for plain HTTP
    const messageId = crypto.randomUUID?.()
      ?? `${Date.now()}-${Math.random().toString(36).slice(2, 11)}`
    const timestamp = new Date().toISOString()

    try {
      // Open SSE stream BEFORE posting — avoids race condition
      listenForResponse()

      // Submit message to sidecar queue
      const body: Record<string, unknown> = {
        session_token: sessionToken,
        content: text,
        message_id: messageId,
        timestamp,
        language: lang,
      }

      // Include survey data on first message
      if (isFirstMessage.current) {
        body.survey = survey
        isFirstMessage.current = false
      }

      // Sprint 16: ship the attached filenames with this turn
      if (shippedAttachments.length > 0) {
        body.attachments = shippedAttachments
      }

      await fetch('/internal/queue', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
    } catch {
      setIsStreaming(false)
      setError('Failed to send message. Please try again.')
    }
  }

  // Sprint 16: Send is allowed if we're not streaming, no chips are still
  // uploading or processing, AND (input has text OR at least one ready chip).
  const hasInFlightChip = attachments.some(a => a.status === 'uploading' || a.status === 'processing')
  const readyAttachments = attachments.filter(a => a.status === 'ready')
  const canSend = !isStreaming && !hasInFlightChip && (input.trim().length > 0 || readyAttachments.length > 0)

  const sendMessage = async () => {
    if (!canSend) return
    const text = input.trim()
    const shipped = readyAttachments.map(a => a.filename)
    setInput('')
    // Clear all chips — successful ones go with the turn, error ones get dropped silently
    setAttachments([])
    submitMessage(text, shipped)
  }

  const listenForResponse = (finalizing = false) => {
    // Close any existing connection
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
    }
    const eventSource = new EventSource(`/internal/stream/${sessionToken}`)
    eventSourceRef.current = eventSource
    let connectionFailures = 0
    let accumulated = ''

    eventSource.addEventListener('token', (e: MessageEvent) => {
      connectionFailures = 0
      accumulated += e.data
      setStreamingText(accumulated)
      setIsStreaming(true)
      setQueuePosition(null)
    })

    eventSource.addEventListener('queue_position', (e: MessageEvent) => {
      connectionFailures = 0
      setQueuePosition(parseInt(e.data, 10))
    })

    eventSource.addEventListener('done', (e: MessageEvent) => {
      eventSource.close()
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: e.data,
        isSummary: finalizing,
      }])
      setStreamingText('')
      setIsStreaming(false)
      setQueuePosition(null)
      if (finalizing) {
        setSessionEnded(true)
      }
    })

    // Sprint 16: chip flow — match the upload_processed event to a chip by filename
    eventSource.addEventListener('upload_processed', (e: MessageEvent) => {
      connectionFailures = 0
      try {
        const info = JSON.parse(e.data)
        const filename: string = info.filename || ''
        if (!filename) return
        setAttachments(prev => prev.map(a =>
          a.filename === filename ? { ...a, status: 'ready' as AttachmentStatus } : a
        ))
      } catch {
        /* ignore — chip will stay in processing until user removes it */
      }
    })

    eventSource.addEventListener('upload_error', (e: MessageEvent) => {
      connectionFailures = 0
      // Best-effort: payload may be a filename or a free-form message.
      // Mark any in-flight chip with that filename as error; if no match,
      // surface a generic error to the user.
      const payload = (e.data || '').toString()
      let matched = false
      setAttachments(prev => prev.map(a => {
        if ((a.status === 'uploading' || a.status === 'processing') && payload.includes(a.filename)) {
          matched = true
          return { ...a, status: 'error' as AttachmentStatus, errorMsg: payload }
        }
        return a
      }))
      if (!matched) {
        setError(payload || 'Upload processing failed')
      }
    })

    // Sprint 16: evidence deletion confirmations from backend
    eventSource.addEventListener('evidence_deleting', () => {
      connectionFailures = 0
      // No-op — chip was removed optimistically on click. Backend confirmation
      // arrives via evidence_deleted; failures restore the chip.
    })

    eventSource.addEventListener('evidence_deleted', () => {
      connectionFailures = 0
      // Optimistic removal already happened — nothing to do.
    })

    eventSource.addEventListener('evidence_delete_error', (e: MessageEvent) => {
      connectionFailures = 0
      try {
        const info = JSON.parse(e.data)
        const filename: string = info.filename || ''
        const reason: string = info.reason || 'unknown'
        // Chip is gone from local state — surface the error so the user knows
        // the file is still active.
        setError(`Could not remove ${filename}: ${reason}`)
      } catch {
        setError('Could not remove attachment')
      }
    })

    eventSource.addEventListener('error', (e: MessageEvent) => {
      eventSource.close()
      setStreamingText('')
      setIsStreaming(false)
      setQueuePosition(null)
      setError(e.data || 'An error occurred')
    })

    // Lesson #1: unblock UI after 3 consecutive connection failures
    eventSource.onerror = () => {
      connectionFailures++
      if (connectionFailures >= 3) {
        eventSource.close()
        setStreamingText('')
        setIsStreaming(false)
        setQueuePosition(null)
        setError('Connection lost. Please try again.')
      }
    }
  }

  const endSession = async () => {
    setShowEndConfirm(false)

    setError('')
    setIsStreaming(true)
    setStreamingText('')
    setQueuePosition(null)

    const messageId = crypto.randomUUID?.()
      ?? `${Date.now()}-${Math.random().toString(36).slice(2, 11)}`
    const timestamp = new Date().toISOString()

    try {
      listenForResponse(true)

      await fetch('/internal/queue', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_token: sessionToken,
          content: '',
          message_id: messageId,
          timestamp,
          language: lang,
          finalize: true,
        }),
      })
    } catch {
      setIsStreaming(false)
      setError('Failed to end session. Please try again.')
    }
  }

  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const fileList = e.target.files
    if (!fileList || fileList.length === 0) return
    const files = Array.from(fileList)
    e.target.value = ''
    await processFiles(files)
  }

  // Sprint 16: auto-rename collisions client-side. If "file.pdf" is already
  // attached or in the chip list, send as "file (2).pdf", "file (3).pdf", …
  const reserveFilename = (desired: string, taken: Set<string>): string => {
    if (!taken.has(desired)) {
      taken.add(desired)
      return desired
    }
    const dotIdx = desired.lastIndexOf('.')
    const stem = dotIdx > 0 ? desired.slice(0, dotIdx) : desired
    const ext = dotIdx > 0 ? desired.slice(dotIdx) : ''
    let n = 2
    while (taken.has(`${stem} (${n})${ext}`)) n++
    const renamed = `${stem} (${n})${ext}`
    taken.add(renamed)
    return renamed
  }

  const processFiles = async (files: File[]) => {
    if (files.length === 0) return

    // Limit to 4 files per batch
    if (files.length > 4) {
      setError(t('upload_batch_limit', lang))
      return
    }

    setError('')

    // Open SSE to receive upload events (chip status updates flow over this)
    if (!eventSourceRef.current || eventSourceRef.current.readyState === EventSource.CLOSED) {
      listenForResponse()
    }

    // Build the unique filename set (existing chips + this batch)
    const taken = new Set(attachments.map(a => a.filename))

    const newChips: Attachment[] = files.map(f => ({
      id: crypto.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2, 11)}`,
      filename: reserveFilename(f.name, taken),
      status: 'uploading' as AttachmentStatus,
    }))

    setAttachments(prev => [...prev, ...newChips])

    // Upload each file in parallel
    await Promise.all(files.map(async (file, idx) => {
      const chip = newChips[idx]
      const formData = new FormData()
      // Send the (possibly renamed) filename to the backend so collisions are
      // resolved client-side and the backend never silently overwrites.
      formData.append('file', file, chip.filename)
      try {
        const resp = await fetch(`/internal/upload/${sessionToken}`, {
          method: 'POST',
          body: formData,
        })
        if (!resp.ok) {
          const body = await resp.json().catch(() => ({ detail: 'Upload failed' }))
          throw new Error(body.detail || `HTTP ${resp.status}`)
        }
        // Backend has the file — move chip to processing. The SSE
        // upload_processed event will move it to ready when done.
        setAttachments(prev => prev.map(a =>
          a.id === chip.id ? { ...a, status: 'processing' as AttachmentStatus } : a
        ))
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Upload failed'
        setAttachments(prev => prev.map(a =>
          a.id === chip.id ? { ...a, status: 'error' as AttachmentStatus, errorMsg: msg } : a
        ))
      }
    }))
  }

  // Sprint 16: remove a chip. For ready/error chips, also call the sidecar
  // DELETE endpoint to retract the file from session evidence + RAG.
  const removeAttachment = async (chip: Attachment) => {
    if (chip.status === 'uploading' || chip.status === 'processing') return
    // Optimistic removal
    setAttachments(prev => prev.filter(a => a.id !== chip.id))
    if (chip.status === 'error') return  // file never landed on backend
    try {
      const resp = await fetch(`/internal/evidence/${sessionToken}/${encodeURIComponent(chip.filename)}`, {
        method: 'DELETE',
      })
      if (!resp.ok) {
        // Restore the chip if the request was rejected outright
        setAttachments(prev => [...prev, { ...chip, status: 'error' as AttachmentStatus, errorMsg: 'Delete failed' }])
        setError('Could not remove attachment')
      }
      // Otherwise wait for the SSE evidence_deleted/error event for confirmation
      if (!eventSourceRef.current || eventSourceRef.current.readyState === EventSource.CLOSED) {
        listenForResponse()
      }
    } catch {
      setAttachments(prev => [...prev, { ...chip, status: 'error' as AttachmentStatus, errorMsg: 'Network error' }])
      setError('Could not remove attachment')
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  // Drag-and-drop file upload
  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (sessionEnded || isStreaming) return
    if (e.dataTransfer?.types?.includes('Files')) {
      dragCounter.current += 1
      setIsDragging(true)
    }
  }

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    dragCounter.current -= 1
    if (dragCounter.current <= 0) {
      dragCounter.current = 0
      setIsDragging(false)
    }
  }

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    dragCounter.current = 0
    setIsDragging(false)
    if (sessionEnded || isStreaming) return
    const files = Array.from(e.dataTransfer?.files || [])
    processFiles(files)
  }

  // Recovery: show previous session context
  const recoverySummary = recoveryData?.recovery_type === 'summary' ? recoveryData.summary : null
  const recoveryMessages = recoveryData?.recovery_type === 'full' ? recoveryData.messages : null

  return (
    <div className="max-w-4xl mx-auto flex flex-col h-[calc(100svh-64px)] relative">
      {/* Session token */}
      <div className="text-center text-xs text-gray-400 py-2 font-mono">{sessionToken}</div>

      {/* UNI watermark — centered behind chat bubbles */}
      <div className="pointer-events-none absolute inset-0 flex items-center justify-center z-0 opacity-[0.08]">
        <img src="/uni-logo.png" alt="" className="w-72 max-w-[60%]" />
      </div>

      {/* Messages */}
      <div ref={scrollContainerRef} onScroll={handleScroll} className="flex-1 overflow-y-auto px-4 space-y-4 pb-4 relative z-10">

        {/* Recovery: previous session summary */}
        {recoverySummary && (
          <div className="bg-blue-50 border border-blue-200 rounded-xl px-5 py-4 text-sm text-gray-700">
            <div className="text-xs font-semibold text-uni-blue mb-2 uppercase tracking-wide">
              Previous session summary ({recoveryData?.message_count} messages)
            </div>
            <div className="prose prose-sm max-w-none prose-headings:text-gray-800 prose-p:text-gray-700 prose-li:text-gray-700 prose-strong:text-gray-800">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{recoverySummary}</ReactMarkdown>
            </div>
          </div>
        )}

        {/* Recovery: previous messages (short conversations) */}
        {recoveryMessages && recoveryMessages.length > 0 && (
          <div className="bg-gray-50 border border-gray-200 rounded-xl px-5 py-4 space-y-3">
            <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
              Previous conversation
            </div>
            {recoveryMessages.map((msg, i) => (
              <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div
                  className={`max-w-[80%] rounded-lg px-3 py-2 text-sm opacity-75 ${
                    msg.role === 'user'
                      ? 'bg-uni-blue/20 text-gray-700'
                      : 'bg-white border border-gray-200 text-gray-600'
                  }`}
                >
                  {msg.role === 'user' ? msg.content : (
                    <div className="prose prose-sm max-w-none prose-headings:text-gray-800 prose-p:text-gray-600 prose-li:text-gray-600 prose-strong:text-gray-700">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Separator after recovery context */}
        {recoveryData && (
          <div className="flex items-center gap-3 text-xs text-gray-400">
            <div className="flex-1 border-t border-gray-200" />
            <span>Session resumed</span>
            <div className="flex-1 border-t border-gray-200" />
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[80%] rounded-lg px-4 py-3 ${
                msg.isSummary
                  ? 'bg-green-50 border-2 border-green-300 text-gray-800'
                  : msg.role === 'user'
                    ? 'bg-uni-blue text-white'
                    : 'bg-white border border-gray-200 text-gray-800'
              }`}
            >
              {msg.isSummary && (
                <div className="text-xs font-semibold text-green-700 mb-2 uppercase tracking-wide">
                  {t('session_summary_label', lang)}
                </div>
              )}
              {msg.role === 'user' ? (
                <div className="text-sm whitespace-pre-wrap">
                  {msg.content && <div>{msg.content}</div>}
                  {msg.attachments && msg.attachments.length > 0 && (
                    <div className={msg.content ? 'mt-2 flex flex-wrap gap-1.5' : 'flex flex-wrap gap-1.5'}>
                      {msg.attachments.map(fn => (
                        <span key={fn} className="inline-flex items-center gap-1 bg-white/20 rounded px-2 py-0.5 text-xs">
                          📎 {fn}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ) : (
                <div className="text-sm prose prose-sm max-w-none prose-headings:text-gray-800 prose-p:text-gray-700 prose-li:text-gray-700 prose-strong:text-gray-800">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                </div>
              )}
            </div>
          </div>
        ))}

        {/* Streaming response */}
        {isStreaming && (
          <div className="flex justify-start">
            <div className="max-w-[80%] rounded-lg px-4 py-3 bg-white border border-gray-200 text-gray-800">
              {queuePosition !== null && !streamingText && (
                <div className="flex items-center gap-2 text-sm text-gray-400">
                  <span className="inline-block w-2 h-2 bg-uni-blue rounded-full animate-pulse" />
                  {queuePosition === 1
                    ? 'Processing...'
                    : `Position ${queuePosition} in queue...`}
                </div>
              )}
              {!streamingText && queuePosition === null && (
                <div className="flex items-center gap-2 text-sm text-gray-400">
                  <span className="inline-block w-2 h-2 bg-uni-blue rounded-full animate-pulse" />
                  Preparing...
                </div>
              )}
              {streamingText && (
                <div className="text-sm prose prose-sm max-w-none prose-headings:text-gray-800 prose-p:text-gray-700 prose-li:text-gray-700 prose-strong:text-gray-800">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{streamingText}</ReactMarkdown>
                </div>
              )}
            </div>
          </div>
        )}

        {error && (
          <div className="text-center">
            <span className="text-sm text-uni-red">{error}</span>
          </div>
        )}

        <div ref={chatEndRef} />
      </div>

      {/* Confirmation dialog */}
      {showEndConfirm && (
        <div className="border-t border-gray-200 bg-red-50 px-4 py-3">
          <div className="max-w-4xl mx-auto text-center space-y-3">
            <p className="text-sm text-gray-700">{t('end_session_confirm', lang)}</p>
            <div className="flex gap-3 justify-center">
              <button
                onClick={endSession}
                className="bg-uni-red text-white rounded-lg px-5 py-2 text-sm font-medium transition-colors hover:opacity-90"
              >
                {t('end_session_yes', lang)}
              </button>
              <button
                onClick={() => setShowEndConfirm(false)}
                className="border border-gray-300 text-gray-700 rounded-lg px-5 py-2 text-sm font-medium transition-colors hover:bg-gray-50"
              >
                {t('end_session_no', lang)}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Input */}
      <div className="border-t border-gray-200 bg-white px-4 py-3">
        {sessionEnded ? (
          <div className="text-center text-sm text-gray-500 py-2">
            {t('session_ended_notice', lang)}
          </div>
        ) : (
          <>
          <div
            className="max-w-4xl mx-auto space-y-2"
            onDragEnter={handleDragEnter}
            onDragLeave={handleDragLeave}
            onDragOver={handleDragOver}
            onDrop={handleDrop}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.txt,.md,.doc,.docx,.jpg,.jpeg,.png"
              multiple
              onChange={handleUpload}
              className="hidden"
            />
            {/* Sprint 16: attachment chips above the textarea */}
            {attachments.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {attachments.map(chip => {
                  const inFlight = chip.status === 'uploading' || chip.status === 'processing'
                  const statusKey =
                    chip.status === 'uploading' ? 'attachment_uploading'
                    : chip.status === 'processing' ? 'attachment_processing'
                    : chip.status === 'ready' ? 'attachment_ready'
                    : 'attachment_error'
                  const statusColor =
                    chip.status === 'ready' ? 'text-green-600'
                    : chip.status === 'error' ? 'text-uni-red'
                    : 'text-gray-500'
                  return (
                    <div
                      key={chip.id}
                      className={`inline-flex items-center gap-2 max-w-full bg-gray-50 border rounded-full pl-3 pr-1 py-1 text-sm ${
                        chip.status === 'error' ? 'border-uni-red' : 'border-gray-300'
                      }`}
                      title={chip.errorMsg || chip.filename}
                    >
                      <span className="shrink-0">📎</span>
                      <span className="truncate max-w-[12rem] text-gray-800">{chip.filename}</span>
                      <span className={`shrink-0 text-xs ${statusColor} flex items-center gap-1`}>
                        {inFlight && (
                          <span className="inline-block w-1.5 h-1.5 bg-uni-blue rounded-full animate-pulse" />
                        )}
                        {t(statusKey, lang)}
                      </span>
                      <button
                        type="button"
                        onClick={() => removeAttachment(chip)}
                        disabled={inFlight}
                        aria-label={t('attachment_remove', lang)}
                        className="shrink-0 w-6 h-6 flex items-center justify-center rounded-full text-gray-500 hover:bg-gray-200 hover:text-gray-800 disabled:opacity-30 disabled:cursor-not-allowed"
                      >
                        <svg xmlns="http://www.w3.org/2000/svg" className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                        </svg>
                      </button>
                    </div>
                  )
                })}
              </div>
            )}
            {/* Row 1: textarea with embedded Send button */}
            <div className="relative">
              <textarea
                ref={textareaRef}
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={t('chat_placeholder', lang)}
                disabled={isStreaming}
                className={`w-full border rounded-lg pl-4 pr-14 py-3 focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none resize-none text-base disabled:opacity-50 min-h-[3rem] transition-colors ${
                  isDragging ? 'border-uni-blue border-2 border-dashed bg-blue-50' : 'border-gray-300'
                }`}
              />
              {isDragging && (
                <div className="absolute inset-0 flex items-center justify-center pointer-events-none rounded-lg">
                  <span className="text-uni-blue text-sm font-medium bg-white/80 px-3 py-1 rounded">
                    {t('drop_files_here', lang)}
                  </span>
                </div>
              )}
              <button
                onClick={sendMessage}
                disabled={!canSend}
                title={hasInFlightChip ? t('attachment_send_blocked', lang) : undefined}
                aria-label="Send"
                className="absolute right-2 bottom-2 w-9 h-9 flex items-center justify-center bg-uni-blue text-white rounded-lg transition-colors hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 10l7-7m0 0l7 7m-7-7v18" />
                </svg>
              </button>
            </div>
            {/* Row 2: Attach left, End Session right */}
            <div className="flex justify-between items-center">
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={isStreaming}
                title={t('upload_button_title', lang)}
                className="flex items-center gap-2 text-gray-500 hover:text-uni-blue transition-colors disabled:opacity-50 disabled:cursor-not-allowed px-3 py-2 min-h-[44px]"
              >
                <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
                </svg>
                <span className="text-sm font-medium">{t('attach_file', lang)}</span>
              </button>
              {!isStreaming && (
                <button
                  onClick={() => setShowEndConfirm(true)}
                  className="border border-uni-red text-uni-red rounded-lg px-4 py-2 text-sm font-medium transition-colors hover:bg-red-50 min-h-[44px]"
                >
                  {t('end_session', lang)}
                </button>
              )}
            </div>
          </div>
          </>
        )}
      </div>
    </div>
  )
}
