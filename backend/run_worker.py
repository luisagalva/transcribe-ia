"""Entry point: python -m backend.run_worker --source ./fixtures/sample.mp4"""
from __future__ import annotations

import argparse
import asyncio
import logging

from backend.shared.config import settings
from backend.workers.worker import StageWorker


def main() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="transcribe-ia worker")
    parser.add_argument("--stage", type=int, default=1, help="Stage ID (default: 1)")
    parser.add_argument("--source", required=True, help="Audio/video file or stream URL")
    parser.add_argument("--lang", default="es", help="Language code, e.g. es, en (default: es)")
    parser.add_argument("--no-loop", action="store_true", help="Play source once (don't loop)")
    parser.add_argument(
        "--output-lang",
        default=None,
        help="Translate output to this language (es/en/zh). Default: transcribe as-is.",
    )
    args = parser.parse_args()

    worker = StageWorker(
        stage_id=args.stage,
        source=args.source,
        lang=args.lang,
        loop_audio=not args.no_loop,
        output_lang=args.output_lang,
    )

    try:
        asyncio.run(worker.run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
