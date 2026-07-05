#!/bin/bash
# Kimi reads its providers from $HOME/.kimi/config.toml. HOME points into the
# workspace mount for containerized runs, so seed the baked config on first
# start, then hand over to the real CLI.
set -euo pipefail
mkdir -p "$HOME/.kimi"
if [ ! -f "$HOME/.kimi/config.toml" ]; then
    cp /opt/kimi/config.toml "$HOME/.kimi/config.toml"
fi
exec /root/.local/bin/kimi "$@"
