FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-editable

COPY bot/ bot/
COPY prompts/ prompts/
COPY alembic/ alembic/
COPY alembic.ini .

RUN mkdir -p data

CMD ["sh", "-c", "uv run alembic upgrade head && uv run python -m bot"]
