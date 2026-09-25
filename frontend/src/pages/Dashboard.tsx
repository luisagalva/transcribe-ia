import { useCallback, useEffect, useRef, useState } from 'react'

// ── Types ─────────────────────────────────────────────────────────────────────

interface StageSnapshot {
  stage_id: number
  worker_status: 'idle' | 'active' | 'reconnecting' | 'error' | 'unknown'
  viewer_count: number
  latency_ms: number | null
  last_text: string | null
  last_seen_ts: number | null
  muted: boolean
}

interface Thresholds {
  latency_warn_ms: number
  latency_crit_ms: number
  stale_warn_sec: number
  stale_crit_sec: number
}

const DEFAULTS: Thresholds = {
  latency_warn_ms: 1500,
  latency_crit_ms: 4000,
  stale_warn_sec: 30,
  stale_crit_sec: 120,
}

type Level = 'ok' | 'warn' | 'crit' | 'none'

// ── Utility helpers ───────────────────────────────────────────────────────────

function timeAgo(ts: number | null): string {
  if (!ts) return '—'
  const s = Math.floor(Date.now() / 1000 - ts)
  if (s < 5) return 'ahora'
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m`
  return `${Math.floor(s / 3600)}h`
}

function staleLevel(ts: number | null, t: Thresholds): Level {
  if (!ts) return 'none'
  const s = Math.floor(Date.now() / 1000 - ts)
  if (s >= t.stale_crit_sec) return 'crit'
  if (s >= t.stale_warn_sec) return 'warn'
  return 'ok'
}

function latencyLevel(ms: number | null, t: Thresholds): Level {
  if (ms === null) return 'none'
  if (ms >= t.latency_crit_ms) return 'crit'
  if (ms >= t.latency_warn_ms) return 'warn'
  return 'ok'
}

// ── Token gate ────────────────────────────────────────────────────────────────

function TokenGate({
  onToken,
  authError,
}: {
  onToken: (t: string) => void
  authError: boolean
}) {
  const [value, setValue] = useState('')

  function submit(e: React.FormEvent) {
    e.preventDefault()
    const t = value.trim()
    if (t) onToken(t)
  }

  return (
    <div className="token-gate">
      <div className="token-gate-card">
        <h1 className="token-gate-title">
          transcribe<span className="accent">-ia</span>
        </h1>
        <p className="token-gate-sub">Dashboard de Producción</p>
        {authError && (
          <p className="token-gate-error">Token inválido. Intenta de nuevo.</p>
        )}
        <form onSubmit={submit} className="token-gate-form">
          <input
            type="password"
            className="token-gate-input"
            placeholder="Token de acceso"
            value={value}
            onChange={e => setValue(e.target.value)}
            autoFocus
          />
          <button type="submit" className="token-gate-btn">
            Entrar
          </button>
        </form>
      </div>
    </div>
  )
}

// ── Stage card ────────────────────────────────────────────────────────────────

const WORKER_LABELS: Record<string, string> = {
  active: 'ACTIVO',
  reconnecting: 'RECONECTANDO',
  idle: 'DETENIDO',
  error: 'ERROR',
  unknown: 'DESCONOCIDO',
}

function StageCard({
  stage,
  thresholds,
  onMute,
  tick: _tick,
}: {
  stage: StageSnapshot
  thresholds: Thresholds
  onMute: (id: number, muted: boolean) => void
  tick: number
}) {
  const workerOk = stage.worker_status === 'active'
  const workerWarn = stage.worker_status === 'reconnecting'
  const staleLvl = staleLevel(stage.last_seen_ts, thresholds)
  const latLvl = latencyLevel(stage.latency_ms, thresholds)
  const geminiLvl: Level = workerOk ? 'ok' : workerWarn ? 'warn' : 'crit'

  const cardClass = [
    'stage-card',
    stage.muted ? 'stage-muted' : '',
    !workerOk && !workerWarn ? 'stage-crit' : '',
    workerWarn || staleLvl === 'warn' || latLvl === 'warn' ? 'stage-warn-border' : '',
    staleLvl === 'crit' || latLvl === 'crit' ? 'stage-crit' : '',
  ]
    .filter(Boolean)
    .join(' ')

  const workerBadgeClass = `worker-badge worker-${workerOk ? 'ok' : workerWarn ? 'warn' : 'crit'}`

  return (
    <div className={cardClass}>
      <div className="card-header">
        <span className="stage-num">Stage {stage.stage_id}</span>
        <span className={workerBadgeClass}>
          {WORKER_LABELS[stage.worker_status] ?? stage.worker_status}
        </span>
        <button
          className={`mute-btn ${stage.muted ? 'is-muted' : ''}`}
          onClick={() => onMute(stage.stage_id, stage.muted)}
          title={stage.muted ? 'Reactivar stage' : 'Silenciar stage'}
        >
          {stage.muted ? '🔇 Silenciado' : 'Silenciar'}
        </button>
      </div>

      <div className="card-metrics">
        <div className="metric">
          <span className="metric-label">Gemini</span>
          <span className={`metric-value metric-${geminiLvl}`}>
            <span className="metric-dot" />
            {workerOk ? 'conectado' : workerWarn ? 'reconectando' : 'desconectado'}
          </span>
        </div>

        <div className="metric">
          <span className="metric-label">Espectadores</span>
          <span className="metric-value">{stage.viewer_count}</span>
        </div>

        <div className="metric">
          <span className="metric-label">Latencia</span>
          <span className={`metric-value metric-${latLvl}`}>
            {stage.latency_ms !== null ? `${stage.latency_ms}ms` : '—'}
          </span>
        </div>

        <div className="metric">
          <span className="metric-label">Último msg</span>
          <span className={`metric-value metric-${staleLvl}`}>
            {timeAgo(stage.last_seen_ts)}
          </span>
        </div>
      </div>

      <div className="card-stream">
        <StreamStatus stale={staleLvl} workerOk={workerOk} />
      </div>

      <p className="card-transcript">
        {stage.last_text ?? (
          <span style={{ opacity: 0.4 }}>Sin transcripciones</span>
        )}
      </p>
    </div>
  )
}

function StreamStatus({ stale, workerOk }: { stale: Level; workerOk: boolean }) {
  if (!workerOk)
    return <span className="stream-tag stream-crit">● Sin Worker</span>
  if (stale === 'crit')
    return <span className="stream-tag stream-crit">● Sin audio</span>
  if (stale === 'warn')
    return <span className="stream-tag stream-warn">● Audio lento</span>
  if (stale === 'none')
    return <span className="stream-tag stream-none">○ Esperando</span>
  return <span className="stream-tag stream-ok">● Stream OK</span>
}

// ── Dashboard root ────────────────────────────────────────────────────────────

export default function Dashboard() {
  const [token, setToken] = useState<string>(
    () => sessionStorage.getItem('db_token') ?? ''
  )
  const [authError, setAuthError] = useState(false)
  const [stages, setStages] = useState<StageSnapshot[]>([])
  const [thresholds, setThresholds] = useState<Thresholds>(DEFAULTS)
  const [connected, setConnected] = useState(false)
  // Tick every second to keep "time ago" values fresh without additional WebSocket traffic.
  const [tick, setTick] = useState(0)

  const wsRef = useRef<WebSocket | null>(null)
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mountedRef = useRef(true)

  useEffect(() => {
    const id = setInterval(() => setTick(n => n + 1), 1000)
    return () => clearInterval(id)
  }, [])

  // Load threshold config once on auth
  useEffect(() => {
    if (!token) return
    fetch(`/dashboard/config?token=${encodeURIComponent(token)}`)
      .then(r => (r.ok ? r.json() : null))
      .then(data => data && setThresholds(data))
      .catch(() => {})
  }, [token])

  const connect = useCallback(() => {
    if (!mountedRef.current || !token) return
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(
      `${proto}//${window.location.host}/ws/dashboard?token=${encodeURIComponent(token)}`
    )
    wsRef.current = ws

    ws.onopen = () => {
      if (!mountedRef.current) {
        ws.close()
        return
      }
      setConnected(true)
      setAuthError(false)
    }

    ws.onmessage = (ev: MessageEvent<string>) => {
      if (!mountedRef.current) return
      try {
        const msg = JSON.parse(ev.data)
        if (msg.event === 'dashboard_update') setStages(msg.stages)
      } catch {}
    }

    ws.onclose = (ev: CloseEvent) => {
      if (!mountedRef.current) return
      setConnected(false)
      if (ev.code === 4003) {
        setAuthError(true)
        setToken('')
        sessionStorage.removeItem('db_token')
        return
      }
      reconnectRef.current = setTimeout(connect, 3000)
    }
  }, [token])

  useEffect(() => {
    mountedRef.current = true
    if (token) connect()
    return () => {
      mountedRef.current = false
      if (reconnectRef.current) clearTimeout(reconnectRef.current)
      wsRef.current?.close()
    }
  }, [connect])

  // Ping every 30s to keep the WebSocket alive through proxies/load balancers.
  useEffect(() => {
    const id = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send('ping')
      }
    }, 30_000)
    return () => clearInterval(id)
  }, [])

  async function handleMute(stageId: number, currentMuted: boolean) {
    try {
      await fetch(`/stages/${stageId}/mute?token=${encodeURIComponent(token)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ muted: !currentMuted }),
      })
    } catch {}
  }

  function handleToken(t: string) {
    sessionStorage.setItem('db_token', t)
    setToken(t)
  }

  if (!token) {
    return <TokenGate onToken={handleToken} authError={authError} />
  }

  return (
    <div className="dashboard">
      <header className="dashboard-header">
        <span className="viewer-logo">
          transcribe<span className="accent">-ia</span>{' '}
          <span className="dashboard-label">producción</span>
        </span>
        <div className={`status-badge ${connected ? 'status-live' : 'status-off'}`}>
          <span className="status-dot" />
          {connected ? 'Dashboard en vivo' : 'Reconectando…'}
        </div>
      </header>

      <main className="dashboard-grid">
        {stages.map(s => (
          <StageCard
            key={s.stage_id}
            stage={s}
            thresholds={thresholds}
            onMute={handleMute}
            tick={tick}
          />
        ))}
        {stages.length === 0 && (
          <p className="empty-hint" style={{ gridColumn: '1 / -1' }}>
            Conectando a Redis…
          </p>
        )}
      </main>
    </div>
  )
}
