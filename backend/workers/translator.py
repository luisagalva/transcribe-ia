"""GeminiTranslator: translates transcript segments using the standard Gemini API."""
from __future__ import annotations

import logging

from google import genai

from backend.shared.config import settings

logger = logging.getLogger(__name__)

LANG_NAMES: dict[str, str] = {
    "es": "Spanish",
    "en": "English",
    "zh": "Chinese (Simplified)",
    "pt": "Portuguese",
}

SUPPORTED_TARGET_LANGS = set(LANG_NAMES.keys())


class GeminiTranslator:
    """
    Translates short text snippets (subtitle segments) to a target language.
    Uses the standard (non-streaming) Gemini API so it can run concurrently
    alongside the live transcription session.
    """

    def __init__(self) -> None:
        self._client = genai.Client(api_key=settings.gemini_api_key)

    async def translate(self, text: str, target_lang: str) -> str:
        lang_name = LANG_NAMES.get(target_lang, target_lang)
        prompt = (
            f"You are a professional subtitle translator. "
            f"Translate the following spoken text to {lang_name}. "
            f"Output ONLY the translation — no explanation, no quotes. "
            f"Keep proper nouns, technical terms, and brand names unchanged. "
            f"Match the length and register of the original.\n\n"
            f"{text}"
        )
        response = await self._client.aio.models.generate_content(
            model=settings.gemini_translation_model,
            contents=prompt,
        )
        result = (response.text or "").strip()
        logger.debug("Translated [%s] %r → %r", target_lang, text[:60], result[:60])
        return result
