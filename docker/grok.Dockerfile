# Grok Build installs via xAI's shell installer (no npm package).
# If the installer's target directory changes, adjust the PATH below —
# verify with `docker run --rm starbench-grok:latest grok --version`.
FROM node:22-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash python3 curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://x.ai/cli/install.sh | bash

ENV PATH="/root/.grok/bin:/root/.local/bin:/usr/local/bin:${PATH}"

WORKDIR /workspace
