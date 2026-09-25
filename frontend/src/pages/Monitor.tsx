import { useCallback, useEffect, useRef, useState } from "react";

// ── Types ─────────────────────────────────────────────────────────────────────

interface StageSnapshot {
  stage_id: number;
  worker_status: "active" | "idle" | "reconnecting" | "error" | "unknown";
  latency_ms: number | null;
  last_text: string | null;
  last_seen_ts: number | null;
  active_langs: string[];
  error_count: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const LAT_WARN = 1500;
const LAT_CRIT = 4000;
const STALE_WARN = 30;
const STALE_CRIT = 120;

type Level = "ok" | "warn" | "crit" | "none";

function latLevel(ms: number | null): Level {
  if (ms === null) return "none";
  if (ms >= LAT_CRIT) return "crit";
  if (ms >= LAT_WARN) return "warn";
  return "ok";
}

function staleLevel(ts: number | null): Level {
  if (!ts) return "none";
  const s = Date.now() / 1000 - ts;
  if (s >= STALE_CRIT) return "crit";
  if (s >= STALE_WARN) return "warn";
  return "ok";
}

function timeAgo(ts: number | null): string {
  if (!ts) return "—";
  const s = Math.floor(Date.now() / 1000 - ts);
  if (s < 5) return "ahora";
  if (s < 60) return `${s}s atrás`;
  if (s < 3600) return `${Math.floor(s / 60)}m atrás`;
  return `${Math.floor(s / 3600)}h atrás`;
}

const LANG_LABELS: Record<string, string> = {
  original: "ORIG",
  es: "ES",
  en: "EN",
  zh: "ZH",
  pt: "PT",
};

function levelColor(l: Level): string {
  return { ok: "#3FB950", warn: "#D29922", crit: "#F85149", none: "#7D8590" }[
    l
  ];
}

// ── Stage card ────────────────────────────────────────────────────────────────

function StageCard({
  stage,
  tick: _tick,
}: {
  stage: StageSnapshot;
  tick: number;
}) {
  const isActive = stage.worker_status === "active";
  const isReconn = stage.worker_status === "reconnecting";
  const isCrit = !isActive && !isReconn;

  const staleLvl = staleLevel(stage.last_seen_ts);
  const latLvl = latLevel(stage.latency_ms);

  const cardAlert =
    isCrit || staleLvl === "crit" || latLvl === "crit"
      ? "crit"
      : isReconn || staleLvl === "warn" || latLvl === "warn"
        ? "warn"
        : "none";

  return (
    <div className={`mc ${cardAlert !== "none" ? `mc--${cardAlert}` : ""}`}>
      {/* ── Top bar ── */}
      <div className="mc-top">
        <div className="mc-top-left">
          <span className="mc-id">Stage {stage.stage_id}</span>
          <StatusPill status={stage.worker_status} />
        </div>
        <div className="mc-top-right">
          {stage.error_count > 0 && (
            <span className="mc-err-pill" title="Reconexiones desde inicio">
              ↺ {stage.error_count}
            </span>
          )}
        </div>
      </div>

      {/* ── Metrics ── */}
      <div className="mc-metrics">
        <Metric
          label="Gemini"
          level={isActive ? "ok" : isReconn ? "warn" : "crit"}
        >
          <span className="mc-dot" />
          {isActive ? "conectado" : isReconn ? "reconectando" : "desconectado"}
        </Metric>

        <Metric label="Latencia" level={latLvl}>
          {stage.latency_ms !== null ? `${stage.latency_ms} ms` : "—"}
        </Metric>

        <Metric label="Último msg" level={staleLvl}>
          {timeAgo(stage.last_seen_ts)}
        </Metric>

        <Metric
          label="Stream"
          level={isActive ? (staleLvl === "none" ? "none" : staleLvl) : "crit"}
        >
          {streamLabel(staleLvl, isActive)}
        </Metric>
      </div>

      {/* ── Languages ── */}
      {stage.active_langs.length > 0 && (
        <div className="mc-langs">
          {stage.active_langs.map((l) => (
            <span key={l} className="mc-lang">
              {LANG_LABELS[l] ?? l.toUpperCase()}
            </span>
          ))}
        </div>
      )}

      {/* ── Transcript preview ── */}
      <p className="mc-text">
        {stage.last_text ?? <em>Sin transcripciones aún</em>}
      </p>
    </div>
  );
}

function streamLabel(stale: Level, workerOk: boolean): string {
  if (!workerOk) return "sin worker";
  if (stale === "crit") return "sin audio";
  if (stale === "warn") return "audio lento";
  if (stale === "none") return "esperando…";
  return "OK";
}

function Metric({
  label,
  level,
  children,
}: {
  label: string;
  level: Level;
  children: React.ReactNode;
}) {
  return (
    <div className="mc-metric">
      <span className="mc-metric-label">{label}</span>
      <span className="mc-metric-value" style={{ color: levelColor(level) }}>
        {children}
      </span>
    </div>
  );
}

function StatusPill({ status }: { status: StageSnapshot["worker_status"] }) {
  const map: Record<string, { label: string; cls: string }> = {
    active: { label: "ACTIVO", cls: "ok" },
    reconnecting: { label: "RECONECT.", cls: "warn" },
    idle: { label: "DETENIDO", cls: "muted" },
    error: { label: "ERROR", cls: "crit" },
    unknown: { label: "DESCON.", cls: "muted" },
  };
  const { label, cls } = map[status] ?? map.unknown;
  return <span className={`mc-pill mc-pill--${cls}`}>{label}</span>;
}

// ── Summary bar ───────────────────────────────────────────────────────────────

function SummaryBar({ stages }: { stages: StageSnapshot[] }) {
  const active = stages.filter((s) => s.worker_status === "active").length;
  const alerts = stages.filter(
    (s) => s.worker_status === "reconnecting" || s.worker_status === "error",
  ).length;
  const stopped = stages.filter(
    (s) => s.worker_status === "idle" || s.worker_status === "unknown",
  ).length;

  return (
    <div className="mon-summary">
      <SumCell label="Stages activos" value={active} accent="#3FB950" />
      <SumCell
        label="Alertas"
        value={alerts}
        accent={alerts > 0 ? "#F85149" : "#7D8590"}
        pulse={alerts > 0}
      />
      <SumCell label="Detenidos" value={stopped} accent="#7D8590" />
    </div>
  );
}

function SumCell({
  label,
  value,
  accent,
  pulse,
}: {
  label: string;
  value: number;
  accent: string;
  pulse?: boolean;
}) {
  return (
    <div className={`mon-sum-cell ${pulse ? "mon-sum-cell--pulse" : ""}`}>
      <span className="mon-sum-value" style={{ color: accent }}>
        {value}
      </span>
      <span className="mon-sum-label">{label}</span>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function Monitor() {
  const [stages, setStages] = useState<StageSnapshot[]>([]);
  const [connected, setConn] = useState(false);
  const [tick, setTick] = useState(0);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    const id = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, []);

  const connect = useCallback(() => {
    if (!mounted.current) return;
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${location.host}/ws/monitor`);
    wsRef.current = ws;

    ws.onopen = () => {
      if (!mounted.current) {
        ws.close();
        return;
      }
      setConn(true);
    };
    ws.onclose = () => {
      if (!mounted.current) return;
      setConn(false);
      reconnRef.current = setTimeout(connect, 3000);
    };
    ws.onmessage = (ev: MessageEvent<string>) => {
      if (!mounted.current) return;
      try {
        const msg = JSON.parse(ev.data);
        if (msg.event === "monitor_update") setStages(msg.stages);
      } catch {}
    };
  }, []);

  useEffect(() => {
    mounted.current = true;
    connect();
    return () => {
      mounted.current = false;
      if (reconnRef.current) clearTimeout(reconnRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  useEffect(() => {
    const id = setInterval(() => {
      wsRef.current?.readyState === WebSocket.OPEN &&
        wsRef.current.send("ping");
    }, 30_000);
    return () => clearInterval(id);
  }, []);

  const now = new Date();
  const timeStr = now.toLocaleTimeString("es", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

  return (
    <div className="mon-shell">
      {/* ── Header ── */}
      <header className="mon-header">
        <div className="mon-header-left">
          <span className="mon-logo">
            transcribe<span className="accent">-ia</span>
          </span>
          <span className="mon-header-tag">Dashboard</span>
        </div>

        <div className="mon-header-right">
          <span className="mon-clock">{timeStr}</span>
          <div
            className={`status-badge ${connected ? "status-live" : "status-off"}`}
          >
            <span className="status-dot" />
            {connected ? "en vivo" : "reconectando…"}
          </div>
        </div>
      </header>

      {/* ── Summary bar ── */}
      <SummaryBar stages={stages} />

      {/* ── Stage grid ── */}
      <main className="mon-grid">
        {stages.length === 0 ? (
          <div className="mon-empty">
            <p className="mon-empty-title">
              {connected ? "Sin stages activos" : "Conectando…"}
            </p>
            <p className="mon-empty-sub">
              {connected
                ? "Inicia un worker para ver su estado aquí en tiempo real."
                : "Estableciendo conexión con el gateway…"}
            </p>
          </div>
        ) : (
          stages.map((s) => (
            <StageCard key={s.stage_id} stage={s} tick={tick} />
          ))
        )}
      </main>
    </div>
  );
}
