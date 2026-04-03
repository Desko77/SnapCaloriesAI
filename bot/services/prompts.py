from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"

_env = Environment(
    loader=FileSystemLoader(str(PROMPTS_DIR)),
    keep_trailing_newline=True,
)


def render_prompt(template_name: str, **context: Any) -> str:
    template = _env.get_template(template_name)
    return template.render(**context)
