# Pi (pi.dev) — npm-installed multi-provider coding agent.
# Verify with `docker run --rm starbench-pi:latest pi --version`.
FROM node:22-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash python3 curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN npm install -g --ignore-scripts @earendil-works/pi-coding-agent

WORKDIR /workspace
