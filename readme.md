# transcribe-ia

Plataforma de transcripción simultánea en tiempo real para conferencias de tecnología.

**Stack:** Python · FastAPI · Gemini Live API · Redis Pub/Sub · WebSockets · React · TypeScript

## Requisitos

| Herramienta             | Versión           |
| ----------------------- | ----------------- |
| Python                  | 3.11+             |
| Node.js                 | 18+               |
| Docker & Docker Compose | cualquier versión |
| FFmpeg                  | instalado en PATH |

**Windows:**

```
winget install Gyan.FFmpeg
```

Para transcribir URLs de YouTube también necesitas yt-dlp:

```
pip install yt-dlp
```

## Instalación

### 1. Copiar el archivo de configuración

```bash
cp .env.example .env
```

Abre `.env` y pon tu `GEMINI_API_KEY`.  
La consigues en <https://aistudio.google.com/app/apikey>.

### 2. Instalar dependencias de Python

```bash
pip install -r backend/requirements.txt
```

### 3. Instalar dependencias del frontend

```bash
cd frontend
npm install
```

## Levantar la aplicación

Necesitas **tres terminales** abiertas al mismo tiempo.

**Terminal 1 — Redis**

```bash
docker compose up -d
```

**Terminal 2 — Gateway (FastAPI)**

```bash
python -m backend.run_gateway
```

**Terminal 3 — Frontend**

```bash
cd frontend
npm run dev
```

## Uso

### Transcribir un video o stream (forma más fácil)

Abre **http://localhost:5173/transcribe**, pega la URL del video (YouTube, enlace directo, HLS…), elige el idioma de salida y haz clic en **"Iniciar transcripción"**.

Idiomas disponibles: Original · Español · English · 中文 (traducción en tiempo real vía Gemini).

### Viewer en vivo (stage fijo)

Abre **http://localhost:5173** — muestra la transcripción del Stage 1 en tiempo real.

Para usar otro stage o fuente de audio, levanta un worker manualmente:

```bash
python -m backend.run_worker --source ./fixtures/sample.mp4 --lang es --stage 1
```

| Flag            | Default       | Descripción                                  |
| --------------- | ------------- | -------------------------------------------- |
| `--source`      | _(requerido)_ | Archivo o URL del stream                     |
| `--stage`       | `1`           | ID del stage                                 |
| `--lang`        | `es`          | Idioma de la fuente                          |
| `--output-lang` | _(ninguno)_   | Traducir a este idioma (`es`, `en`, `zh`)    |
| `--no-loop`     | _(flag)_      | Reproducir una sola vez en lugar de en bucle |

### OBS Browser Source (subtítulos)

1. En OBS: **Fuentes → + → Navegador**
2. URL: `http://localhost:5173/obs?stage=1&lang=es`
3. Resolución: `1920 × 1080`

El fondo es transparente automáticamente. Los subtítulos aparecen en la parte inferior centrados.

Para ajustar posición o tamaño desde el CSS personalizado de OBS:

```css
.obs-overlay {
  bottom: 160px;
} /* subir el texto */
.obs-line {
  font-size: 48px;
} /* texto más grande */
```

### Dashboard de producción

Abre **http://localhost:5173/dashboard**.

Requiere configurar `DASHBOARD_TOKEN` en el `.env` — es la contraseña de acceso al dashboard. Ejemplo:

```
DASHBOARD_TOKEN=mi-password-secreto
```

Desde el dashboard puedes ver el estado de todos los stages, silenciarlos y ver métricas de latencia en tiempo real.

## Exportar transcripciones

```bash
# WebVTT
curl http://localhost:8000/stages/1/transcript.vtt -o stage1.vtt

# SRT
curl http://localhost:8000/stages/1/transcript.srt -o stage1.srt
```

## Glosario dinámico

Cada stage puede tener términos técnicos que Gemini respetará al transcribir:

```bash
# Agregar términos
curl -X PUT http://localhost:8000/stages/1/glossary \
  -H "Content-Type: application/json" \
  -d '{"terms": ["Kubernetes", "PostgreSQL", "WebAssembly"]}'

# Ver términos actuales
curl http://localhost:8000/stages/1/glossary

# Eliminar glosario
curl -X DELETE http://localhost:8000/stages/1/glossary
```

El worker recarga el glosario en cada reconexión con Gemini.

## URLs del sistema

| URL                                 | Descripción                        |
| ----------------------------------- | ---------------------------------- |
| `http://localhost:5173/transcribe`  | Transcribir cualquier video/stream |
| `http://localhost:5173/`            | Viewer del Stage 1                 |
| `http://localhost:5173/obs?stage=1` | Overlay para OBS                   |
| `http://localhost:5173/dashboard`   | Dashboard de producción            |
| `http://localhost:8000/health`      | Health check del backend           |

## Estructura del proyecto

```
transcribe-ia/
├── backend/
│   ├── shared/          config.py, models.py
│   ├── workers/         audio.py, gemini.py, worker.py
│   ├── gateway/         main.py, ws_manager.py, redis_sub.py,
│   │                    session_manager.py, stage_state.py,
│   │                    transcript_export.py
│   ├── run_worker.py
│   ├── run_gateway.py
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── hooks/       useTranscript.ts
│       ├── pages/       Viewer.tsx, Transcribe.tsx, OBS.tsx, Dashboard.tsx
│       └── types/       events.ts
├── fixtures/            pon aquí tus archivos de audio/video de prueba
├── docker-compose.yml   Redis
└── .env.example
```

## Licencia

Apache 2.0
