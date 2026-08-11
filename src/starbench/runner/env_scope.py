"""Prefix-scoped environment: separate executor and judge env without argv leaks.

The console launches one ``starbench-run`` subprocess that runs *both* a
contender (executor) and a judge. A naive design puts every injected variable
into that one process environment, so a contender's ``OPENAI_BASE_URL`` silently
reroutes an OpenAI-family judge in the same run. To isolate the two sides without
putting secrets on the command line (``ps``-visible) or in plaintext temp files,
the console instead passes injected variables as *prefixed* environment
variables:

    STARBENCH_EXECUTOR_ENV_<VAR>=<value>   -> executor scope only
    STARBENCH_JUDGE_ENV_<VAR>=<value>      -> judge scope only

At startup the runner calls :func:`scoped_base_envs`, which strips those prefix
keys out of the ambient environment and folds each into its own side. The
resulting two base envs seed ``ExecutorContext.base_env`` / ``JudgeContext.base_env``
respectively, replacing the adapters' historical ``os.environ.copy()``.

Invariants:
- A plain (unprefixed) ambient variable stays visible to *both* sides — this is
  what keeps standalone CLI use unchanged: with no prefix vars set, both base
  envs equal the ambient environment.
- The prefix key names themselves never appear in either base env (stripped from
  the clean ambient), so a leaked ``STARBENCH_*_ENV_*`` cannot reach a child
  process.
- Only *values* travel in env vars; nothing is written to argv or to disk.

改什么来这里: the prefix spelling or how scoped variables fold into base envs.
"""

from __future__ import annotations

from typing import Dict, Mapping, Tuple

EXECUTOR_ENV_PREFIX = "STARBENCH_EXECUTOR_ENV_"
JUDGE_ENV_PREFIX = "STARBENCH_JUDGE_ENV_"


def partition_scoped_env(
    environ: Mapping[str, str],
) -> Tuple[Dict[str, str], Dict[str, str], Dict[str, str]]:
    """Split ``environ`` into (clean_ambient, executor_scope, judge_scope).

    ``clean_ambient`` is ``environ`` with every ``STARBENCH_{EXECUTOR,JUDGE}_ENV_*``
    key removed; ``executor_scope`` / ``judge_scope`` map the *stripped* variable
    name to its value (``STARBENCH_EXECUTOR_ENV_FOO`` -> ``FOO``).
    """
    clean: Dict[str, str] = {}
    executor: Dict[str, str] = {}
    judge: Dict[str, str] = {}
    for key, value in environ.items():
        if key.startswith(EXECUTOR_ENV_PREFIX):
            executor[key[len(EXECUTOR_ENV_PREFIX):]] = value
        elif key.startswith(JUDGE_ENV_PREFIX):
            judge[key[len(JUDGE_ENV_PREFIX):]] = value
        else:
            clean[key] = value
    return clean, executor, judge


def scoped_base_envs(environ: Mapping[str, str]) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Return (executor_base_env, judge_base_env) for adapter env construction.

    Each is the clean ambient environment overlaid with its own side's scoped
    variables. With no prefix variables present both equal the ambient env, so
    standalone CLI behaviour is unchanged.
    """
    clean, executor, judge = partition_scoped_env(environ)
    return {**clean, **executor}, {**clean, **judge}
