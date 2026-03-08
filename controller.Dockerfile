FROM python:3.12-alpine

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
RUN apk add --no-cache docker-cli

WORKDIR /app
COPY pyproject.toml /app/pyproject.toml
COPY gluetun_picker /app/gluetun_picker
COPY worker.Dockerfile /app/worker.Dockerfile

RUN uv sync

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_CACHE_DIR=/tmp/uv-cache

ENTRYPOINT ["uv", "run", "python", "-m", "gluetun_picker"]
