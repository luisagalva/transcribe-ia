import { useEffect, useRef } from 'react'
import { useTranscript } from '../hooks/useTranscript'

const STAGE = 1
const LANG = 'es'

export default function Viewer() {
  const { lines, currentLine, status, connected } = useTranscript(STAGE, LANG)
  const bottomRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom when new lines arrive
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [lines, currentLine])

  return (
    <div className="viewer">
      <header className="viewer-header">
        <span className="viewer-logo">transcribe<span className="accent">-ia</span></span>
        <div className={`status-badge ${connected ? 'status-live' : 'status-off'}`}>
          <span className="status-dot" />
          {connected ? `Stage ${STAGE} · ${status}` : 'Desconectado'}
        </div>
      </header>

      <main className="transcript-area">
        {lines.length === 0 && !currentLine && (
          <p className="empty-hint">
            {connected
              ? 'Esperando transcripción…'
              : 'Conectando al servidor…'}
          </p>
        )}

        {lines.map((line) => (
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
