# transcribe-ia

Plataforma de transcripción y traducción simultánea en tiempo real para conferencias de tecnología, con subtítulos listos para OBS.

**Stack:** Python · FastAPI · Gemini Live API · Redis Pub/Sub · WebSockets · React · TypeScript

## Instalación

Requisitos: Python 3.11+, Node.js 18+, Docker y FFmpeg en el PATH (en Windows: `winget install Gyan.FFmpeg`).

```bash
cp .env.example .env                     # pon tu GEMINI_API_KEY
pip install -r backend/requirements.txt
cd frontend && npm install
```

La `GEMINI_API_KEY` se obtiene en <https://aistudio.google.com/app/apikey>.

## Levantar la aplicación

Desde la raíz del proyecto:

```bash
# Redis (queda corriendo en segundo plano)
docker compose up -d

# Terminal 1 — Gateway en http://localhost:8000
python -m backend.run_gateway

# Terminal 2 — Frontend en http://localhost:5173
cd frontend && npm run dev
```

Con esto la app ya está arriba, pero no transcribe nada hasta que levantes al menos un **worker**. Cada worker toma una fuente de audio (un archivo o tu micrófono) y la publica en un **stage**. Hay dos maneras de usarlo:

- [Probar los workers con los audios de `fixtures/`](#probar-los-workers-con-los-audios-de-fixtures)
- [Transmitir en vivo con OBS](#transmitir-en-vivo-con-obs)

## Probar los workers con los audios de `fixtures/`

Hay tres audios de prueba, uno por idioma: `test_es.mp3`, `test_en.mp3` y `test_ch.mp3`.

**1. Copia los audios de `media/` a `fixtures/`:**

```bash
# Bash / Git Bash
cp media/*.mp3 fixtures/

# PowerShell
Copy-Item media/*.mp3 fixtures/
```

**2. Levanta un worker por audio**, cada uno en su propia terminal y en su **propio stage**, para ver varios workers transcribiendo y traduciendo en paralelo:

```bash
# Terminal 3 — Español, stage 1
python -m backend.run_worker --stage 1 --source fixtures/test_es.mp3 --lang es --target-langs en,zh

# Terminal 4 — Inglés, stage 2
python -m backend.run_worker --stage 2 --source fixtures/test_en.mp3 --lang en --target-langs es,zh

# Terminal 5 — Chino, stage 3
python -m backend.run_worker --stage 3 --source fixtures/test_ch.mp3 --lang zh --target-langs es,en
```

Los audios se repiten en bucle. Agrega `--no-loop` si quieres que cada uno se reproduzca una sola vez.

**3. Verifica el resultado:**

1. **Monitor** en <http://localhost:5173/>: aparecen los stages 1, 2 y 3 activos, con su latencia, sus idiomas y el último texto transcrito.
2. **Subtítulos por stage:** abre `http://localhost:5173/obs?stage=N&lang=X`. Usa `lang=original` para el texto en el idioma del audio, o uno de los idiomas de `--target-langs` para ver la traducción. Por ejemplo:
   - `http://localhost:5173/obs?stage=2&lang=original` muestra el inglés original.
   - `http://localhost:5173/obs?stage=2&lang=es` muestra la traducción al español.
3. **Aislamiento:** detén un worker con `Ctrl+C`. Los otros dos siguen transcribiendo, porque cada worker es un proceso independiente.

## Transmitir en vivo con OBS

### 1. Levantar un worker con tu micrófono

Busca el nombre exacto de tu micrófono:

```bash
ffmpeg -list_devices true -f dshow -i dummy 2>&1
```

Copia el nombre de la línea que termina en `(audio)`, por ejemplo `"Micrófono (Logitech PRO X Wireless Gaming Headset)"`, y úsalo en `--source` con el prefijo `audio=`:

```bash
python -m backend.run_worker --stage 1 --source "audio=Micrófono (Logitech PRO X Wireless Gaming Headset)" --lang es --target-langs en --no-loop
```

`--no-loop` es obligatorio con audio en vivo.

### 2. Agregar los subtítulos como Browser Source

En OBS: **Fuentes → `+` → Navegador** y configura:

| Campo                                     | Valor                                       |
| ----------------------------------------- | ------------------------------------------- |
| URL                                       | `http://localhost:5173/obs?stage=1&lang=en` |
| Ancho × Alto                              | `1920 × 1080`                               |
| Shutdown source when not visible          | ✅ Activado                                 |
| Refresh browser when scene becomes active | ✅ Activado                                 |

- `lang` elige el idioma de los subtítulos: `original` o cualquiera de los idiomas que pasaste en `--target-langs` (`es`, `en`, `zh`, `pt`).
- El fondo es transparente y los subtítulos aparecen centrados en la parte inferior.
- Arrastra el Browser Source a la **primera posición** de la lista de fuentes para que los subtítulos queden encima de todo.

Para cambiar la posición o el tamaño, usa el campo **CSS personalizado** de la fuente:

```css
.obs-overlay {
  bottom: 160px;
} /* subir el texto */
.obs-line {
  font-size: 48px;
} /* texto más grande */
```

### 3. Transmitir

Configura tu destino normalmente en **Ajustes → Emisión** (YouTube, Twitch, etc.). Los subtítulos se incluyen en lo que OBS transmite.

## Referencia

### Flags del worker

| Flag             | Default                       | Descripción                                        |
| ---------------- | ----------------------------- | -------------------------------------------------- |
| `--source`       | _(requerido)_                 | Archivo, URL del stream o `audio=<micrófono>`      |
| `--stage`        | `1`                           | ID del stage (uno distinto por worker)             |
| `--lang`         | `es`                          | Idioma del audio                                   |
| `--target-langs` | `DEFAULT_TARGET_LANGS` (.env) | Idiomas a traducir, separados por coma: `en,zh,pt` |
| `--no-loop`      | _(flag)_                      | Reproducir una sola vez en lugar de en bucle       |

### URLs

| URL                                             | Descripción                     |
| ----------------------------------------------- | ------------------------------- |
| `http://localhost:5173/`                        | Monitor de todos los stages     |
| `http://localhost:5173/obs?stage=N&lang=X`      | Subtítulos para OBS             |
| `http://localhost:8000/health`                  | Health check del backend        |
| `http://localhost:8000/stages/N/transcript.vtt` | Exportar transcripción (WebVTT) |
| `http://localhost:8000/stages/N/transcript.srt` | Exportar transcripción (SRT)    |

Los endpoints de exportación aceptan `?lang=X` para descargar una traducción.

### Glosario

Cada stage puede tener términos técnicos que Gemini respeta al transcribir. El worker los recarga cada vez que se reconecta con Gemini.

```bash
curl -X PUT http://localhost:8000/stages/1/glossary \
  -H "Content-Type: application/json" \
  -d '{"terms": ["Kubernetes", "PostgreSQL", "WebAssembly"]}'

curl http://localhost:8000/stages/1/glossary            # ver términos
curl -X DELETE http://localhost:8000/stages/1/glossary  # borrar glosario
```

### Estructura del proyecto

```
backend/
  gateway/   API FastAPI y WebSockets
  workers/   captura con FFmpeg, transcripción y traducción con Gemini
  shared/    configuración y modelos
  media/     audios de prueba originales (se copian a fixtures/)
frontend/    React + Vite (Monitor y overlay de OBS)
fixtures/    audios que usan los workers
```

## Licencia

Este proyecto se distribuye bajo la licencia [Apache 2.0](LICENSE).
