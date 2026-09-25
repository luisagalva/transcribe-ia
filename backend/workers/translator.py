"""GeminiTranslator: translates transcript segments using the standard Gemini API."""
from __future__ import annotations

import asyncio
import logging
import random

from google import genai
from google.genai import types

from backend.shared.config import settings

logger = logging.getLogger(__name__)

LANG_NAMES: dict[str, str] = {
    "es": "Spanish",
    "en": "English",
    "zh": "Chinese (Simplified)",
    "pt": "Portuguese",
}

SUPPORTED_TARGET_LANGS = set(LANG_NAMES.keys())

_GENERATE_CONFIG = types.GenerateContentConfig(
    temperature=0.0,
    max_output_tokens=256,
    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
)

# Fallback model when the primary is unavailable (503)
_FALLBACK_MODEL = "gemini-3.8-flash-lite"


class GeminiTranslator:
    def __init__(self) -> None:
        self._client = genai.Client(api_key=settings.gemini_api_key)

    async def translate(self, text: str, target_lang: str, retries: int = 5) -> str:
        lang_name = LANG_NAMES.get(target_lang, target_lang)
        prompt = (
            f"You are a professional subtitle translator. "
            f"Translate the following spoken text to {lang_name}. "
            f"Output ONLY the translation — no explanation, no quotes. "
            f"Keep proper nouns, technical terms, and brand names unchanged. "
            f"Match the length and register of the original.\n\n"
            f"{text}"
        )
        delay = 1.0
        model = settings.gemini_translation_model
        for attempt in range(retries):
            try:
                response = await self._client.aio.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=_GENERATE_CONFIG,
                )
                result = (response.text or "").strip()
                logger.debug("Translated [%s] %r → %r", target_lang, text[:60], result[:60])
                return result
            except Exception as exc:
                is_last = attempt == retries - 1
                if is_last:
                    raise
                # On 503 switch to fallback model for next attempt
                if "503" in str(exc) or "UNAVAILABLE" in str(exc):
                    model = _FALLBACK_MODEL
                jitter = random.uniform(0, delay * 0.3)
                logger.warning(
                    "Translation to %s failed (attempt %d/%d, model=%s): %s — retrying in %.1fs",
                    target_lang, attempt + 1, retries, model, exc, delay + jitter,
                )
                await asyncio.sleep(delay + jitter)
                delay *= 2
        return text  # unreachable
