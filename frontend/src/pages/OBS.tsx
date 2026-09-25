import { useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useTranscript } from '../hooks/useTranscript'

// How many finalised lines to keep visible above the current partial.
const VISIBLE_FINALS = 2

export default function OBS() {
  const [params] = useSearchParams()
  const stage = parseInt(params.get('stage') ?? '1', 10)
  const lang = params.get('lang') ?? 'es'

  const { lines, currentLine } = useTranscript(stage, lang)

  // Make the page fully transparent for OBS Browser Source.
  useEffect(() => {
    document.body.classList.add('obs-mode')
    document.documentElement.classList.add('obs-mode')
    return () => {
      document.body.classList.remove('obs-mode')
      document.documentElement.classList.remove('obs-mode')
    }
  }, [])

  const visibleFinals = lines.slice(-VISIBLE_FINALS)

  // Nothing to show yet — render nothing so OBS sees a blank transparent page.
  if (visibleFinals.length === 0 && !currentLine) return null

  return (
    <div className="obs-overlay">
      <div className="obs-subtitle">
        {visibleFinals.map((line) => (
          // key by sequence → React creates a new element for each final line,
          // which triggers the fade-in animation without reflowing older lines.
          <p key={line.sequence} className="obs-line obs-line--final">
            {line.text}
          </p>
        ))}
        {currentLine && (
          // key is stable → element stays in place while text updates in-place,
          // avoiding any flash or re-animation on every interim word.
          <p key="partial" className="obs-line obs-line--partial">
            {currentLine.text}
          </p>
        )}
      </div>
    </div>
  )
}
