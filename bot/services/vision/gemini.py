import logging

from google import genai
from google.genai import types

from bot.config import settings
from bot.services.vision.base import VisionProvider

logger = logging.getLogger(__name__)


class GeminiProvider(VisionProvider):
    def __init__(self):
        if settings.gemini_api_key:
            self._client = genai.Client(api_key=settings.gemini_api_key)
        else:
            self._client = None

    async def analyze(self, image_data: bytes | None, prompt: str) -> str:
        if self._client is None:
            raise RuntimeError("Gemini API key not configured")

        contents: list = [prompt]
        if image_data:
            contents.append(
                types.Part.from_bytes(data=image_data, mime_type="image/jpeg")
            )

        response = await self._client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=contents,
        )
        return response.text

    async def is_available(self) -> bool:
        return self._client is not None
