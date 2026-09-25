import { useEffect, useRef, useState } from 'react'
import { useTranscript } from '../hooks/useTranscript'

// ── Constants ─────────────────────────────────────────────────────────────────

const SOURCE_LANGS = [
  { value: 'es', label: 'Español' },
  { value: 'en', label: 'English' },
  { value: 'zh', label: '中文' },
  { value: 'pt', label: 'Português' },
]

const TARGET_LANGS = [
  { value: 'original', label: 'Original', sub: 'Sin traducción' },
  { value: 'es', label: 'Español', sub: 'Traducir al español' },
  { value: 'en', label: 'English', sub: 'Translate to English' },
  { value: 'zh', label: '中文', sub: '翻译成中文' },
  { value: 'pt', label: 'Português', sub: 'Traduzir para português' },
]

// ── Types ─────────────────────────────────────────────────────────────────────

interface Session {
  sessionId: string
  stageId: number
  url: string
  sourceLang: string
  targetLangs: string[]   // langs the worker is translating to
  viewLang: string        // which lang this viewer shows
}

// ── Setup form ────────────────────────────────────────────────────────────────

function SetupForm({ onStart }: { onStart: (s: Session) => void }) {
  const [url, setUrl] = useState('')
  const [sourceLang, setSourceLang] = useState('es')
  const [targetLangs, setTargetLangs] = useState<string[]>([])
  const [viewLang, setViewLang] = useState('original')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function toggleTarget(lang: string) {
    setTargetLangs(prev =>
      prev.includes(lang) ? prev.filter(l => l !== lang) : [...prev, lang]
    )
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    const trimmed = url.trim()
    if (!trimmed) return

    setLoading(true)
    setError(null)

    try {
      const res = await fetch('/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: trimmed,
          lang: sourceLang,
          target_langs: targetLangs,
        }),
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
        sourceLang,
        targetLangs,
        viewLang,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error desconocido')
    } finally {
      setLoading(false)
    }
  }

  // Auto-select viewLang: if the chosen viewLang is a translation that was unchecked, reset
  const effectiveViewLang =
    viewLang === 'original' || targetLangs.includes(viewLang) ? viewLang : 'original'

  return (
    <div className="transcribe-setup">
      <div className="transcribe-card">
        <h1 className="transcribe-title">
          transcribe<span className="accent">-ia</span>
        </h1>
        <p className="transcribe-sub">Transcripción y traducción en tiempo real</p>

        <form onSubmit={submit} className="transcribe-form">
          {/* URL */}
          <div className="form-field">
            <label className="form-label" htmlFor="url-input">URL del video o stream</label>
            <input
              id="url-input"
              type="url"
              className="form-input"
              placeholder="https://youtube.com/watch?v=…  o  https://…"
              value={url}
              onChange={e => setUrl(e.target.value)}
              disabled={loading}
              autoFocus
              required
            />
            <p className="form-hint">YouTube, videos directos, HLS, RTMP</p>
          </div>

          {/* Source language */}
          <div className="form-field">
            <label className="form-label">Idioma del audio</label>
            <div className="src-lang-row">
              {SOURCE_LANGS.map(opt => (
                <button
                  key={opt.value}
                  type="button"
                  className={`src-lang-btn ${sourceLang === opt.value ? 'src-lang-btn--active' : ''}`}
                  onClick={() => setSourceLang(opt.value)}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Target languages (multi-select) */}
          <div className="form-field">
            <label className="form-label">Traducir a (selecciona varios)</label>
            <div className="lang-options">
              {TARGET_LANGS.filter(o => o.value !== 'original').map(opt => (
                <label
                  key={opt.value}
                  className={`lang-option ${targetLangs.includes(opt.value) ? 'lang-option--selected' : ''}`}
                >
                  <input
                    type="checkbox"
                    className="lang-radio"
                    checked={targetLangs.includes(opt.value)}
                    onChange={() => toggleTarget(opt.value)}
                  />
                  <span className="lang-name">{opt.label}</span>
                  <span className="lang-sub">{opt.sub}</span>
                </label>
              ))}
            </div>
            <p className="form-hint">
              Sin seleccionar = solo transcripción en idioma original
            </p>
          </div>

          {/* View language selector */}
          <div className="form-field">
            <label className="form-label">Ver en pantalla como</label>
            <div className="lang-options">
              {TARGET_LANGS.filter(
                o => o.value === 'original' || targetLangs.includes(o.value)
              ).map(opt => (
                <label
                  key={opt.value}
                  className={`lang-option ${effectiveViewLang === opt.value ? 'lang-option--selected' : ''}`}
                >
                  <input
                    type="radio"
                    name="view-lang"
                    className="lang-radio"
                    checked={effectiveViewLang === opt.value}
                    onChange={() => setViewLang(opt.value)}
                  />
                  <span className="lang-name">{opt.label}</span>
                  <span className="lang-sub">{opt.sub}</span>
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

// ── Active transcript view ────────────────────────────────────────────────────

function ActiveTranscript({ session, onStop }: { session: Session; onStop: () => void }) {
  const wsLang = session.viewLang === 'original' ? 'original' : session.viewLang
  const { lines, currentLine, status, connected } = useTranscript(session.stageId, wsLang)
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

  const viewLabel = TARGET_LANGS.find(o => o.value === session.viewLang)?.label ?? session.viewLang

  const shortUrl = (() => {
    try {
      const u = new URL(session.url)
      const path = u.pathname.length > 18 ? u.pathname.slice(0, 18) + '…' : u.pathname
      return u.hostname + path
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
          <span className="transcribe-lang-tag">{viewLabel}</span>
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
              ? 'Iniciando… puede tardar unos segundos'
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
  return session
    ? <ActiveTranscript session={session} onStop={() => setSession(null)} />
    : <SetupForm onStart={setSession} />
}
