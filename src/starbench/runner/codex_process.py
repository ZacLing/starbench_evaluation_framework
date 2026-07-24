"""DEPRECATED compatibility shim — do not add new code here.

This module used to hold every runtime's command construction, env preparation,
docker wrapping, and output parsing. That logic now lives in its proper home:

- generic process/docker/parsing → ``starbench.execution`` (process, docker, parsers)
- per-runtime command/env/docker → ``starbench.adapters`` (codex, claude, gemini,
  grok, opencode, spec) and the derived ``DEFAULT_DOCKER_IMAGES`` in
  ``starbench.adapters.registry``

The names below are re-exported so existing importers (``gui/*`` and the test
suite) keep working unchanged and with identical behaviour. New callers should
import from ``starbench.execution`` / ``starbench.adapters`` directly; this shim
is scheduled for removal a release after the migration settles.
"""

from __future__ import annotations

# -- execution primitives ---------------------------------------------------
from ..execution.process import (  # noqa: F401
    _pump_stream,
    mark_failed,
    run_cli_process,
    split_command,
)
from ..execution.docker import (  # noqa: F401
    _kill_container_on_timeout,
    build_docker_agent_command,
    kill_container_on_timeout,
)
from ..execution.parsers import (  # noqa: F401
    _CLAUDE_FILE_CHANGE_TOOLS,
    _claude_tool_result_text,
    _extract_claude_payload,
    _extract_headless_response_text,
    _extract_json_object,
    _extract_last_agent_message_text,
    _extract_opencode_session_id,
    _extract_opencode_text,
    _extract_opencode_text_from_events,
    _load_headless_json,
    _load_opencode_export,
    _raise_on_claude_error_result,
    _read_jsonl_events,
    append_claude_compat_events,
    append_opencode_compat_events,
    normalize_custom_events,
    normalize_headless_events,
    write_claude_final_output,
    write_claude_stream_final_output,
    write_custom_final_output,
    write_headless_final_output,
    write_opencode_final_output,
)

# -- per-runtime adapters ---------------------------------------------------
from ..adapters.codex import (  # noqa: F401
    CODEX_DOCKER_ENV_WHITELIST,
    build_codex_exec_command,
    build_docker_codex_command,
    prepare_auth_home,
    prepare_isolated_auth_home,
    run_codex_process_in_docker,
)
from ..adapters.claude import (  # noqa: F401
    CLAUDE_DOCKER_ENV_WHITELIST,
    build_claude_docker_command,
    build_claude_print_command,
    prepare_claude_env,
    run_claude_process_in_docker,
)
from ..adapters.gemini import (  # noqa: F401
    GEMINI_DOCKER_ENV_WHITELIST,
    build_gemini_docker_command,
    build_gemini_headless_command,
    prepare_gemini_env,
    run_gemini_process_in_docker,
)
from ..adapters.grok import (  # noqa: F401
    GROK_DOCKER_ENV_WHITELIST,
    build_grok_docker_command,
    build_grok_headless_command,
    prepare_grok_env,
    run_grok_process_in_docker,
)
from ..adapters.opencode import (  # noqa: F401
    OPENCODE_DOCKER_ENV_WHITELIST,
    _opencode_inline_config_content,
    _opencode_model_id,
    build_opencode_docker_command,
    build_opencode_run_command,
    opencode_docker_export_env,
    prepare_opencode_env,
    run_opencode_process_in_docker,
)
from ..adapters.spec import (  # noqa: F401
    build_custom_command,
    build_custom_docker_command,
    run_custom_process_in_docker,
)

# -- derived tables ---------------------------------------------------------
from ..adapters.registry import DEFAULT_DOCKER_IMAGES  # noqa: F401

# -- historical process-runner alias ----------------------------------------
# The generic process runner was renamed ``run_codex_process`` -> ``run_cli_process``.
# Keep the old name importable from this shim so existing callers stay unaffected.
run_codex_process = run_cli_process
