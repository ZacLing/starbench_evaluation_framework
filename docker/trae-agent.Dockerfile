# trae-agent is not on PyPI; the documented install is git clone + uv sync
# (https://github.com/bytedance/trae-agent). Pin a commit for reproducible
# benchmark images if needed.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv
RUN git clone --depth 1 https://github.com/bytedance/trae-agent.git /opt/trae-agent \
    && cd /opt/trae-agent \
    && uv sync

ENV PATH="/opt/trae-agent/.venv/bin:${PATH}"

WORKDIR /workspace
