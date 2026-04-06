import base64
import logging

from openai import AsyncOpenAI

from bot.config import settings
from bot.services.vision.base import VisionProvider

logger = logging.getLogger(__name__)


class OpenAICompatProvider(VisionProvider):
    """OpenAI-compatible provider. Works with OpenAI, OpenRouter, LM Studio, Ollama, etc."""

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        model: str = "",
        reasoning_effort: str = "",
    ):
        key = api_key or settings.openai_api_key
        url = base_url or settings.openai_base_url
        self._model = model or settings.openai_model
        self._reasoning_effort = reasoning_effort or ""
        if key:
            self._client = AsyncOpenAI(api_key=key, base_url=url)
        else:
            self._client = None

    async def analyze(self, image_data: bytes | list[bytes] | None, prompt: str) -> str:
        if self._client is None:
            raise RuntimeError("OpenAI-compatible API not configured")

        content: list[dict] = [{"type": "text", "text": prompt}]
        if image_data:
            images = image_data if isinstance(image_data, list) else [image_data]
            for img in images:
                b64 = base64.b64encode(img).decode("utf-8")
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                })

        extra: dict = {}
        if self._reasoning_effort:
            extra["extra_body"] = {"reasoning_effort": self._reasoning_effort}

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": content}],
            **extra,
        )
        text = response.choices[0].message.content
        if text is None:
            raise RuntimeError(f"AI returned empty response (finish_reason={response.choices[0].finish_reason})")
        return text

    async def is_available(self) -> bool:
        return self._client is not None
