from abc import ABC, abstractmethod


class VisionProvider(ABC):
    @abstractmethod
    async def analyze(self, image_data: bytes | None, prompt: str) -> str:
        """Send image + prompt to the vision model, return raw text response.
        If image_data is None, send text-only prompt.
        """

    @abstractmethod
    async def is_available(self) -> bool:
        """Check if the provider is configured and reachable."""
