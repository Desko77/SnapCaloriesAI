from abc import ABC, abstractmethod


class VisionProvider(ABC):
    @abstractmethod
    async def analyze(self, image_data: bytes | list[bytes] | None, prompt: str) -> str:
        """Send image(s) + prompt to the vision model, return raw text response.
        image_data can be:
          - None: text-only prompt
          - bytes: single image
          - list[bytes]: multiple images (album/media group)
        """

    @abstractmethod
    async def is_available(self) -> bool:
        """Check if the provider is configured and reachable."""
