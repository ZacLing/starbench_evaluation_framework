# Kimi Code CLI reads providers from ~/.kimi/config.toml; a wrapper seeds the
# baked config into $HOME at startup, and OPENAI_BASE_URL / OPENAI_API_KEY
# override its endpoint and key at run time. The model is fixed in
# docker/kimi-config.toml (kimi has no model flag).
FROM python:3.13-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv \
    && uv tool install --python 3.13 kimi-cli

COPY docker/kimi-config.toml /opt/kimi/config.toml
COPY docker/kimi-entry.sh /usr/local/bin/kimi
RUN chmod +x /usr/local/bin/kimi

ENV PATH="/usr/local/bin:/root/.local/bin:${PATH}"

WORKDIR /workspace
