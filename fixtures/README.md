# fixtures/

Put your test audio or video file here.

FFmpeg supports: `.mp4`, `.mkv`, `.mp3`,

Example command to start the worker with a local file:

```bash
python -m backend.run_worker --source fixtures/sample.mp4 --lang es
```

If you don't have a file, you can use `ffmpeg -f lavfi` to generate a test tone:

```bash
# generates a 440 Hz sine wave — good to test the pipeline without a real audio file
ffmpeg -f lavfi -i "sine=frequency=440:duration=3600" -ar 16000 -ac 1 fixtures/tone.wav
```
