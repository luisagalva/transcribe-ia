import { useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useTranscript } from '../hooks/useTranscript'

export default function OBS() {
  const [params] = useSearchParams()
  const stage = parseInt(params.get('stage') ?? '1', 10)
  const lang = params.get('lang') ?? 'es'

  const { lines, currentLine } = useTranscript(stage, lang)

  // Make body fully transparent for OBS Browser Source
  useEffect(() => {
    document.body.classList.add('obs-mode')
    document.documentElement.classList.add('obs-mode')
    return () => {
      document.body.classList.remove('obs-mode')
      document.documentElement.classList.remove('obs-mode')
    }
  }, [])

  // Show current partial, fallback to last finalised line
  const display = currentLine?.text ?? lines[lines.length - 1]?.text ?? ''

  if (!display) return null

  return (
    <div className="obs-overlay">
      <p className="obs-text">{display}</p>
    </div>
  )
}
