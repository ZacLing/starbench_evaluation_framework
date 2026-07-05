"""Compatibility shim for the split runner — re-exports the public surface.

The benchmark runner used to live entirely in this file. It is now split by
responsibility so a single change touches one small module:

- ``runner/cli.py``          argparse + ``main`` (the ``starbench-run`` entry point)
- ``runner/orchestrator.py`` the run loop, batching, progress, summaries
- ``runner/executor.py``     per-task materialize / skill install / executor dispatch
- ``runner/judge.py``        single & parallel judge dispatch + aggregation
- ``runner/env_scope.py``    prefix-scoped executor/judge env isolation

Everything the old module exposed is re-exported here so existing importers and
``python -m starbench.runner.run_benchmark`` keep working unchanged. The console
script ``starbench-run = starbench.runner.run_benchmark:main`` stays valid via
the ``main`` re-export. New callers should import from the module that owns the
symbol; this shim is scheduled for removal a release after the split settles.

改什么来这里: nothing — add code to the owning module above and re-export it here.
"""

from __future__ import annotations

# -- CLI ---------------------------------------------------------------------
from .cli import (  # noqa: F401
    DEFAULT_EXECUTOR_SKILLS_DIR,
    DEFAULT_RUNS_DIR,
    DEFAULT_RUNTIMES_DIR,
    DEFAULT_TASKS_DIR,
    PROJECT_ROOT,
    main,
    parse_args,
)

# -- executor side -----------------------------------------------------------
from .executor import (  # noqa: F401
    IGNORED_EXECUTOR_SKILL_NAMES,
    copy_task_material,
    hash_executor_skill_directory,
    install_executor_skills,
    json_dump,
    materialize_task,
    run_executor,
)

# -- judge side --------------------------------------------------------------
from .judge import (  # noqa: F401
    SCHEMAS_DIR,
    prepare_evaluator_workspace,
    rubric_launch_order,
    run_parallel_judges,
    run_single_judge,
)

# -- orchestration -----------------------------------------------------------
from .orchestrator import (  # noqa: F401
    executor_timing_from_status,
    make_run_task_ids,
    run_benchmark,
)
from .summary import (  # noqa: F401
    build_instruction_ablation_summary,
    format_instruction_ablation_markdown,
)

# -- prompt builders (historically re-exported through this module) ----------
from .prompts import (  # noqa: F401
    OPENCODE_JUDGE_AGENT,
    build_augmented_prompt_text,
    build_executor_prompt,
    build_parallel_judge_prompt,
    build_single_judge_prompt,
    claude_executor_allowed_tools,
    opencode_model_name,
)

# -- adapters / registry (historically imported at module scope) -------------
from ..adapters import (  # noqa: F401
    BUILTIN_AGENTS,
    DEFAULT_DOCKER_IMAGES,
    ExecutorContext,
    JudgeContext,
    RuntimeAdapter,
    get_builtin,
    resolve,
)


if __name__ == "__main__":
    raise SystemExit(main())
