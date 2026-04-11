import logging
from typing import Any

from google import genai

from bot.config import settings

logger = logging.getLogger(__name__)

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


async def generate_embedding(text: str) -> list[float] | None:
    """Generate embedding vector for a text description using Gemini."""
    try:
        client = _get_client()
        result = await client.aio.models.embed_content(
            model=settings.embedding_model,
            contents=text,
            config={"output_dimensionality": settings.embedding_dimensions},
        )
        return list(result.embeddings[0].values)
    except Exception:
        logger.exception("Failed to generate embedding")
        return None


def build_meal_text(
    description: str,
    items: list[dict[str, Any]],
    totals: dict[str, float],
) -> str:
    """Build text representation of a meal for embedding generation."""
    parts = [description]
    for item in items:
        name = item.get("name", "")
        grams = item.get("grams", item.get("grams_min", ""))
        if name:
            parts.append(f"{name} {grams}г" if grams else name)
    parts.append(
        f"Итого: {int(totals.get('calories', 0))} ккал, "
        f"Б:{int(totals.get('protein', 0))}г "
        f"Ж:{int(totals.get('fat', 0))}г "
        f"У:{int(totals.get('carbs', 0))}г"
    )
    return " | ".join(parts)
