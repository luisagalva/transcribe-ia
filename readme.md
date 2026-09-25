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

### Adding the source

1. Open OBS → **Sources panel** → click **+** → choose **Browser**.
2. Give it a name, e.g. `transcribe-ia stage 1`.
3. Fill in the settings exactly as follows:

| Setting | Value |
|---------|-------|
| **URL** | `http://localhost:5173/obs?stage=1&lang=es` |
| **Width** | `1920` |
| **Height** | `1080` |
| **Frame rate** | `30` (24 is fine too — the page has no motion other than text) |
| **Use custom frame rate** | ✅ checked |
| **Shutdown source when not visible** | ✅ recommended (saves CPU) |
| **Refresh browser when scene becomes active** | ✅ recommended |
| **Custom CSS** | *(leave blank — not needed)* |

4. Click **OK**.
5. The source will show transparent except for the subtitle text at the bottom of the frame.

> **The page handles its own transparent background** — you do not need to tick "Allow transparency" because the `<html>` and `<body>` backgrounds are set to `transparent` by the page itself.

### Customising per stage / language

Change the query parameters in the URL:

| Parameter | Default | Example |
|-----------|---------|---------|
| `stage`   | `1`     | `?stage=2` — connects to the stage 2 worker |
| `lang`    | `es`    | `&lang=en` — sent to the gateway for filtering |

Example for stage 2, English:
```
http://localhost:5173/obs?stage=2&lang=en
```

Duplicate the Browser Source in OBS to show multiple stages simultaneously in the same scene.

### What the page does automatically

- **Reconnects** on WebSocket disconnect with exponential back-off (1 s → 10 s max).
- **Loads history** — the last 30 final lines from Redis are fetched on connect, so the overlay is not blank after a brief disconnect.
- **Shows 2 final lines + 1 partial** — older lines scroll off automatically.
- **No cursor, no UI chrome** — the page renders only subtitle text.

### Positioning tips

- The text sits **40 px from the bottom**, centered, with a maximum width of the full frame minus 96 px of horizontal padding.
- To move the text up (e.g. above a lower-third graphic), add `Custom CSS` in OBS:
  ```css
  .obs-overlay { bottom: 160px; }
  ```
- To increase font size:
  ```css
  .obs-line { font-size: 48px; }
  ```
- To show only 1 line instead of 2, reduce `VISIBLE_FINALS` in `frontend/src/pages/OBS.tsx` and rebuild.

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

windows correr en local instalar

winget install ffmpeg
winget install Gyan.FFmpeg
