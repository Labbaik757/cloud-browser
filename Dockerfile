# Cloud Browser v1 — Docker image for Render (free web service).
#
# Base image choice: mcr.microsoft.com/playwright/python:v1.64.1-jammy
# (official Playwright image) instead of python:3.12-slim + manual
# `playwright install --with-deps chromium`.
# Why: the official image already has Chromium + all system deps installed
# and version-matched to playwright 1.64.1 (same as requirements.txt and
# the locally tested fbvenv). The slim route re-downloads ~500MB of apt
# packages and is the fragile step that most often fails on free builders.
# Trade-off: this image is large (~2 GB), so the first Render build is slow.
FROM mcr.microsoft.com/playwright/python:v1.64.1-jammy

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py index.html test-page.html ./

# Unpacked extensions to load at browser launch (extensions/<name>/ with
# a manifest.json). Must be copied or the feature silently does nothing.
COPY extensions/ ./extensions/

ENV PYTHONUNBUFFERED=1
# Render sets PORT at runtime; server.py reads it (fallback CLOUD_BROWSER_PORT).
EXPOSE 10000

CMD ["python", "server.py"]
