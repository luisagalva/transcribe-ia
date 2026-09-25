import { useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useTranscript } from '../hooks/useTranscript'

export default function OBS() {
  const [params] = useSearchParams()
  const stage = parseInt(params.get('stage') ?? '1', 10)
  const lang = params.get('lang') ?? 'es'

  const { lines, currentLine } = useTranscript(stage, lang)

  useEffect(() => {
    document.body.classList.add('obs-mode')
    document.documentElement.classList.add('obs-mode')
    return () => {
      document.body.classList.remove('obs-mode')
      document.documentElement.classList.remove('obs-mode')
    }
  }, [])

  // While a partial is building, hide old finals so the same content
  // doesn't appear twice (final + partial of the same phrase).
  const lastFinal = currentLine ? null : lines.at(-1) ?? null

  if (!lastFinal && !currentLine) return null

  return (
    <div className="obs-overlay">
      <div className="obs-subtitle">
        {lastFinal && (
          <p key={lastFinal.sequence} className="obs-line obs-line--final">
            {lastFinal.text}
          </p>
        )}
        {currentLine && (
          <p key="partial" className="obs-line obs-line--partial">
            {currentLine.text}
          </p>
        )}
      </div>
    </div>
  )
}
