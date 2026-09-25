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

---

## Transmisión en vivo con OBS Studio

Esta sección explica cómo usar **transcribe-ia** como overlay de subtítulos en tiempo real mientras transmites en vivo desde OBS Studio.

### Requisitos previos

#### Instalar FFmpeg (Windows)

```bash
winget install Gyan.FFmpeg
```

Verifica que quedó en el PATH:

```bash
ffmpeg -version
```

#### Encontrar el nombre exacto de tu micrófono

```bash
ffmpeg -list_devices true -f dshow -i dummy 2>&1
```

Busca la línea que dice `(audio)` y copia el nombre exacto, por ejemplo:

```
[dshow] "Micrófono (Logitech PRO X Wireless Gaming Headset)" (audio)
```

Ese nombre es el que usarás en el flag `--source` del worker.

---

### Paso a paso

Abre **cuatro terminales** desde la raíz del proyecto.

**Terminal 1 — Redis**

```bash
docker compose up -d
```

**Terminal 2 — Gateway**

```bash
python -m backend.run_gateway
```

**Terminal 3 — Frontend**

```bash
cd frontend
npm run dev
```

**Terminal 4 — Worker (con tu micrófono)**

Reemplaza el nombre del micrófono por el que obtuviste en el paso anterior:

```bash
python -m backend.run_worker \
  --stage 1 \
  --source "audio=Micrófono (Logitech PRO X Wireless Gaming Headset)" \
  --lang es \
  --target-langs en \
  --no-loop
```

| Flag                | Descripción                                                               |
| ------------------- | ------------------------------------------------------------------------- |
| `--lang es`         | Idioma en el que hablas                                                   |
| `--target-langs en` | Idioma al que traducir (puede ser `en`, `pt`, `zh` o combinados: `en,pt`) |
| `--no-loop`         | Obligatorio para audio en vivo (no archivo)                               |

---

### Configurar OBS Studio

#### 1. Agregar el overlay como Browser Source

1. En OBS: **Fuentes → `+` → Navegador (Browser)**
2. Configura los siguientes valores:

| Campo                                     | Valor                                       |
| ----------------------------------------- | ------------------------------------------- |
| URL                                       | `http://localhost:5173/obs?stage=1&lang=en` |
| Ancho                                     | `1920`                                      |
| Alto                                      | `1080`                                      |
| Shutdown source when not visible          | ✅ Activado                                 |
| Refresh browser when scene becomes active | ✅ Activado                                 |

El parámetro `lang=en` muestra los subtítulos en inglés. Cámbialo según el idioma de tu audiencia.

#### 2. Posicionar la fuente correctamente

> **Importante:** arrastra el Browser Source a la **primera posición** en la lista de fuentes (parte superior del panel). OBS renderiza las fuentes de abajo hacia arriba, por lo que ponerla al tope garantiza que los subtítulos se muestren sobre todo lo demás.

#### 3. Transmitir a plataformas externas

Configura tu destino de stream normalmente en **Ajustes → Emisión** (YouTube, Twitch, etc.). Los subtítulos del overlay se incluyen automáticamente en lo que OBS captura y transmite.

---

### Referencia rápida de URLs del overlay

| URL                                         | Muestra                 |
| ------------------------------------------- | ----------------------- |
| `http://localhost:5173/obs?stage=1&lang=en` | Traducción al inglés    |
| `http://localhost:5173/obs?stage=1&lang=es` | Español original        |
| `http://localhost:5173/obs?stage=1&lang=pt` | Traducción al portugués |
| `http://localhost:5173/obs?stage=1&lang=zh` | Traducción al chino     |

### Dashboard de producción

Abre **http://localhost:5173/dashboard**.

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

| URL                                 | Descripción              |
| ----------------------------------- | ------------------------ |
| `http://localhost:5173/`            | Viewer del Stage 1       |
| `http://localhost:5173/obs?stage=1` | Overlay para OBS         |
| `http://localhost:5173/dashboard`   | Dashboard de producción  |
| `http://localhost:8000/health`      | Health check del backend |

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
