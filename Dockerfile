FROM python:3.15-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE NOTICE alembic.ini ./
COPY src ./src
COPY migrations ./migrations
RUN uv sync --locked --no-dev

RUN useradd --system --no-create-home volty
USER volty
ENV PATH="/app/.venv/bin:$PATH"

CMD ["sh", "-c", "alembic upgrade head && exec volty"]
