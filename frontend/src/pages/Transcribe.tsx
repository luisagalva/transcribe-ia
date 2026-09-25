import { useEffect, useRef, useState } from 'react'
import { useTranscript } from '../hooks/useTranscript'

// ── Types ─────────────────────────────────────────────────────────────────────

type OutputMode = 'original' | 'es' | 'en' | 'zh'

interface Session {
  sessionId: string
  stageId: number
  url: string
  outputMode: OutputMode
}

// ── Language options ──────────────────────────────────────────────────────────

const OUTPUT_OPTIONS: { value: OutputMode; label: string; sublabel: string }[] = [
  { value: 'original', label: 'Original', sublabel: 'Transcripción directa' },
  { value: 'es', label: 'Español', sublabel: 'Traducir al español' },
  { value: 'en', label: 'English', sublabel: 'Translate to English' },
  { value: 'zh', label: '中文', sublabel: '翻译成中文' },
]

// ── Setup form ────────────────────────────────────────────────────────────────

function SetupForm({ onStart }: { onStart: (session: Session) => void }) {
  const [url, setUrl] = useState('')
  const [outputMode, setOutputMode] = useState<OutputMode>('original')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    const trimmed = url.trim()
    if (!trimmed) return

    setLoading(true)
    setError(null)

    try {
      const body: Record<string, string> = {
        url: trimmed,
        lang: 'es', // source language hint (Gemini auto-detects; this is for logging)
      }
      if (outputMode !== 'original') {
        body.output_lang = outputMode
      }

      const res = await fetch('/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })

      if (!res.ok) {
        const detail = await res.json().catch(() => ({ detail: res.statusText }))
        throw new Error(detail.detail ?? res.statusText)
      }

      const data = await res.json()
      onStart({
        sessionId: data.session_id,
        stageId: data.stage_id,
        url: trimmed,
        outputMode,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error desconocido')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="transcribe-setup">
      <div className="transcribe-card">
        <h1 className="transcribe-title">
          transcribe<span className="accent">-ia</span>
        </h1>
        <p className="transcribe-sub">Transcripción y traducción en tiempo real</p>

        <form onSubmit={submit} className="transcribe-form">
          <div className="form-field">
            <label className="form-label" htmlFor="url-input">
              URL del video o stream
            </label>
            <input
              id="url-input"
              type="url"
              className="form-input"
              placeholder="https://youtube.com/watch?v=... o https://..."
              value={url}
              onChange={e => setUrl(e.target.value)}
              disabled={loading}
              autoFocus
              required
            />
            <p className="form-hint">YouTube, videos directos, streams HLS/RTMP</p>
          </div>

          <div className="form-field">
            <label className="form-label">Idioma de salida</label>
            <div className="lang-options">
              {OUTPUT_OPTIONS.map(opt => (
                <label
                  key={opt.value}
                  className={`lang-option ${outputMode === opt.value ? 'lang-option--selected' : ''}`}
                >
                  <input
                    type="radio"
                    name="output-mode"
                    value={opt.value}
                    checked={outputMode === opt.value}
                    onChange={() => setOutputMode(opt.value)}
                    className="lang-radio"
                  />
                  <span className="lang-name">{opt.label}</span>
                  <span className="lang-sub">{opt.sublabel}</span>
                </label>
              ))}
            </div>
          </div>

          {error && <p className="form-error">{error}</p>}

          <button type="submit" className="transcribe-btn" disabled={loading || !url.trim()}>
            {loading ? 'Iniciando…' : 'Iniciar transcripción'}
          </button>
        </form>
      </div>
    </div>
  )
}

// ── Active transcript view ─────────────────────────────────────────────────────

function ActiveTranscript({
  session,
  onStop,
}: {
  session: Session
  onStop: () => void
}) {
  const { lines, currentLine, status, connected } = useTranscript(session.stageId, 'es')
  const bottomRef = useRef<HTMLDivElement>(null)
  const [stopping, setStopping] = useState(false)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [lines, currentLine])

  async function handleStop() {
    setStopping(true)
    try {
      await fetch(`/sessions/${session.sessionId}`, { method: 'DELETE' })
    } catch {}
    onStop()
  }

  const modeLabel = OUTPUT_OPTIONS.find(o => o.value === session.outputMode)?.label ?? session.outputMode

  const shortUrl = (() => {
    try {
      const u = new URL(session.url)
      return u.hostname + (u.pathname.length > 20 ? u.pathname.slice(0, 20) + '…' : u.pathname)
    } catch {
      return session.url.slice(0, 40)
    }
  })()

  return (
    <div className="viewer">
      <header className="viewer-header">
        <span className="viewer-logo">
          transcribe<span className="accent">-ia</span>
        </span>

        <div className="transcribe-header-meta">
          <span className="transcribe-url-tag" title={session.url}>{shortUrl}</span>
          <span className="transcribe-lang-tag">{modeLabel}</span>
          <div className={`status-badge ${connected ? 'status-live' : 'status-off'}`}>
            <span className="status-dot" />
            {connected ? status || 'en vivo' : 'Conectando…'}
          </div>
          <button
            className="transcribe-stop-btn"
            onClick={handleStop}
            disabled={stopping}
          >
            {stopping ? 'Deteniendo…' : 'Detener'}
          </button>
        </div>
      </header>

      <main className="transcript-area">
        {lines.length === 0 && !currentLine && (
          <p className="empty-hint">
            {connected
              ? 'Iniciando transcripción… (puede tardar unos segundos)'
              : 'Conectando al servidor…'}
          </p>
        )}

        {lines.map(line => (
          <p key={`${line.sequence}-${line.timestamp}`} className="transcript-line final">
            {line.text}
          </p>
        ))}

        {currentLine && (
          <p className="transcript-line partial">
            {currentLine.text}
            <span className="cursor" aria-hidden="true" />
          </p>
        )}

        <div ref={bottomRef} />
      </main>
    </div>
  )
}

// ── Page root ─────────────────────────────────────────────────────────────────

export default function Transcribe() {
  const [session, setSession] = useState<Session | null>(null)

  function handleStart(s: Session) {
    setSession(s)
  }

  function handleStop() {
    setSession(null)
  }

  if (session) {
    return <ActiveTranscript session={session} onStop={handleStop} />
  }

  return <SetupForm onStart={handleStart} />
}
