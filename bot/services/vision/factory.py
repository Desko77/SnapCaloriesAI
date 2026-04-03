import logging

from bot.config import settings
from bot.services.vision.base import VisionProvider
from bot.services.vision.gemini import GeminiProvider
from bot.services.vision.openai_compat import OpenAICompatProvider

logger = logging.getLogger(__name__)

PROVIDERS: dict[str, type[VisionProvider]] = {
    "gemini": GeminiProvider,
    "openai_compat": OpenAICompatProvider,
}


class FallbackVisionProvider(VisionProvider):
    """Tries primary provider first, falls back to secondary on failure."""

    def __init__(self, primary: VisionProvider, fallback: VisionProvider | None):
        self._primary = primary
        self._fallback = fallback

    async def analyze(self, image_data: bytes | None, prompt: str) -> str:
        try:
            return await self._primary.analyze(image_data, prompt)
        except Exception as exc:
            if self._fallback is None:
                raise
            logger.warning("Primary provider failed (%s), trying fallback", exc)
            return await self._fallback.analyze(image_data, prompt)

    async def is_available(self) -> bool:
        primary_ok = await self._primary.is_available()
        fallback_ok = await self._fallback.is_available() if self._fallback else False
        return primary_ok or fallback_ok


def create_vision_provider() -> VisionProvider:
    primary_cls = PROVIDERS.get(settings.vision_provider)
    if primary_cls is None:
        raise ValueError(f"Unknown vision provider: {settings.vision_provider}")

    fallback_cls = PROVIDERS.get(settings.vision_fallback)
    fallback = fallback_cls() if fallback_cls else None

    return FallbackVisionProvider(primary_cls(), fallback)
