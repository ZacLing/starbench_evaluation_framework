"""Local HTTP server for the StarBench Console.

Standard library only. Binds to localhost by default; the console is a
single-operator tool over a local runs directory, not a shared service.
"""

from __future__ import annotations

import argparse
import json
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple
from urllib.parse import parse_qs, urlparse

from . import agents, data, experiments, library, providers, skills
from .agents import AgentError, DEFAULT_RUNTIMES_DIR
from .experiments import ExperimentError
from .launcher import (
    AGENT_CHOICES,
    LaunchError,
    LaunchRegistry,
    build_run_argv,
    scoped_launch_env,
)
from .library import LibraryError
from .providers import ProviderError
from .skills import DEFAULT_SKILLS_DIR, SkillError

STATIC_DIR = Path(__file__).parent / "static"

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}

MAX_BODY_BYTES = 1_000_000


class ConsoleState:
    def __init__(
        self,
        runs_dir: Path,
        tasks_dirs: Sequence[Path],
        cwd: Path,
        runtimes_dir: Optional[Path] = None,
        skills_dir: Optional[Path] = None,
    ) -> None:
        self.runs_dir = runs_dir
        self.tasks_dirs = list(tasks_dirs)
        self.cwd = cwd
        self.runtimes_dir = (runtimes_dir or DEFAULT_RUNTIMES_DIR).resolve()
        self.skills_dir = (skills_dir or DEFAULT_SKILLS_DIR).resolve()
        self.registry = LaunchRegistry()


class ConsoleHandler(BaseHTTPRequestHandler):
    server_version = "StarBenchConsole/0.1"
    state: ConsoleState  # assigned by make_handler

    # -- plumbing -----------------------------------------------------------

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass

    def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, message: str, status: HTTPStatus) -> None:
        self._send_json({"error": message}, status)

    def _read_body(self) -> Optional[Dict[str, Any]]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY_BYTES:
            return None
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _send_static(self, relative: str) -> None:
        target = (STATIC_DIR / relative).resolve()
        try:
            target.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self._send_error_json("Not found.", HTTPStatus.NOT_FOUND)
            return
        if not target.is_file():
            self._send_error_json("Not found.", HTTPStatus.NOT_FOUND)
            return
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header(
            "Content-Type", CONTENT_TYPES.get(target.suffix, "application/octet-stream")
        )
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    # -- routing ------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        segments = [segment for segment in parsed.path.split("/") if segment]
        query = parse_qs(parsed.query)
        try:
            if not segments or segments[0] != "api":
                if segments and segments[0] == "static":
                    self._send_static("/".join(segments[1:]))
                else:
                    self._send_static("index.html")
                return
            self._route_api_get(segments[1:], query)
        except data.NotFound as error:
            self._send_error_json(str(error), HTTPStatus.NOT_FOUND)
        except (LibraryError, ExperimentError, ProviderError, AgentError, SkillError) as error:
            self._send_error_json(str(error), HTTPStatus.BAD_REQUEST)
        except BrokenPipeError:
            pass
        except Exception as error:  # pragma: no cover - defensive last resort
            self._send_error_json(f"Internal error: {error}", HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        segments = [segment for segment in parsed.path.split("/") if segment]
        try:
            if segments[:2] == ["api", "launch"] and len(segments) == 2:
                self._handle_launch()
            elif (
                len(segments) == 4
                and segments[:2] == ["api", "launches"]
                and segments[3] == "stop"
            ):
                self._handle_stop(segments[2])
            elif segments == ["api", "tasks", "import"]:
                self._handle_task_import()
            elif segments == ["api", "tasklib", "dirs"]:
                self._handle_register_tasks_dir()
            elif segments == ["api", "experiments"]:
                self._handle_create_experiment()
            elif segments == ["api", "profiles"]:
                self._handle_save_profiles()
            elif segments == ["api", "providers"]:
                self._handle_save_providers()
            elif segments == ["api", "agents"]:
                self._handle_save_agent()
            elif (
                len(segments) == 4
                and segments[:2] == ["api", "agents"]
                and segments[3] == "delete"
            ):
                self._send_json(
                    agents.delete_custom_agent(self.state.runtimes_dir, segments[2])
                )
            elif (
                len(segments) == 4
                and segments[:2] == ["api", "providers"]
                and segments[3] == "refresh-models"
            ):
                self._send_json(
                    providers.refresh_provider_models(self.state.runs_dir, segments[2])
                )
            else:
                self._send_error_json("Not found.", HTTPStatus.NOT_FOUND)
        except (
            LaunchError,
            LibraryError,
            ExperimentError,
            ProviderError,
            AgentError,
            SkillError,
        ) as error:
            self._send_error_json(str(error), HTTPStatus.BAD_REQUEST)
        except BrokenPipeError:
            pass
        except Exception as error:  # pragma: no cover - defensive last resort
            self._send_error_json(f"Internal error: {error}", HTTPStatus.INTERNAL_SERVER_ERROR)

    def _route_api_get(self, segments: Sequence[str], query: Dict[str, Any]) -> None:
        state = self.state
        active = state.registry.active_run_ids()
        if segments == ["meta"]:
            self._send_json(self._meta())
        elif segments == ["runs"]:
            self._send_json({"runs": data.list_runs(state.runs_dir, active)})
        elif len(segments) == 2 and segments[0] == "runs":
            self._send_json(data.run_detail(state.runs_dir, segments[1], active))
        elif len(segments) == 4 and segments[0] == "runs" and segments[2] == "tasks":
            self._send_json(data.task_run_detail(state.runs_dir, segments[1], segments[3]))
        elif (
            len(segments) == 5
            and segments[0] == "runs"
            and segments[2] == "tasks"
            and segments[4] == "events"
        ):
            offset = self._query_int(query, "offset", 0)
            limit = self._query_int(query, "limit", 100)
            self._send_json(
                data.raw_events(state.runs_dir, segments[1], segments[3], offset, limit)
            )
        elif segments == ["tasklib"]:
            self._send_json({"libraries": self._libraries()})
        elif segments == ["tasklib", "task"]:
            tasks_dir = self._registered_dir(query.get("dir", [""])[0])
            self._send_json(
                library.task_package_detail(tasks_dir, query.get("name", [""])[0])
            )
        elif segments == ["fs", "list"]:
            self._send_json(
                library.browse_directories(query.get("path", [None])[0], cwd=state.cwd)
            )
        elif segments == ["preflight"]:
            first = lambda key, default="": query.get(key, [default])[0]  # noqa: E731
            self._send_json({"checks": self._preflight(first)})
        elif segments == ["agents"]:
            self._send_json(agents.list_agents(state.runtimes_dir))
        elif segments == ["agents", "templates"]:
            self._send_json({"templates": agents.agent_templates()})
        elif segments == ["skills"]:
            self._send_json(skills.list_skills(state.skills_dir))
        elif segments == ["launches"]:
            self._send_json({"launches": state.registry.list()})
        elif segments == ["profiles"]:
            self._send_json(experiments.load_profiles(state.runs_dir))
        elif segments == ["providers"]:
            self._send_json(providers.load_providers(state.runs_dir))
        elif segments == ["providers", "cli-status"]:
            self._send_json(providers.load_provider_cli_statuses(state.runs_dir))
        elif segments == ["experiments"]:
            self._send_json({"experiments": experiments.list_experiments(state.runs_dir, active)})
        elif len(segments) == 2 and segments[0] == "experiments":
            self._send_json(
                experiments.experiment_detail(state.runs_dir, segments[1], active)
            )
        else:
            self._send_error_json("Not found.", HTTPStatus.NOT_FOUND)

    def _custom_meta(self, agent: str) -> Optional[Dict[str, Any]]:
        if not agent.startswith("custom:"):
            return None
        return agents.get_custom_agent(self.state.runtimes_dir, agent.split(":", 1)[1])

    def _preflight(self, first: Any) -> list:
        executor_agent = first("executor_agent", "codex")
        evaluator_agent = first("evaluator_agent", "codex")
        docker_image = first("docker_image")
        executor_meta = self._custom_meta(executor_agent)
        evaluator_meta = self._custom_meta(evaluator_agent)
        if first("executor_backend", "local") == "docker":
            if executor_meta:
                docker_image = executor_meta.get("docker_image") or ""
            elif not docker_image:
                from ..adapters import DEFAULT_DOCKER_IMAGES

                docker_image = DEFAULT_DOCKER_IMAGES.get(executor_agent, "")
        return library.preflight(
            executor_agent=executor_agent,
            evaluator_agent=evaluator_agent,
            executor_backend=first("executor_backend", "local"),
            docker_image=docker_image,
            executor_auth_mode=first("executor_auth_mode", "env"),
            evaluator_auth_mode=first("evaluator_auth_mode", "env"),
            opencode_api_key_env=first("opencode_api_key_env") or None,
            executor_bin=(executor_meta or {}).get("cli", {}).get("bin"),
            evaluator_bin=(evaluator_meta or {}).get("cli", {}).get("bin"),
            executor_env_keys=[executor_meta["api_key_env"]]
            if executor_meta and executor_meta.get("api_key_env")
            else None,
            evaluator_env_keys=[evaluator_meta["api_key_env"]]
            if evaluator_meta and evaluator_meta.get("api_key_env")
            else None,
        )

    def _libraries(self) -> list:
        return [
            {
                "dir": str(tasks_dir),
                "exists": tasks_dir.is_dir(),
                "tasks": data.list_task_packages(tasks_dir),
            }
            for tasks_dir in self.state.tasks_dirs
        ]

    def _registered_dir(self, raw: str) -> Path:
        target = Path(raw).resolve() if raw else None
        for tasks_dir in self.state.tasks_dirs:
            if target == tasks_dir:
                return tasks_dir
        raise LibraryError(f"Not a registered task directory: {raw}")

    @staticmethod
    def _query_int(query: Dict[str, Any], key: str, fallback: int) -> int:
        try:
            return int(query.get(key, [fallback])[0])
        except (TypeError, ValueError):
            return fallback

    def _meta(self) -> Dict[str, Any]:
        state = self.state
        return {
            "runs_dir": str(state.runs_dir),
            "cwd": str(state.cwd),
            "runtimes_dir": str(state.runtimes_dir),
            "skills_dir": str(state.skills_dir),
            "tasks_dirs": [
                {"dir": str(path), "exists": path.is_dir()} for path in state.tasks_dirs
            ],
            "agents": list(AGENT_CHOICES),
            "judge_modes": ["single", "parallel", "both"],
            "auth_modes": ["env", "global", "copy-auth"],
            "backends": ["local", "docker"],
            "thinking_efforts": ["none", "low", "medium", "high"],
        }

    # -- actions ------------------------------------------------------------

    def _handle_launch(self) -> None:
        payload = self._read_body()
        if payload is None:
            raise LaunchError("Request body must be a JSON object.")
        state = self.state
        argv = build_run_argv(payload, runs_dir=state.runs_dir)
        if payload.get("dry_run"):
            self._send_json({"argv": argv, "dry_run": True})
            return
        run_id = str(payload["run_id"]).strip()
        state.runs_dir.mkdir(parents=True, exist_ok=True)
        log_path = state.runs_dir / f"{run_id}.launch.log"
        launch = state.registry.launch(run_id, argv, cwd=state.cwd, log_path=log_path)
        self._send_json(launch, HTTPStatus.CREATED)

    def _handle_stop(self, run_id: str) -> None:
        launch = self.state.registry.stop(run_id)
        self._send_json(launch)

    def _handle_task_import(self) -> None:
        payload = self._read_body()
        if payload is None:
            raise LibraryError("Request body must be a JSON object.")
        files = payload.get("files")
        if not isinstance(files, list):
            raise LibraryError("`files` must be a list of {path, content_b64} objects.")
        dry_run = bool(payload.get("dry_run"))
        target_dir = self._registered_dir(str(payload.get("target_dir") or ""))
        report = library.install_task_package(files, target_dir=target_dir, dry_run=dry_run)
        self._send_json(report, HTTPStatus.OK if dry_run or not report["valid"] else HTTPStatus.CREATED)

    def _handle_create_experiment(self) -> None:
        payload = self._read_body()
        if payload is None:
            raise ExperimentError("Request body must be a JSON object.")
        state = self.state
        plan = experiments.plan_experiment(
            payload,
            runs_dir=state.runs_dir,
            runtimes_dir=state.runtimes_dir,
            skills_dir=state.skills_dir,
        )
        if payload.get("dry_run"):
            self._send_json({**plan, "dry_run": True})
            return
        launched = []
        for item in plan["plans"]:
            state.runs_dir.mkdir(parents=True, exist_ok=True)
            log_path = state.runs_dir / f"{item['run_id']}.launch.log"
            launched.append(
                state.registry.launch(
                    item["run_id"],
                    item["argv"],
                    cwd=state.cwd,
                    log_path=log_path,
                    # Executor and judge injections ship under separate scope
                    # prefixes so the runner keeps their environments isolated.
                    env_extra=scoped_launch_env(
                        item.get("executor_env_spec"), item.get("judge_env_spec")
                    ),
                )
            )
        record = experiments.record_experiment(
            state.runs_dir, name=plan["name"], payload=payload, plans=plan["plans"]
        )
        self._send_json({**record, "launches": launched}, HTTPStatus.CREATED)

    def _handle_save_profiles(self) -> None:
        payload = self._read_body()
        if payload is None:
            raise ExperimentError("Request body must be a JSON object.")
        self._send_json(experiments.save_profiles(self.state.runs_dir, payload))

    def _handle_save_providers(self) -> None:
        payload = self._read_body()
        if payload is None:
            raise ProviderError("Request body must be a JSON object.")
        self._send_json(providers.save_providers(self.state.runs_dir, payload))

    def _handle_save_agent(self) -> None:
        payload = self._read_body()
        if payload is None:
            raise AgentError("Request body must be a JSON object.")
        self._send_json(
            agents.save_custom_agent(self.state.runtimes_dir, payload), HTTPStatus.CREATED
        )

    def _handle_register_tasks_dir(self) -> None:
        payload = self._read_body()
        if payload is None:
            raise LibraryError("Request body must be a JSON object.")
        raw = str(payload.get("dir") or "").strip()
        if not raw:
            raise LibraryError("`dir` is required.")
        path = Path(raw).expanduser().resolve()
        if not path.is_dir():
            raise LibraryError(f"Not a directory: {path}")
        if path not in self.state.tasks_dirs:
            self.state.tasks_dirs.append(path)
        self._send_json({"libraries": self._libraries()})


def make_handler(state: ConsoleState) -> type:
    return type("BoundConsoleHandler", (ConsoleHandler,), {"state": state})


def build_state(
    runs_dir: Path,
    tasks_dirs: Optional[Sequence[Path]] = None,
    cwd: Optional[Path] = None,
    runtimes_dir: Optional[Path] = None,
    skills_dir: Optional[Path] = None,
) -> ConsoleState:
    cwd = (cwd or Path.cwd()).resolve()
    runs_dir = runs_dir if runs_dir.is_absolute() else cwd / runs_dir
    if tasks_dirs is None:
        tasks_dirs = [cwd / "tasks", cwd / "examples" / "tasks"]
    resolved = []
    for path in tasks_dirs:
        path = path if path.is_absolute() else cwd / path
        resolved.append(path.resolve())
    if runtimes_dir is not None and not runtimes_dir.is_absolute():
        runtimes_dir = cwd / runtimes_dir
    if skills_dir is not None and not skills_dir.is_absolute():
        skills_dir = cwd / skills_dir
    return ConsoleState(runs_dir.resolve(), resolved, cwd, runtimes_dir, skills_dir)


def serve(state: ConsoleState, host: str, port: int) -> Tuple[ThreadingHTTPServer, threading.Thread]:
    server = ThreadingHTTPServer((host, port), make_handler(state))
    thread = threading.Thread(target=server.serve_forever, name="starbench-gui", daemon=True)
    thread.start()
    return server, thread


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the StarBench Console GUI.")
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    parser.add_argument(
        "--tasks-dir",
        type=Path,
        action="append",
        help="Task package directory offered in the launcher. Repeatable. "
        "Defaults to ./tasks and ./examples/tasks.",
    )
    parser.add_argument(
        "--runtimes-dir",
        type=Path,
        default=None,
        help="Directory of custom runtime specs (defaults to the repo's runtimes/).",
    )
    parser.add_argument(
        "--skills-dir",
        type=Path,
        default=None,
        help="Executor skill library root (defaults to the repo's executor_skills/).",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8321)
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser tab.")
    args = parser.parse_args(argv)

    state = build_state(
        args.runs_dir,
        args.tasks_dir,
        runtimes_dir=args.runtimes_dir,
        skills_dir=args.skills_dir,
    )
    server = ThreadingHTTPServer((args.host, args.port), make_handler(state))
    url = f"http://{args.host}:{server.server_address[1]}/"
    print(f"StarBench Console serving {state.runs_dir}")
    print(f"  {url}")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
