FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY src/ ./src/
COPY main.py ./

ENV PYTHONPATH=/app/src

RUN uv sync --frozen --no-dev
RUN mkdir -p /data

EXPOSE 8300

ENTRYPOINT ["uv", "run", "--no-sync", "python", "main.py", "--start"]
