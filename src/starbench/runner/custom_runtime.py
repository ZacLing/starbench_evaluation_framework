from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

VALID_PARSERS = {"headless-json", "jsonl-events", "text"}
VALID_PROMPT_VIA = {"stdin", "arg"}


@dataclass(frozen=True)
class CustomRuntimeSpec:
    id: str
    command: str
    args: List[str]
    judge_args: List[str]
    model_flag: str | None
    prompt_via: str
    prompt_flag: str
    parser: str
    env: Dict[str, str]
    docker_image: str | None
    docker_env_passthrough: List[str]
    source_path: Path

    def public_metadata(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "command": self.command,
            "args": self.args,
            "judge_args": self.judge_args,
            "model_flag": self.model_flag,
            "prompt_via": self.prompt_via,
            "prompt_flag": self.prompt_flag,
            "parser": self.parser,
            "docker_image": self.docker_image,
            "source_path": str(self.source_path),
        }


def _string_list(value: Any, *, path: Path, key: str) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"Custom runtime {path}: {key} must be a list of strings")
    return list(value)


def load_custom_runtime(runtimes_dir: Path, runtime_id: str) -> CustomRuntimeSpec:
    path = runtimes_dir / f"{runtime_id}.json"
    if not path.exists():
        raise ValueError(f"Missing custom runtime config: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Custom runtime {path} is not valid JSON: {exc}")
    if not isinstance(data, dict):
        raise ValueError(f"Custom runtime {path} must be a JSON object")
    if data.get("id") != runtime_id:
        raise ValueError(
            f"Custom runtime {path}: id {data.get('id')!r} does not match filename {runtime_id!r}"
        )
    command = data.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError(f"Custom runtime {path}: command is required")
    parser = data.get("parser")
    if parser not in VALID_PARSERS:
        raise ValueError(
            f"Custom runtime {path}: parser must be one of {sorted(VALID_PARSERS)}, got {parser!r}"
        )
    prompt_via = data.get("prompt_via", "stdin")
    if prompt_via not in VALID_PROMPT_VIA:
        raise ValueError(
            f"Custom runtime {path}: prompt_via must be one of {sorted(VALID_PROMPT_VIA)}, got {prompt_via!r}"
        )
    env = data.get("env") or {}
    if not isinstance(env, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in env.items()
    ):
        raise ValueError(f"Custom runtime {path}: env must be an object of string values")
    args = _string_list(data.get("args"), path=path, key="args")
    judge_args_value = data.get("judge_args")
    judge_args = args if judge_args_value is None else _string_list(judge_args_value, path=path, key="judge_args")
    model_flag = data.get("model_flag")
    if model_flag is not None and not isinstance(model_flag, str):
        raise ValueError(f"Custom runtime {path}: model_flag must be a string or null")
    docker = data.get("docker")
    docker_image: str | None = None
    docker_env_passthrough: List[str] = []
    if docker is not None:
        if not isinstance(docker, dict) or not isinstance(docker.get("image"), str) or not docker["image"].strip():
            raise ValueError(f"Custom runtime {path}: docker section requires a non-empty image string")
        docker_image = docker["image"]
        docker_env_passthrough = _string_list(docker.get("env_passthrough"), path=path, key="docker.env_passthrough")
    return CustomRuntimeSpec(
        id=runtime_id,
        command=command,
        args=args,
        judge_args=judge_args,
        model_flag=model_flag,
        prompt_via=prompt_via,
        prompt_flag=str(data.get("prompt_flag", "-p")),
        parser=parser,
        env=dict(env),
        docker_image=docker_image,
        docker_env_passthrough=docker_env_passthrough,
        source_path=path,
    )
