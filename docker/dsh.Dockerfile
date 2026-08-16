# DeepSeek Harness (dsh) — npm-installed, plugin-composed coding harness.
# The headless profile boots from bundles resolved out of the dsh installation
# itself (@deepseek-ai/dsh-app-boot's module fallback), so no pnpm and no
# network access are needed at run time; `dsh plugin` (out-of-tree plugins) is
# the only path that would want pnpm and the benchmark never takes it.
# Verify with `docker run --rm starbench-dsh:latest dsh --version`.
FROM node:22-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash python3 git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN npm install -g @deepseek-ai/dsh@latest

WORKDIR /workspace
