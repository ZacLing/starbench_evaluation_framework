"""Compatibility façade for split experiment application services."""

from .services.errors import ExperimentError
from .services.profiles import (
    BUILTIN_PROFILE, BUILTIN_PROFILE_HSW_FRONTIER, BUILTIN_PROFILES,
    PER_CONTENDER_FIELD_CHOICES, ROSTER_ENTRY_FIELDS, TASK_SET_FIELDS,
    load_profiles, profiles_path, save_profiles,
)
from .services.planning_inputs import (
    DOCKER_CAPABLE_AGENTS, INSTRUCTION_MODES, JUDGE_ENV_SENSITIVE,
    PROMPT_THINKING_EFFORTS, RIGOR_MODES, THINKING_EFFORTS_BY_AGENT,
)
from .services.planning import plan_experiment
from .services.records import (
    experiment_detail, experiments_dir, list_experiments, record_experiment,
)

__all__ = [name for name in globals() if not name.startswith("__")]
