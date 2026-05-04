FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Install dependencies first (layer-cached unless pyproject/lock changes)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy application code
COPY alembic/ alembic/
COPY alembic.ini .
COPY app/ app/
COPY frontend/ frontend/
COPY start.sh .

RUN chmod +x start.sh

EXPOSE 8000

CMD ["./start.sh"]
