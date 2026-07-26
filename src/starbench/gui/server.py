"""Local HTTP server for the StarBench Console.

Standard library only. Binds to localhost by default; the console is a
single-operator tool over a local runs directory, not a shared service.
"""

from __future__ import annotations

import argparse
import json
import signal
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple
from urllib.parse import parse_qs, urlparse

from . import data
from .agents import AgentError, DEFAULT_RUNTIMES_DIR
from .experiments import ExperimentError
from .launcher import LaunchError
from ..home import HomeLayout, resolve_home
from ..lifecycle import LaunchRegistry
from .library import LibraryError
from .providers import ProviderError
from .services.console import ConsoleApplication
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
        self.registry = LaunchRegistry(self.runs_dir)
        self.application = ConsoleApplication(
            runs_dir=self.runs_dir,
            tasks_dirs=self.tasks_dirs,
            cwd=self.cwd,
            registry=self.registry,
            runtimes_dir=self.runtimes_dir,
            skills_dir=self.skills_dir,
        )


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
            elif segments == ["api", "launches"]:
                self._handle_launch_batch()
            elif segments == ["api", "profiles"]:
                self._handle_save_profiles()
            elif segments == ["api", "providers"]:
                self._handle_save_providers()
            elif segments == ["api", "agents"]:
                self._handle_save_agent()
            elif segments == ["api", "agents", "install"]:
                self._handle_install_agent()
            elif (
                len(segments) == 4
                and segments[:2] == ["api", "agents"]
                and segments[3] == "delete"
            ):
                self._send_json(self.state.application.delete_agent(segments[2]))
            elif (
                len(segments) == 4
                and segments[:2] == ["api", "providers"]
                and segments[3] == "refresh-models"
            ):
                self._send_json(
                    self.state.application.refresh_provider_models(segments[2])
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
        app = self.state.application
        if segments == ["meta"]:
            self._send_json(app.meta())
        elif segments == ["runs"]:
            self._send_json(app.list_runs())
        elif len(segments) == 2 and segments[0] == "runs":
            self._send_json(app.run_detail(segments[1]))
        elif len(segments) == 3 and segments[0] == "runs" and segments[2] == "live":
            self._send_json(app.run_live(segments[1]))
        elif len(segments) == 4 and segments[0] == "runs" and segments[2] == "tasks":
            self._send_json(app.task_run_detail(segments[1], segments[3]))
        elif (
            len(segments) == 5
            and segments[0] == "runs"
            and segments[2] == "tasks"
            and segments[4] == "events"
        ):
            offset = self._query_int(query, "offset", 0)
            limit = self._query_int(query, "limit", 100)
            self._send_json(app.raw_events(segments[1], segments[3], offset, limit))
        elif (
            len(segments) == 5
            and segments[0] == "runs"
            and segments[2] == "tasks"
            and segments[4] == "trace"
        ):
            offset = self._query_int(query, "offset", 0)
            limit = self._query_int(query, "limit", data.TRACE_DEFAULT_LIMIT)
            self._send_json(app.task_trace(segments[1], segments[3], offset, limit))
        elif (
            len(segments) == 5
            and segments[0] == "runs"
            and segments[2] == "tasks"
            and segments[4] == "artifact"
        ):
            self._send_json(
                app.read_artifact(
                    segments[1], segments[3], query.get("path", [""])[0]
                )
            )
        elif segments == ["coverage"]:
            profile_id = query.get("profile", [None])[0]
            self._send_json(app.coverage(profile_id))
        elif segments == ["tasklib"]:
            self._send_json({"libraries": app.libraries()})
        elif segments == ["tasklib", "history"]:
            # Legacy ?dir= is accepted and ignored: history is global under
            # the single home library.
            self._send_json(app.task_history())
        elif segments == ["tasklib", "task"]:
            self._send_json(
                app.task_package_detail(
                    query.get("dir", [""])[0], query.get("name", [""])[0]
                )
            )
        elif segments == ["preflight"]:
            params = {
                key: str(values[0]) if values else "" for key, values in query.items()
            }
            self._send_json(app.preflight(params))
        elif segments == ["agents"]:
            self._send_json(app.list_agents())
        elif segments == ["agents", "status"]:
            # npm update checks hit the network; the fast default paints the
            # page from local probes only, and the UI opts in explicitly.
            check_updates = str(query.get("check_updates", [""])[0]).strip().lower() in ("1", "true")
            self._send_json(app.agent_statuses(check_updates=check_updates))
        elif segments == ["agents", "templates"]:
            self._send_json(app.agent_templates())
        elif segments == ["skills"]:
            self._send_json(app.list_skills())
        elif segments == ["launches"]:
            self._send_json(app.list_launches())
        elif segments == ["profiles"]:
            self._send_json(app.load_profiles())
        elif segments == ["providers"]:
            self._send_json(app.load_providers())
        elif segments == ["providers", "cli-status"]:
            self._send_json(app.provider_cli_statuses())
        elif segments == ["compare"]:
            raw = query.get("runs", [])
            run_ids = [
                run_id.strip()
                for item in raw
                for run_id in str(item).split(",")
                if run_id.strip()
            ]
            self._send_json(app.compare(run_ids))
        else:
            self._send_error_json("Not found.", HTTPStatus.NOT_FOUND)

    @staticmethod
    def _query_int(query: Dict[str, Any], key: str, fallback: int) -> int:
        try:
            return int(query.get(key, [fallback])[0])
        except (TypeError, ValueError):
            return fallback


    # -- actions ------------------------------------------------------------

    def _handle_launch(self) -> None:
        payload = self._read_body()
        if payload is None:
            raise LaunchError("Request body must be a JSON object.")
        result = self.state.application.launch(payload)
        status = HTTPStatus.CREATED if result.created else HTTPStatus.OK
        self._send_json(result.payload, status)

    def _handle_stop(self, run_id: str) -> None:
        self._send_json(self.state.application.stop(run_id))

    def _handle_task_import(self) -> None:
        payload = self._read_body()
        if payload is None:
            raise LibraryError("Request body must be a JSON object.")
        result = self.state.application.import_task(payload)
        status = HTTPStatus.CREATED if result.created else HTTPStatus.OK
        self._send_json(result.payload, status)

    def _handle_launch_batch(self) -> None:
        payload = self._read_body()
        if payload is None:
            raise ExperimentError("Request body must be a JSON object.")
        result = self.state.application.launch_batch(payload)
        status = HTTPStatus.CREATED if result.created else HTTPStatus.OK
        self._send_json(result.payload, status)

    def _handle_save_profiles(self) -> None:
        payload = self._read_body()
        if payload is None:
            raise ExperimentError("Request body must be a JSON object.")
        self._send_json(self.state.application.save_profiles(payload))

    def _handle_save_providers(self) -> None:
        payload = self._read_body()
        if payload is None:
            raise ProviderError("Request body must be a JSON object.")
        self._send_json(self.state.application.save_providers(payload))

    def _handle_save_agent(self) -> None:
        payload = self._read_body()
        if payload is None:
            raise AgentError("Request body must be a JSON object.")
        self._send_json(
            self.state.application.save_agent(payload), HTTPStatus.CREATED
        )

    def _handle_install_agent(self) -> None:
        payload = self._read_body()
        if payload is None:
            raise AgentError("Request body must be a JSON object.")
        agent_id = str(payload.get("agent_id") or "").strip()
        self._send_json(self.state.application.install_agent(agent_id))


def make_handler(state: ConsoleState) -> type:
    return type("BoundConsoleHandler", (ConsoleHandler,), {"state": state})


def build_state(
    runs_dir: Optional[Path] = None,
    tasks_dirs: Optional[Sequence[Path]] = None,
    cwd: Optional[Path] = None,
    runtimes_dir: Optional[Path] = None,
    skills_dir: Optional[Path] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> ConsoleState:
    """Assemble console state; every omitted location comes from the home layout.

    Precedence per directory: explicit argument > ``$STARBENCH_HOME`` >
    ``~/.starbench``. Home is resolved here and nowhere inward — the read itself
    lives in :mod:`starbench.home`, off ``os.environ`` or an injected ``environ``
    — so everything downstream sees explicit paths. Home-derived and
    argument-derived paths go through the same absolutize-then-``resolve()``
    treatment, so two spellings of the same directory compare equal downstream.
    Raises ``ValueError`` when ``$STARBENCH_HOME`` is set to a relative path.
    """
    cwd = (cwd or Path.cwd()).resolve()
    home = HomeLayout(resolve_home(environ))
    if runs_dir is None:
        runs_dir = home.runs
    if tasks_dirs is None:
        tasks_dirs = [home.tasks]
    if runtimes_dir is None:
        runtimes_dir = home.runtimes
    if skills_dir is None:
        skills_dir = home.skills
    runs_dir = runs_dir if runs_dir.is_absolute() else cwd / runs_dir
    resolved = []
    for path in tasks_dirs:
        path = path if path.is_absolute() else cwd / path
        resolved.append(path.resolve())
    if not runtimes_dir.is_absolute():
        runtimes_dir = cwd / runtimes_dir
    if not skills_dir.is_absolute():
        skills_dir = cwd / skills_dir
    # ConsoleState resolves runtimes_dir/skills_dir on the way in.
    return ConsoleState(runs_dir.resolve(), resolved, cwd, runtimes_dir, skills_dir)


def serve(state: ConsoleState, host: str, port: int) -> Tuple[ThreadingHTTPServer, threading.Thread]:
    server = ThreadingHTTPServer((host, port), make_handler(state))
    thread = threading.Thread(target=server.serve_forever, name="starbench-gui", daemon=True)
    thread.start()
    return server, thread


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the StarBench Console GUI.")
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=None,
        help="Run artifact root. Defaults to $STARBENCH_HOME/runs (~/.starbench/runs).",
    )
    parser.add_argument(
        "--tasks-dir",
        type=Path,
        action="append",
        help="Task package directory offered in the launcher. Repeatable. "
        "Defaults to $STARBENCH_HOME/tasks (~/.starbench/tasks).",
    )
    parser.add_argument(
        "--runtimes-dir",
        type=Path,
        default=None,
        help="Directory of custom runtime specs. "
        "Defaults to $STARBENCH_HOME/runtimes (~/.starbench/runtimes).",
    )
    parser.add_argument(
        "--skills-dir",
        type=Path,
        default=None,
        help="Executor skill library root. "
        "Defaults to $STARBENCH_HOME/skills (~/.starbench/skills).",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8321)
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser tab.")
    args = parser.parse_args(argv)

    try:
        state = build_state(
            args.runs_dir,
            args.tasks_dir,
            runtimes_dir=args.runtimes_dir,
            skills_dir=args.skills_dir,
        )
    except ValueError as exc:
        parser.error(str(exc))
    server = ThreadingHTTPServer((args.host, args.port), make_handler(state))
    url = f"http://{args.host}:{server.server_address[1]}/"
    print(f"StarBench Console serving {state.runs_dir}")
    print(f"  {url}")
    if not args.no_browser:
        webbrowser.open(url)

    def request_shutdown(_signum: int, _frame: Any) -> None:
        raise KeyboardInterrupt

    previous_sigterm = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, request_shutdown)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        state.registry.stop_all()
        server.server_close()
        signal.signal(signal.SIGTERM, previous_sigterm)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
