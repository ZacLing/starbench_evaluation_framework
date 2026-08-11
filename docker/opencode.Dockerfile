# glibc base: the opencode npm package ships a platform binary that is not
# built for musl.
FROM node:22-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN npm install -g opencode-ai

WORKDIR /workspace
