# Build the web app
FROM node:22-slim AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN mkdir -p ../src/oh_my_ugc && npm run build

# Runtime: Python and ffmpeg (with libass, which draws the captions and text)
FROM python:3.12-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src/ src/
COPY --from=web /app/src/oh_my_ugc/web src/oh_my_ugc/web
RUN uv sync --frozen --no-dev
# Photos, generated media, the database and settings all live in /data.
ENV PATH="/app/.venv/bin:$PATH" \
    OMU_HOME=/data
VOLUME /data
EXPOSE 8000
CMD ["omu", "serve", "--host", "0.0.0.0", "--port", "8000", "--no-open"]
