# transcribe-ia

Real-time simultaneous transcription platform for tech conferences.

**Stack:** Python · FastAPI · Gemini Live API · Redis Pub/Sub · WebSockets · React · TypeScript

## Architecture (MVP)

```
audio file
  └─ FFmpeg (PCM 16kHz)
       └─ Worker (Python)
            └─ Gemini Live API  ──→  transcript tokens
                 └─ Redis PUBLISH
                      └─ Gateway (FastAPI/WS)
                           └─ Browser clients (React)
```

## Prerequisites

| Tool                    | Version             |
| ----------------------- | ------------------- |
| Python                  | 3.11+               |
| Node.js                 | 18+                 |
| Docker & Docker Compose | any recent          |
| FFmpeg                  | installed & on PATH |

## Setup

### 1. Clone and copy env file

```bash
cp .env.example .env
```

Edit `.env` and set your `GEMINI_API_KEY`.  
Get one at <https://aistudio.google.com/app/apikey>.

### 2. Start Redis

```bash
docker compose up -d
```

### 3. Install Python dependencies

```bash
cd backend
pip install -r requirements.txt
cd ..
```

> **Windows tip:** run `pip install -r backend\requirements.txt` from the project root.

### 4. Install frontend dependencies

```bash
cd frontend
npm install
cd ..
```

## Running the project

You need **three terminals** running simultaneously.

### Terminal 1 — Gateway (WebSocket server)

```bash
# from project root
python -m backend.run_gateway
```

Starts on `http://localhost:8000`. Healthcheck: `http://localhost:8000/health`

### Terminal 2 — Worker (audio → Gemini → Redis)

```bash
# Place a video/audio file in fixtures/ first
python -m backend.run_worker --source ./fixtures/sample.mp4 --lang es
```

Options:
| Flag | Default | Description |
|------|---------|-------------|
| `--source` | _(required)_ | File path or stream URL (rtmp://, https://.m3u8, …) |
| `--stage` | `1` | Stage ID |
| `--lang` | `es` | Language code (`es`, `en`, `pt`, …) |
| `--no-loop` | _(flag)_ | Play the file once instead of looping |

### Terminal 3 — Frontend

```bash
cd frontend
npm run dev
```

Opens at <http://localhost:5173>

## URLs

| URL                                         | Description                         |
| ------------------------------------------- | ----------------------------------- |
| `http://localhost:5173/`                    | Main viewer — shows live transcript |
| `http://localhost:5173/obs?stage=1&lang=es` | OBS Browser Source overlay          |
| `ws://localhost:8000/ws?stage=1&lang=es`    | Raw WebSocket endpoint              |
| `http://localhost:8000/health`              | Backend healthcheck                 |

## OBS Browser Source setup

1. In OBS, add a **Browser Source**.
2. URL: `http://localhost:5173/obs?stage=1&lang=es`
3. Width: `1920`, Height: `1080`
4. Enable **"Shutdown source when not visible"** (optional)
5. Check **"Refresh browser when scene becomes active"** (optional)

The page renders white text with a black outline on a **transparent background**. No custom CSS needed in OBS.

## Testing without a real audio file

Generate a 1-hour sine tone (tests the pipeline without spending Gemini quota):

```bash
ffmpeg -f lavfi -i "sine=frequency=440:duration=3600" -ar 16000 -ac 1 fixtures/tone.wav
python -m backend.run_worker --source ./fixtures/tone.wav --lang es
```

Or use any MP4 from your machine — FFmpeg handles the decoding.

## Project structure

```
transcribe-ia/
├── backend/
│   ├── shared/          config.py, models.py
│   ├── workers/         audio.py, gemini.py, worker.py
│   ├── gateway/         main.py, ws_manager.py, redis_sub.py
│   ├── run_worker.py    worker entrypoint
│   ├── run_gateway.py   gateway entrypoint
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── hooks/       useTranscript.ts
│       ├── pages/       Viewer.tsx, OBS.tsx
│       └── types/       events.ts
├── fixtures/            put your test audio/video here
├── docker-compose.yml   Redis
└── .env.example
```

## Extending to multiple stages

The architecture is stage-aware from day one:

- Start additional workers with `--stage 2`, `--stage 3`, etc.
- The OBS overlay uses `?stage=N` to select a stage.
- The frontend `Viewer.tsx` hardcodes `STAGE=1` — add a dropdown to make it dynamic.

## License

Apache 2.0 — see [LICENSE](LICENSE).
