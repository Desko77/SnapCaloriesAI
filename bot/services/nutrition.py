import json
from typing import Any


def parse_ai_response(raw_response: str) -> dict[str, Any]:
    """Parse JSON response from AI vision model."""
    # Strip markdown code fences if present
    text = raw_response.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # remove opening fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    return json.loads(text)
