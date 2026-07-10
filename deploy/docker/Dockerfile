# Easy Breezy server. Сборка из корня репозитория:
#   docker build -f deploy/docker/Dockerfile -t easy-breezy .
# UI собирается заранее (make build-ui) и попадает в образ из ui/dist.

FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app/server
COPY server/pyproject.toml server/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY server/src ./src
RUN uv sync --frozen --no-dev

COPY ui/dist /app/ui/dist

ENV PATH="/app/server/.venv/bin:$PATH"
CMD ["python", "-m", "easy_breezy"]
