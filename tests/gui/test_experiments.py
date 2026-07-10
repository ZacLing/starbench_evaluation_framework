"""Experiment planning, recording and custom-runtime contenders in gui.experiments."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from starbench.contracts import validate_payload
from starbench.gui import experiments
from starbench.gui.experiments import ExperimentError
from helpers import make_run, write_json


class ExperimentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_gui_exp_"))
        self.runs_dir = self.tmp / "runs"
        self.runs_dir.mkdir()
        self.tasks_dir = self.tmp / "tasks"
        self.tasks_dir.mkdir()
        self._write_minimal_task(self.tasks_dir / "demo_task")

    @staticmethod
    def _write_minimal_task(package: Path) -> None:
        write_json(package / "task.json", {"id": "demo_task", "name": "Demo task"})
        write_json(
            package / "rubrics.json",
            {
                "rubrics": [
                    {
                        "id": "R001",
                        "fail_fast": False,
                        "expected": True,
                        "question": "Output exists?",
                    }
                ]
            },
        )
        (package / "prompt.md").write_text("Produce an output.", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def experiment_payload(self, **overrides):
        base = {
            "name": "exp_demo",
            "tasks_dir": str(self.tasks_dir),
            "tasks": ["demo_task"],
            "shared": {
                "evaluator_agent": "codex",
                "evaluator_model": "gpt-5.5",
                "evaluator_auth_mode": "global",
                "judge_mode": "single",
                "evaluator_timeout_seconds": 600,
                "executor_backend": "docker",
                "docker_image": "starbench-codex:latest",
                "seed": 7,
                "batch_size": 1,
                "repeat": 1,
            },
            "contenders": [
                {"label": "GPT gpt-5.5", "agent": "codex", "model": "gpt-5.5", "auth_mode": "env"},
                {
                    "label": "Claude opus",
                    "agent": "claude",
                    "model": "claude-opus-4-8",
                    "auth_mode": "global",
                },
            ],
        }
        base.update(overrides)
        return base

    def test_plan_builds_one_run_per_contender(self) -> None:
        plan = experiments.plan_experiment(self.experiment_payload(), runs_dir=self.runs_dir)
        self.assertEqual(len(plan["plans"]), 2)
        run_ids = [item["run_id"] for item in plan["plans"]]
        self.assertEqual(run_ids, ["exp_demo__gpt-gpt-5-5", "exp_demo__claude-opus"])
        for item in plan["plans"]:
            joined = " ".join(item["argv"])
            self.assertIn("--evaluator-agent codex", joined)
            self.assertIn("--evaluator-model gpt-5.5", joined)
            self.assertIn("--seed 7", joined)
            self.assertIn("--evaluator-auth-mode global", joined)

    def test_shared_advanced_knobs_forward_to_every_contender(self) -> None:
        payload = self.experiment_payload()
        payload["shared"]["max_evaluator_parallel"] = 8
        payload["shared"]["claude_max_turns"] = 30
        plan = experiments.plan_experiment(payload, runs_dir=self.runs_dir)
        self.assertEqual(len(plan["plans"]), 2)
        for item in plan["plans"]:
            joined = " ".join(item["argv"])
            self.assertIn("--max-evaluator-parallel 8", joined)
            self.assertIn("--claude-max-turns 30", joined)

    def test_executor_and_judge_opencode_gateways_are_independent(self) -> None:
        payload = self.experiment_payload(
            contenders=[
                {
                    "label": "OpenCode contender",
                    "agent": "opencode",
                    "model": "executor/model",
                    "auth_mode": "env",
                    "opencode_provider": "executor-provider",
                    "opencode_base_url": "https://executor.example/v1",
                    "opencode_api_key_env": "EXECUTOR_KEY",
                }
            ]
        )
        payload["shared"].update(
            {
                "evaluator_agent": "opencode",
                "evaluator_model": "judge/model",
                "evaluator_auth_mode": "env",
                "evaluator_gateway": {
                    "opencode_provider": "judge-provider",
                    "opencode_base_url": "https://judge.example/v1",
                    "opencode_api_key_env": "JUDGE_KEY",
                },
            }
        )

        item = experiments.plan_experiment(payload, runs_dir=self.runs_dir)["plans"][0]
        argv = item["argv"]
        joined = " ".join(argv)
        self.assertIn("--executor-opencode-provider executor-provider", joined)
        self.assertIn("--executor-opencode-base-url https://executor.example/v1", joined)
        self.assertIn("--evaluator-opencode-provider judge-provider", joined)
        self.assertIn("--evaluator-opencode-base-url https://judge.example/v1", joined)
        self.assertEqual(item["executor_opencode_api_key_env"], "EXECUTOR_KEY")
        self.assertEqual(item["evaluator_opencode_api_key_env"], "JUDGE_KEY")
        self.assertEqual(item["executor_credential_env_keys"], ["EXECUTOR_KEY"])
        self.assertEqual(item["evaluator_credential_env_keys"], ["JUDGE_KEY"])

    def test_codex_executor_bin_does_not_reroute_codex_judge(self) -> None:
        payload = self.experiment_payload(
            contenders=[
                {
                    "label": "Codex gateway",
                    "agent": "codex",
                    "model": "gpt-5.5",
                    "auth_mode": "env",
                    "codex_bin": "codex -c model_provider=gateway",
                }
            ]
        )
        payload["shared"]["evaluator_agent"] = "codex"

        argv = experiments.plan_experiment(payload, runs_dir=self.runs_dir)["plans"][0][
            "argv"
        ]
        joined = " ".join(argv)
        self.assertIn("--executor-bin codex -c model_provider=gateway", joined)
        self.assertNotIn("--evaluator-bin", argv)

    def test_claude_max_turns_omitted_when_unset(self) -> None:
        plan = experiments.plan_experiment(self.experiment_payload(), runs_dir=self.runs_dir)
        for item in plan["plans"]:
            self.assertNotIn("--claude-max-turns", item["argv"])

    def test_docker_backend_uses_one_image_per_runtime(self) -> None:
        payload = self.experiment_payload()
        payload["contenders"].append(
            {"label": "Gemini", "agent": "gemini", "model": "gemini-2.5-pro", "auth_mode": "env"}
        )
        plan = experiments.plan_experiment(payload, runs_dir=self.runs_dir)
        by_agent = {item["agent"]: item for item in plan["plans"]}
        for agent, image in (
            ("codex", "starbench-codex:latest"),
            ("claude", "starbench-claude-code:latest"),
            ("gemini", "starbench-gemini-cli:latest"),
        ):
            self.assertEqual(by_agent[agent]["backend"], "docker")
            self.assertFalse(by_agent[agent]["backend_downgraded"])
            self.assertEqual(by_agent[agent]["docker_image"], image)
            self.assertIn(f"--docker-image {image}", " ".join(by_agent[agent]["argv"]))

    def test_record_list_and_detail(self) -> None:
        payload = self.experiment_payload()
        plan = experiments.plan_experiment(payload, runs_dir=self.runs_dir)
        experiments.record_experiment(
            self.runs_dir, name=plan["name"], payload=payload, plans=plan["plans"]
        )
        make_run(self.runs_dir, "exp_demo__gpt-gpt-5-5")
        listed = experiments.list_experiments(self.runs_dir)
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["id"], "exp_demo")
        self.assertEqual(len(listed[0]["runs"]), 2)
        self.assertEqual(listed[0]["runs"][1]["status"], "missing")

        detail = experiments.experiment_detail(self.runs_dir, "exp_demo")
        self.assertEqual(len(detail["contenders"]), 2)
        matrix = detail["matrix"]
        self.assertEqual(matrix[0]["task_id"], "demo_task")
        rubric = matrix[0]["rubrics"][0]
        self.assertIn("exp_demo__gpt-gpt-5-5", rubric["cells"])
        self.assertEqual(rubric["cells"]["exp_demo__gpt-gpt-5-5"]["passed"], 1)

    def test_duplicate_experiment_name_rejected(self) -> None:
        payload = self.experiment_payload()
        plan = experiments.plan_experiment(payload, runs_dir=self.runs_dir)
        experiments.record_experiment(
            self.runs_dir, name=plan["name"], payload=payload, plans=plan["plans"]
        )
        with self.assertRaises(ExperimentError):
            experiments.plan_experiment(payload, runs_dir=self.runs_dir)

    def test_contender_error_names_the_contender(self) -> None:
        payload = self.experiment_payload(
            contenders=[{"label": "bad", "agent": "bash", "model": "x"}]
        )
        with self.assertRaises(ExperimentError) as ctx:
            experiments.plan_experiment(payload, runs_dir=self.runs_dir)
        self.assertIn("bad", str(ctx.exception))

    def test_invalid_task_is_rejected_before_a_launch_plan_is_created(self) -> None:
        rubrics_path = self.tasks_dir / "demo_task" / "rubrics.json"
        rubric = json.loads(rubrics_path.read_text(encoding="utf-8"))["rubrics"][0]
        write_json(rubrics_path, {"rubrics": [rubric, dict(rubric)]})

        with self.assertRaisesRegex(ExperimentError, "invalid_task.*Duplicate rubric"):
            experiments.plan_experiment(self.experiment_payload(), runs_dir=self.runs_dir)

    def test_profiles_roundtrip_and_builtin_default(self) -> None:
        loaded = experiments.load_profiles(self.runs_dir)
        self.assertFalse(loaded["persisted"])
        self.assertEqual(loaded["profiles"][0]["id"], "standard")
        self.assertEqual(loaded["default_profile_id"], "standard")

        saved = experiments.save_profiles(
            self.runs_dir,
            {
                "default_profile_id": "mine",
                "profiles": [
                    {
                        "id": "mine",
                        "name": "Mine",
                        "shared": {"judge_mode": "parallel", "seed": 1},
                        "per_contender_fields": ["model", "credentials"],
                    }
                ],
            },
        )
        self.assertTrue(saved["persisted"])
        reloaded = experiments.load_profiles(self.runs_dir)
        self.assertTrue(reloaded["persisted"])
        self.assertEqual(reloaded["default_profile_id"], "mine")
        self.assertEqual(reloaded["profiles"][0]["shared"]["judge_mode"], "parallel")

    def test_profiles_validation(self) -> None:
        with self.assertRaises(ExperimentError):
            experiments.save_profiles(self.runs_dir, {"profiles": []})
        with self.assertRaises(ExperimentError):
            experiments.save_profiles(
                self.runs_dir,
                {
                    "default_profile_id": "ghost",
                    "profiles": [
                        {"id": "a", "shared": {}, "per_contender_fields": []}
                    ],
                },
            )
        with self.assertRaises(ExperimentError):
            experiments.save_profiles(
                self.runs_dir,
                {
                    "profiles": [
                        {"id": "a", "shared": {}, "per_contender_fields": ["nope"]}
                    ]
                },
            )

    def test_hsw_frontier_builtin_template(self) -> None:
        loaded = experiments.load_profiles(self.runs_dir)
        by_id = {profile["id"]: profile for profile in loaded["profiles"]}
        hsw = by_id["hsw-frontier"]
        self.assertEqual(hsw["name"], "HSW frontier sweep")
        self.assertEqual(hsw["shared"]["repeat"], 5)
        # Same instrument as "standard" — only the repeat count differs.
        standard_shared = dict(by_id["standard"]["shared"])
        hsw_shared = dict(hsw["shared"])
        self.assertEqual(standard_shared.pop("repeat"), 1)
        self.assertEqual(hsw_shared.pop("repeat"), 5)
        self.assertEqual(standard_shared, hsw_shared)
        # Empty roster placeholder: which columns to measure is the operator's
        # judgment, not a shipped guess. task_set is deliberately absent.
        self.assertEqual(hsw["roster"], [])
        self.assertNotIn("task_set", hsw)
        # The plain default stays roster-less (bare launches remain the norm).
        self.assertNotIn("roster", by_id["standard"])

    def save_roster_profile(self, **overrides):
        profile = {
            "id": "hsw",
            "name": "HSW",
            "shared": {"judge_mode": "single", "seed": 1, "repeat": 5},
            "per_contender_fields": ["model"],
            "roster": [
                {"agent": "claude", "model": "claude-opus-4-8", "provider_id": "anthropic"},
                {"agent": "codex", "model": "gpt-5.5"},
            ],
            "task_set": {"tasks_dir": str(self.tasks_dir), "task_ids": ["demo_task"]},
        }
        profile.update(overrides)
        return experiments.save_profiles(self.runs_dir, {"profiles": [profile]})

    def test_profiles_roster_and_task_set_roundtrip(self) -> None:
        self.save_roster_profile()
        reloaded = experiments.load_profiles(self.runs_dir)["profiles"][0]
        self.assertEqual(len(reloaded["roster"]), 2)
        self.assertEqual(reloaded["roster"][0]["provider_id"], "anthropic")
        self.assertEqual(reloaded["task_set"]["task_ids"], ["demo_task"])
        self.assertEqual(reloaded["rev"], 1)

    def test_profiles_rev_increments_only_on_content_change(self) -> None:
        self.save_roster_profile()
        # Identical save: the revision counter must not move.
        self.save_roster_profile()
        self.assertEqual(experiments.load_profiles(self.runs_dir)["profiles"][0]["rev"], 1)
        # Content change bumps it.
        self.save_roster_profile(name="HSW v2")
        self.assertEqual(experiments.load_profiles(self.runs_dir)["profiles"][0]["rev"], 2)
        # A client echoing back a stale rev is ignored: the server assigns it.
        self.save_roster_profile(name="HSW v3", rev=99)
        self.assertEqual(experiments.load_profiles(self.runs_dir)["profiles"][0]["rev"], 3)

    def test_profiles_old_format_backward_compatible(self) -> None:
        # A pre-roster profiles.json (no roster/task_set/rev) loads untouched
        # and can be re-saved as-is; new fields stay optional.
        write_json(
            self.runs_dir / "profiles.json",
            {
                "default_profile_id": "legacy",
                "profiles": [
                    {
                        "id": "legacy",
                        "name": "Legacy",
                        "shared": {"judge_mode": "single"},
                        "per_contender_fields": ["model"],
                    }
                ],
            },
        )
        loaded = experiments.load_profiles(self.runs_dir)
        self.assertTrue(loaded["persisted"])
        self.assertEqual(loaded["profiles"][0]["id"], "legacy")
        self.assertNotIn("roster", loaded["profiles"][0])
        saved = experiments.save_profiles(
            self.runs_dir, {"default_profile_id": "legacy", "profiles": loaded["profiles"][:]}
        )
        self.assertEqual(saved["profiles"][0]["rev"], 1)

    def test_profiles_roster_validation(self) -> None:
        with self.assertRaisesRegex(ExperimentError, "must be a list"):
            self.save_roster_profile(roster="claude")
        with self.assertRaisesRegex(ExperimentError, "must be an object"):
            self.save_roster_profile(roster=["claude"])
        with self.assertRaisesRegex(ExperimentError, "needs an `agent`"):
            self.save_roster_profile(roster=[{"model": "gpt-5.5"}])
        # Credential-shaped fields are rejected by name whitelist.
        with self.assertRaisesRegex(ExperimentError, "unsupported field"):
            self.save_roster_profile(
                roster=[{"agent": "codex", "model": "gpt-5.5", "api_key": "sk-secret"}]
            )

    def test_profiles_task_set_validation(self) -> None:
        with self.assertRaisesRegex(ExperimentError, "task_set must be an object"):
            self.save_roster_profile(task_set=["demo_task"])
        with self.assertRaisesRegex(ExperimentError, "tasks_dir"):
            self.save_roster_profile(task_set={"task_ids": ["demo_task"]})
        with self.assertRaisesRegex(ExperimentError, "task_ids"):
            self.save_roster_profile(
                task_set={"tasks_dir": str(self.tasks_dir), "task_ids": "demo_task"}
            )
        with self.assertRaisesRegex(ExperimentError, "unsupported field"):
            self.save_roster_profile(
                task_set={"tasks_dir": str(self.tasks_dir), "task_ids": [], "extra": 1}
            )


class ExperimentCustomRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_gui_expcustom_"))
        self.runs_dir = self.tmp / "runs"
        self.runs_dir.mkdir()
        self.tasks_dir = self.tmp / "tasks"
        self.tasks_dir.mkdir()
        ExperimentTest._write_minimal_task(self.tasks_dir / "demo_task")
        self.runtimes_dir = self.tmp / "runtimes"
        self.runtimes_dir.mkdir()
        write_json(
            self.runtimes_dir / "qwen-code.json",
            {
                "id": "qwen-code",
                "label": "Qwen Code",
                "command": "qwen",
                "args": ["--output-format", "json", "--yolo"],
                "model_flag": "-m",
                "prompt_via": "stdin",
                "parser": "headless-json",
                "protocol": "openai",
                "base_url_env": "OPENAI_BASE_URL",
                "api_key_env": "OPENAI_API_KEY",
                "docker": {
                    "image": "starbench-qwen:latest",
                    "env_passthrough": ["OPENAI_API_KEY"],
                },
            },
        )
        write_json(
            self.runtimes_dir / "kimi-code.json",
            {
                "id": "kimi-code",
                "command": "kimi",
                "args": ["--print", "--quiet"],
                "prompt_via": "stdin",
                "parser": "text",
                "protocol": "none",
            },
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def payload(self, **overrides):
        base = {
            "name": "exp_custom",
            "tasks_dir": str(self.tasks_dir),
            "tasks": [],
            "shared": {
                "evaluator_agent": "claude",
                "evaluator_model": "claude-opus-4-8",
                "judge_mode": "single",
                "executor_backend": "docker",
                "docker_image": "starbench-codex:latest",
            },
            "contenders": [
                {
                    "label": "Qwen Code",
                    "agent": "custom:qwen-code",
                    "model": "qwen3-coder",
                    "auth_mode": "env",
                    "env": {
                        "OPENAI_BASE_URL": {"value": "https://openrouter.ai/api/v1"},
                        "OPENAI_API_KEY": {"from_env": "OPENROUTER_API_KEY"},
                    },
                },
                {"label": "Kimi", "agent": "custom:kimi-code", "model": "", "auth_mode": "global"},
            ],
        }
        base.update(overrides)
        return base

    def test_custom_contenders_plan_with_docker_capability(self) -> None:
        plan = experiments.plan_experiment(
            self.payload(), runs_dir=self.runs_dir, runtimes_dir=self.runtimes_dir
        )
        by_agent = {item["agent"]: item for item in plan["plans"]}
        qwen = by_agent["custom:qwen-code"]
        self.assertIn("--executor-agent custom:qwen-code", " ".join(qwen["argv"]))
        self.assertIn("--executor-model qwen3-coder", " ".join(qwen["argv"]))
        self.assertIn(f"--runtimes-dir {self.runtimes_dir}", " ".join(qwen["argv"]))
        self.assertEqual(qwen["backend"], "docker")
        self.assertFalse(qwen["backend_downgraded"])
        self.assertEqual(qwen["agent_label"], "Qwen Code")
        kimi = by_agent["custom:kimi-code"]
        self.assertEqual(kimi["backend"], "local")
        self.assertTrue(kimi["backend_downgraded"])

    def test_unknown_custom_contender_rejected(self) -> None:
        payload = self.payload(
            contenders=[{"label": "ghost", "agent": "custom:ghost", "model": ""}]
        )
        with self.assertRaisesRegex(ExperimentError, "custom runtime"):
            experiments.plan_experiment(
                payload, runs_dir=self.runs_dir, runtimes_dir=self.runtimes_dir
            )

    def test_qwen_openrouter_with_codex_judge_isolated_not_rejected(self) -> None:
        # Regression: a qwen-via-OpenRouter contender injecting OPENAI_BASE_URL
        # alongside an official Codex judge used to be rejected (shared process
        # env). Executor and judge now run under isolated env scopes, so the
        # plan succeeds — the injection lands only in the executor scope and the
        # collision is surfaced as an advisory warning.
        payload = self.payload()
        payload["shared"]["evaluator_agent"] = "codex"
        plan = experiments.plan_experiment(
            payload, runs_dir=self.runs_dir, runtimes_dir=self.runtimes_dir
        )
        qwen = {item["agent"]: item for item in plan["plans"]}["custom:qwen-code"]
        self.assertEqual(
            qwen["executor_env_spec"]["OPENAI_BASE_URL"],
            {"value": "https://openrouter.ai/api/v1"},
        )
        self.assertNotIn("OPENAI_BASE_URL", qwen["judge_env_spec"])
        self.assertTrue(
            any("OPENAI_BASE_URL" in warning for warning in qwen["warnings"]),
            qwen["warnings"],
        )

    def test_claude_gateway_with_claude_judge_isolated_not_rejected(self) -> None:
        # Same isolation, Anthropic side: a claude-via-gateway contender injecting
        # ANTHROPIC_BASE_URL with an official Claude judge is now legal.
        payload = self.payload(
            contenders=[
                {
                    "label": "Claude via gateway",
                    "agent": "claude",
                    "model": "claude-opus-4-8",
                    "auth_mode": "env",
                    "env": {
                        "ANTHROPIC_BASE_URL": {"value": "https://gw.example"},
                        "ANTHROPIC_AUTH_TOKEN": {"from_env": "GW_TOKEN"},
                    },
                }
            ],
            shared={
                "evaluator_agent": "claude",
                "evaluator_model": "claude-opus-4-8",
                "judge_mode": "single",
                "executor_backend": "local",
            },
        )
        plan = experiments.plan_experiment(
            payload, runs_dir=self.runs_dir, runtimes_dir=self.runtimes_dir
        )
        item = plan["plans"][0]
        self.assertEqual(
            item["executor_env_spec"]["ANTHROPIC_BASE_URL"], {"value": "https://gw.example"}
        )
        self.assertNotIn("ANTHROPIC_BASE_URL", item["judge_env_spec"])
        self.assertTrue(
            any("ANTHROPIC_BASE_URL" in warning for warning in item["warnings"]),
            item["warnings"],
        )

    def test_custom_judge_env_is_role_scoped_even_when_values_differ(self) -> None:
        payload = self.payload()
        payload["shared"]["evaluator_agent"] = "custom:kimi-code"
        payload["shared"]["judge_env"] = {"KIMI_HOME": {"value": "/tmp/kimi"}}
        plan = experiments.plan_experiment(
            payload, runs_dir=self.runs_dir, runtimes_dir=self.runtimes_dir
        )
        for item in plan["plans"]:
            self.assertIn("KIMI_HOME", item["env_keys"])
            self.assertIn("--evaluator-agent custom:kimi-code", " ".join(item["argv"]))

        # The same variable may have different role-scoped values.
        payload = self.payload(name="exp_custom2")
        payload["shared"]["evaluator_agent"] = "custom:qwen-code"
        payload["shared"]["judge_env"] = {
            "OPENAI_BASE_URL": {"value": "https://api.openai.com/v1"}
        }
        plan = experiments.plan_experiment(
            payload, runs_dir=self.runs_dir, runtimes_dir=self.runtimes_dir
        )
        qwen = {item["agent"]: item for item in plan["plans"]}["custom:qwen-code"]
        self.assertEqual(
            qwen["executor_env_spec"]["OPENAI_BASE_URL"],
            {"value": "https://openrouter.ai/api/v1"},
        )
        self.assertEqual(
            qwen["judge_env_spec"]["OPENAI_BASE_URL"],
            {"value": "https://api.openai.com/v1"},
        )

    def test_unknown_custom_judge_rejected(self) -> None:
        payload = self.payload()
        payload["shared"]["evaluator_agent"] = "custom:ghost-judge"
        with self.assertRaisesRegex(ExperimentError, "Judge runtime"):
            experiments.plan_experiment(
                payload, runs_dir=self.runs_dir, runtimes_dir=self.runtimes_dir
            )


class ExperimentInstructionTest(unittest.TestCase):
    """Instruction ablation: forwarding, the execution estimate, and the two
    runner semantics verified against runner.task_loader.build_task_runs."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_gui_instr_"))
        self.runs_dir = self.tmp / "runs"
        self.runs_dir.mkdir()
        self.tasks_dir = self.tmp / "tasks"
        self.tasks_dir.mkdir()
        self._write_task("task_a", ["H001", "H002"])
        self._write_task("task_b", ["H001", "H002", "H003"])

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_task(self, task_id, step_ids) -> None:
        pkg = self.tasks_dir / task_id
        write_json(pkg / "task.json", {"id": task_id, "name": task_id})
        write_json(
            pkg / "rubrics.json",
            {"rubrics": [{"id": "R001", "fail_fast": True, "expected": True, "question": "?"}]},
        )
        (pkg / "prompt.md").write_text("# go", encoding="utf-8")
        if step_ids is not None:
            write_json(
                pkg / "human_reference.json",
                {
                    "steps": [
                        {
                            "step_id": sid,
                            "step_type": "structure",
                            "instruction": f"do {sid}",
                            # Private trace — must never surface in a plan.
                            "reasoning": f"secret-{sid}",
                        }
                        for sid in step_ids
                    ]
                },
            )

    def payload(self, tasks, *, shared_extra=None, contenders=None, name="exp_instr"):
        shared = {
            "evaluator_agent": "codex",
            "evaluator_model": "gpt-5.5",
            "evaluator_auth_mode": "global",
            "judge_mode": "single",
            "executor_backend": "local",
            "seed": 1,
            "repeat": 1,
        }
        if shared_extra:
            shared.update(shared_extra)
        return {
            "name": name,
            "tasks_dir": str(self.tasks_dir),
            "tasks": tasks,
            "shared": shared,
            "contenders": contenders
            or [{"label": "GPT", "agent": "codex", "model": "gpt-5.5", "auth_mode": "global"}],
        }

    def test_instruction_mode_and_steps_forwarded_to_every_contender(self) -> None:
        payload = self.payload(
            ["task_a", "task_b"],
            shared_extra={"instruction_mode": "select", "instruction_steps": ["H001"]},
            contenders=[
                {"label": "GPT", "agent": "codex", "model": "gpt-5.5", "auth_mode": "global"},
                {"label": "Claude", "agent": "claude", "model": "claude-opus-4-8", "auth_mode": "global"},
            ],
        )
        plan = experiments.plan_experiment(payload, runs_dir=self.runs_dir)
        self.assertEqual(len(plan["plans"]), 2)
        for item in plan["plans"]:
            joined = " ".join(item["argv"])
            self.assertIn("--instruction-mode select", joined)
            self.assertIn("--instruction-step H001", joined)

    def test_estimate_none_mode(self) -> None:
        est = experiments.plan_experiment(
            self.payload(["task_a", "task_b"]), runs_dir=self.runs_dir
        )["execution_estimate"]
        self.assertEqual(est["mode"], "none")
        self.assertEqual(est["per_contender"], 2)  # one run per task
        self.assertEqual(est["total"], 2)  # × one contender

    def test_estimate_select_mode(self) -> None:
        est = experiments.plan_experiment(
            self.payload(
                ["task_a", "task_b"],
                shared_extra={"instruction_mode": "select", "instruction_steps": ["H001"]},
            ),
            runs_dir=self.runs_dir,
        )["execution_estimate"]
        self.assertEqual(est["mode"], "select")
        self.assertEqual(est["per_contender"], 2)  # one combined run per task

    def test_estimate_traverse_mode(self) -> None:
        est = experiments.plan_experiment(
            self.payload(["task_a", "task_b"], shared_extra={"instruction_mode": "traverse"}),
            runs_dir=self.runs_dir,
        )["execution_estimate"]
        self.assertEqual(est["mode"], "traverse")
        self.assertEqual(est["per_contender"], 5)  # 2 + 3 expert steps

    def test_estimate_ablation_mode(self) -> None:
        est = experiments.plan_experiment(
            self.payload(["task_a", "task_b"], shared_extra={"instruction_mode": "ablation"}),
            runs_dir=self.runs_dir,
        )["execution_estimate"]
        self.assertEqual(est["mode"], "ablation")
        # task_a: 1 baseline + 2 steps + 1 all-steps = 4; task_b: 1 + 3 + 1 = 5 -> 9
        self.assertEqual(est["per_contender"], 9)

    def test_estimate_scales_with_repeat_and_contenders(self) -> None:
        payload = self.payload(
            ["task_a", "task_b"],
            shared_extra={"instruction_mode": "ablation", "repeat": 3},
            contenders=[
                {"label": "GPT", "agent": "codex", "model": "gpt-5.5", "auth_mode": "global"},
                {"label": "Claude", "agent": "claude", "model": "claude-opus-4-8", "auth_mode": "global"},
            ],
        )
        est = experiments.plan_experiment(payload, runs_dir=self.runs_dir)["execution_estimate"]
        self.assertEqual(est["per_contender"], 27)  # 9 variants × 3 repeats
        self.assertEqual(est["total"], 54)  # × 2 contenders

    def test_select_unknown_step_rejected(self) -> None:
        payload = self.payload(
            ["task_a", "task_b"],
            shared_extra={"instruction_mode": "select", "instruction_steps": ["H999"]},
        )
        with self.assertRaisesRegex(ExperimentError, "none of the selected tasks"):
            experiments.plan_experiment(payload, runs_dir=self.runs_dir)

    def test_select_step_present_in_only_one_task_is_allowed_at_plan_time(self) -> None:
        # Verified semantics (multi-task select): H003 exists in task_b but not
        # task_a. The plan-time guard only requires a step to exist in >=1 selected
        # task; the runner enforces the stricter every-task rule at launch and
        # rejects the run naming task_a. The console does not pre-empt that here.
        payload = self.payload(
            ["task_a", "task_b"],
            shared_extra={"instruction_mode": "select", "instruction_steps": ["H003"]},
        )
        plan = experiments.plan_experiment(payload, runs_dir=self.runs_dir)
        self.assertIn("--instruction-step H003", " ".join(plan["plans"][0]["argv"]))

    def test_traverse_and_ablation_reject_stepless_tasks_at_plan_time(self) -> None:
        # Verified semantics: the runner rejects the WHOLE run when a selected
        # task lacks expert steps in traverse/ablation. B5 upgrades the console
        # from an amber note to a plan-time hard block: a plan known to die at
        # launch must not produce a Launch-able green light.
        self._write_task("task_c", None)  # no human_reference.json
        for mode in ("traverse", "ablation"):
            with self.assertRaisesRegex(ExperimentError, "task_c"):
                experiments.plan_experiment(
                    self.payload(["task_a", "task_c"], shared_extra={"instruction_mode": mode}),
                    runs_dir=self.runs_dir,
                )
        # All-steps selections still plan normally.
        est = experiments.plan_experiment(
            self.payload(["task_a"], shared_extra={"instruction_mode": "traverse"}),
            runs_dir=self.runs_dir,
        )["execution_estimate"]
        self.assertEqual(est["per_contender"], 2)

    def test_plan_items_carry_executor_auth_mode_for_preflight(self) -> None:
        plan = experiments.plan_experiment(self.payload(["task_a"]), runs_dir=self.runs_dir)
        for item in plan["plans"]:
            self.assertIn(item["executor_auth_mode"], ("env", "global", "copy-auth"))

    def test_web_search_override_flag_and_unenforceable_warning(self) -> None:
        payload = self.payload(
            ["task_a"],
            shared_extra={"web_search_mode": "deny"},
            contenders=[
                {"label": "GPT", "agent": "codex", "model": "gpt-5.5", "auth_mode": "global"},
                {"label": "Gemini", "agent": "gemini", "model": "gemini-3-pro", "auth_mode": "global"},
            ],
        )
        plan = experiments.plan_experiment(payload, runs_dir=self.runs_dir)
        by_agent = {item["agent"]: item for item in plan["plans"]}
        # Every contender's argv carries the override; only runtimes without an
        # enforcement hook get the honesty warning.
        for item in plan["plans"]:
            joined = " ".join(item["argv"])
            self.assertIn("--web-search deny", joined)
        self.assertFalse(
            [w for w in by_agent["codex"]["warnings"] if "web-search" in w]
        )
        gemini_warnings = [w for w in by_agent["gemini"]["warnings"] if "web-search" in w]
        self.assertEqual(len(gemini_warnings), 1)
        self.assertIn("not enforceable", gemini_warnings[0])

    def test_thinking_effort_forwarded_as_generic_flag(self) -> None:
        payload = self.payload(
            ["task_a"],
            contenders=[
                {
                    "label": "GPT",
                    "agent": "codex",
                    "model": "gpt-5.5",
                    "auth_mode": "global",
                    "thinking_effort": "xhigh",
                }
            ],
        )
        plan = experiments.plan_experiment(payload, runs_dir=self.runs_dir)
        joined = " ".join(plan["plans"][0]["argv"])
        self.assertIn("--thinking-effort xhigh", joined)
        self.assertNotIn("--claude-thinking-effort", joined)

    def test_thinking_effort_outside_the_runtimes_set_is_rejected(self) -> None:
        # gemini is a prompt runtime: xhigh has no instruction tier and no
        # native switch, so the plan must refuse it instead of passing it on.
        payload = self.payload(
            ["task_a"],
            contenders=[
                {
                    "label": "Gemini",
                    "agent": "gemini",
                    "model": "gemini-3-pro",
                    "auth_mode": "global",
                    "thinking_effort": "xhigh",
                }
            ],
        )
        with self.assertRaisesRegex(experiments.ExperimentError, "xhigh"):
            experiments.plan_experiment(payload, runs_dir=self.runs_dir)

    def test_plan_never_exposes_reasoning(self) -> None:
        """PRIVACY RED LINE: no private reasoning trace reaches the plan payload."""
        payload = self.payload(
            ["task_a", "task_b"],
            shared_extra={"instruction_mode": "select", "instruction_steps": ["H001"]},
        )
        plan = experiments.plan_experiment(payload, runs_dir=self.runs_dir)
        serialized = json.dumps(plan)
        self.assertNotIn("secret-H001", serialized)
        self.assertNotIn("reasoning", serialized)


class ExperimentRigorTest(unittest.TestCase):
    """Rigor injection: forwarding, plan-time guard, and that rigor does not
    expand executor variants (verified against runner.task_loader.build_task_runs,
    which attaches selected_rigors to each task run without adding runs)."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_gui_rigor_"))
        self.runs_dir = self.tmp / "runs"
        self.runs_dir.mkdir()
        self.tasks_dir = self.tmp / "tasks"
        self.tasks_dir.mkdir()
        self._write_task("task_a", ["G", "H"])
        self._write_task("task_b", ["G", "H", "K"])

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_task(self, task_id, rigor_ids) -> None:
        pkg = self.tasks_dir / task_id
        write_json(pkg / "task.json", {"id": task_id, "name": task_id})
        write_json(
            pkg / "rubrics.json",
            {"rubrics": [{"id": "R001", "fail_fast": True, "expected": True, "question": "?"}]},
        )
        (pkg / "prompt.md").write_text("# go", encoding="utf-8")
        if rigor_ids is not None:
            write_json(
                pkg / "rigors.json",
                {
                    "rigors": [
                        {"id": rid, "rubric_id": "R001", "requirement": f"must {rid}"}
                        for rid in rigor_ids
                    ]
                },
            )

    def payload(self, tasks, *, shared_extra=None, contenders=None, name="exp_rigor"):
        shared = {
            "evaluator_agent": "codex",
            "evaluator_model": "gpt-5.5",
            "evaluator_auth_mode": "global",
            "judge_mode": "single",
            "executor_backend": "local",
            "seed": 1,
            "repeat": 1,
        }
        if shared_extra:
            shared.update(shared_extra)
        return {
            "name": name,
            "tasks_dir": str(self.tasks_dir),
            "tasks": tasks,
            "shared": shared,
            "contenders": contenders
            or [{"label": "GPT", "agent": "codex", "model": "gpt-5.5", "auth_mode": "global"}],
        }

    def test_rigor_mode_and_ids_forwarded_to_every_contender(self) -> None:
        payload = self.payload(
            ["task_a", "task_b"],
            shared_extra={"rigor_mode": "select", "rigors": ["G", "H"]},
            contenders=[
                {"label": "GPT", "agent": "codex", "model": "gpt-5.5", "auth_mode": "global"},
                {"label": "Claude", "agent": "claude", "model": "claude-opus-4-8", "auth_mode": "global"},
            ],
        )
        plan = experiments.plan_experiment(payload, runs_dir=self.runs_dir)
        self.assertEqual(len(plan["plans"]), 2)
        for item in plan["plans"]:
            joined = " ".join(item["argv"])
            self.assertIn("--rigor-mode select", joined)
            self.assertIn("--rigor G", joined)
            self.assertIn("--rigor H", joined)

    def test_rigor_none_forwards_no_flag(self) -> None:
        plan = experiments.plan_experiment(
            self.payload(["task_a", "task_b"]), runs_dir=self.runs_dir
        )
        joined = " ".join(plan["plans"][0]["argv"])
        self.assertNotIn("--rigor-mode", joined)
        self.assertNotIn("--rigor ", joined)

    def test_select_unknown_rigor_rejected(self) -> None:
        payload = self.payload(
            ["task_a", "task_b"],
            shared_extra={"rigor_mode": "select", "rigors": ["ZZZ"]},
        )
        with self.assertRaisesRegex(ExperimentError, "none of the selected tasks"):
            experiments.plan_experiment(payload, runs_dir=self.runs_dir)

    def test_select_requires_at_least_one_rigor(self) -> None:
        payload = self.payload(
            ["task_a", "task_b"], shared_extra={"rigor_mode": "select", "rigors": []}
        )
        with self.assertRaisesRegex(ExperimentError, "at least one rigor"):
            experiments.plan_experiment(payload, runs_dir=self.runs_dir)

    def test_rigor_mode_rejects_unknown_value(self) -> None:
        payload = self.payload(
            ["task_a"], shared_extra={"rigor_mode": "ablation", "rigors": ["G"]}
        )
        with self.assertRaisesRegex(ExperimentError, "Rigor mode must be one of"):
            experiments.plan_experiment(payload, runs_dir=self.runs_dir)

    def test_rigor_present_in_only_one_task_is_allowed_at_plan_time(self) -> None:
        # Verified semantics (multi-task select): K exists in task_b but not
        # task_a. The plan-time guard only requires a rigor to exist in >=1
        # selected task; the runner enforces the stricter every-task rule at
        # launch and rejects the run naming task_a. The console does not pre-empt.
        payload = self.payload(
            ["task_a", "task_b"],
            shared_extra={"rigor_mode": "select", "rigors": ["K"]},
        )
        plan = experiments.plan_experiment(payload, runs_dir=self.runs_dir)
        self.assertIn("--rigor K", " ".join(plan["plans"][0]["argv"]))

    def test_rigor_does_not_change_execution_estimate(self) -> None:
        # Verified semantics: rigor injects into whatever variant the instruction
        # mode produces; it does not multiply executor variants. The estimate is
        # identical with and without rigor selection.
        without = experiments.plan_experiment(
            self.payload(["task_a", "task_b"]), runs_dir=self.runs_dir
        )["execution_estimate"]
        with_rigor = experiments.plan_experiment(
            self.payload(
                ["task_a", "task_b"],
                shared_extra={"rigor_mode": "select", "rigors": ["G", "H"]},
                name="exp_rigor2",
            ),
            runs_dir=self.runs_dir,
        )["execution_estimate"]
        self.assertEqual(with_rigor["per_contender"], without["per_contender"])
        self.assertEqual(with_rigor["total"], without["total"])
        self.assertEqual(with_rigor["per_contender"], 2)  # one run per task, unchanged


class ExperimentProfileSnapshotTest(unittest.TestCase):
    """Snapshot-on-use: launching from a roster-carrying profile attaches one
    contract snapshot per contender; bare launches attach nothing. The payload
    is the effective configuration and the profile is the comparison baseline:
    a deviating (ad-hoc) launch is allowed, and the backend diffs the two and
    annotates the snapshot with ``modified``/``modified_fields``."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_gui_snapshot_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.runs_dir = self.tmp / "runs"
        self.runs_dir.mkdir()
        self.tasks_dir = self.tmp / "tasks"
        self.tasks_dir.mkdir()
        for task_id in ("task_a", "task_b"):
            pkg = self.tasks_dir / task_id
            write_json(pkg / "task.json", {"id": task_id, "name": task_id})
            write_json(
                pkg / "rubrics.json",
                {"rubrics": [{"id": "R001", "fail_fast": True, "expected": True, "question": "?"}]},
            )
            (pkg / "prompt.md").write_text("# go", encoding="utf-8")
        # Providers the snapshot inlines (endpoint value + key env NAME only).
        write_json(
            self.runs_dir / "providers.json",
            {
                "providers": [
                    {
                        "id": "anthropic",
                        "name": "Anthropic",
                        "kind": "anthropic",
                        "auth": "api_key",
                        "base_url": "https://api.anthropic.com",
                        "api_key_env": "ANTHROPIC_API_KEY",
                        "models": ["claude-opus-4-8"],
                    },
                    {
                        "id": "openai",
                        "name": "OpenAI",
                        "kind": "openai",
                        "auth": "api_key",
                        "base_url": "",
                        "api_key_env": "OPENAI_API_KEY",
                        "models": ["gpt-5.5"],
                    },
                ]
            },
        )

    def save_profile(self, **overrides) -> None:
        profile = {
            "id": "hsw",
            "name": "HSW sweep",
            "shared": {
                "evaluator_agent": "codex",
                "evaluator_model": "gpt-5.5",
                "evaluator_auth_mode": "global",
                "judge_mode": "single",
                "evaluator_timeout_seconds": 600,
                "executor_backend": "local",
                "seed": 7,
                "batch_size": 2,
                "repeat": 5,
            },
            "per_contender_fields": ["model", "credentials"],
            "roster": [
                {
                    "agent": "claude",
                    "model": "claude-opus-4-8",
                    "provider_id": "anthropic",
                    "label": "Claude Opus",
                },
                {"agent": "codex", "model": "gpt-5.5", "provider_id": "openai"},
            ],
            "task_set": {"tasks_dir": str(self.tasks_dir), "task_ids": []},
        }
        profile.update(overrides)
        experiments.save_profiles(self.runs_dir, {"profiles": [profile]})

    def payload(self, **overrides):
        base = {
            "name": "exp_snapshot",
            "profile_id": "hsw",
            "tasks_dir": str(self.tasks_dir),
            "tasks": [],
            "shared": {
                "evaluator_agent": "codex",
                "evaluator_model": "gpt-5.5",
                "evaluator_auth_mode": "global",
                "judge_mode": "single",
                "evaluator_timeout_seconds": 600,
                "executor_backend": "local",
                "seed": 7,
                "batch_size": 2,
                "repeat": 5,
            },
            "contenders": [
                {
                    "label": "Claude Opus",
                    "agent": "claude",
                    "provider_id": "anthropic",
                    "model": "claude-opus-4-8",
                },
                {
                    "label": "GPT",
                    "agent": "codex",
                    "provider_id": "openai",
                    "model": "gpt-5.5",
                },
            ],
        }
        base.update(overrides)
        return base

    @staticmethod
    def snapshot_path_from(argv) -> str:
        return argv[argv.index("--profile-snapshot") + 1]

    def plan_snapshots(self, payload) -> list:
        """Plan the payload and return every contender's transported snapshot."""
        plan = experiments.plan_experiment(payload, runs_dir=self.runs_dir)
        return [
            json.loads(
                Path(self.snapshot_path_from(item["argv"])).read_text(encoding="utf-8")
            )
            for item in plan["plans"]
        ]

    def test_roster_profile_attaches_one_snapshot_per_contender(self) -> None:
        self.save_profile()
        plan = experiments.plan_experiment(self.payload(), runs_dir=self.runs_dir)
        self.assertEqual(len(plan["plans"]), 2)
        paths = set()
        for item in plan["plans"]:
            path = self.snapshot_path_from(item["argv"])
            paths.add(path)
            snapshot = json.loads(Path(path).read_text(encoding="utf-8"))
            # The transported file honours the public contract as written.
            validate_payload("profile_snapshot.schema.json", snapshot)
            # This run's column corresponds to the launched contender.
            self.assertEqual(snapshot["contender"]["agent"], item["agent"])
            self.assertEqual(snapshot["contender"]["model"], item["model"])
            self.assertEqual(snapshot["contender"]["label"], item["label"])
            # Roster context travels whole, resolved to inline values.
            self.assertEqual(len(snapshot["roster"]), 2)
            self.assertEqual(
                snapshot["roster"][0]["base_url"], "https://api.anthropic.com"
            )
            self.assertEqual(snapshot["roster"][0]["api_key_env"], "ANTHROPIC_API_KEY")
            # Profile identity + revision pin the contract as of launch.
            self.assertEqual(snapshot["profile"], {"id": "hsw", "rev": 1, "name": "HSW sweep"})
            # Instrument and execution mirror the shared configuration.
            self.assertEqual(snapshot["instrument"]["evaluator_agent"], "codex")
            self.assertEqual(snapshot["instrument"]["evaluator_auth_mode"], "global")
            self.assertEqual(snapshot["instrument"]["evaluator_timeout_seconds"], 600)
            self.assertEqual(snapshot["execution"]["seed"], 7)
            self.assertEqual(snapshot["execution"]["repeat"], 5)
            self.assertEqual(snapshot["execution"]["executor_backend"], "local")
            # Empty selector list resolved to every task in the directory.
            self.assertEqual(snapshot["task_set"]["task_ids"], ["task_a", "task_b"])
            # Credential discipline: env-var NAMES only, never key material.
            serialized = json.dumps(snapshot)
            self.assertNotIn("sk-", serialized)
            self.assertNotIn('"api_key"', serialized)
        self.assertEqual(len(paths), 2, "each contender gets its own snapshot file")

    def test_contender_snapshot_inlines_its_provider(self) -> None:
        self.save_profile()
        plan = experiments.plan_experiment(self.payload(), runs_dir=self.runs_dir)
        by_agent = {item["agent"]: item for item in plan["plans"]}
        claude = json.loads(
            Path(self.snapshot_path_from(by_agent["claude"]["argv"])).read_text(encoding="utf-8")
        )
        self.assertEqual(claude["contender"]["provider_id"], "anthropic")
        self.assertEqual(claude["contender"]["base_url"], "https://api.anthropic.com")
        self.assertEqual(claude["contender"]["api_key_env"], "ANTHROPIC_API_KEY")
        codex = json.loads(
            Path(self.snapshot_path_from(by_agent["codex"]["argv"])).read_text(encoding="utf-8")
        )
        # Official OpenAI provider: no base_url configured, key env still named.
        self.assertEqual(codex["contender"]["provider_id"], "openai")
        self.assertNotIn("base_url", codex["contender"])
        self.assertEqual(codex["contender"]["api_key_env"], "OPENAI_API_KEY")

    def test_snapshot_cites_the_current_profile_rev(self) -> None:
        self.save_profile()
        self.save_profile(name="HSW sweep v2")  # rev 2
        plan = experiments.plan_experiment(self.payload(), runs_dir=self.runs_dir)
        snapshot = json.loads(
            Path(self.snapshot_path_from(plan["plans"][0]["argv"])).read_text(encoding="utf-8")
        )
        self.assertEqual(snapshot["profile"]["rev"], 2)
        self.assertEqual(snapshot["profile"]["name"], "HSW sweep v2")

    def test_profile_without_roster_launches_bare(self) -> None:
        self.save_profile(roster=[])
        plan = experiments.plan_experiment(self.payload(), runs_dir=self.runs_dir)
        for item in plan["plans"]:
            self.assertNotIn("--profile-snapshot", item["argv"])

    def test_payload_without_profile_launches_bare(self) -> None:
        self.save_profile()
        payload = self.payload()
        del payload["profile_id"]
        plan = experiments.plan_experiment(payload, runs_dir=self.runs_dir)
        for item in plan["plans"]:
            self.assertNotIn("--profile-snapshot", item["argv"])

    def test_unknown_profile_id_rejected(self) -> None:
        self.save_profile()
        with self.assertRaisesRegex(ExperimentError, "ghost"):
            experiments.plan_experiment(
                self.payload(profile_id="ghost"), runs_dir=self.runs_dir
            )

    def test_dangling_payload_provider_rejected(self) -> None:
        # The snapshot inlines the PAYLOAD's providers (the effective config);
        # an unresolvable reference there still fails the plan — never a
        # half-true contract on disk.
        self.save_profile()
        payload = self.payload()
        payload["contenders"][0]["provider_id"] = "ghost"
        with self.assertRaisesRegex(ExperimentError, "ghost"):
            experiments.plan_experiment(payload, runs_dir=self.runs_dir)

    def test_dangling_profile_roster_provider_reads_as_deviation(self) -> None:
        # The profile is only the comparison baseline now: its dangling
        # reference no longer enters the snapshot (the effective roster does),
        # so the launch proceeds and the diff reports the roster deviation.
        self.save_profile(
            roster=[
                {"agent": "claude", "model": "claude-opus-4-8", "provider_id": "ghost"},
                {"agent": "codex", "model": "gpt-5.5", "provider_id": "openai"},
            ]
        )
        snapshot = self.plan_snapshots(self.payload())[0]
        self.assertTrue(snapshot["modified"])
        self.assertEqual(snapshot["modified_fields"], ["roster"])
        self.assertNotIn("ghost", json.dumps(snapshot))

    # -- Ad-hoc deviation record (payload = effective, profile = baseline) --

    def test_unmodified_launch_carries_no_deviation_marker(self) -> None:
        # The payload mirrors the profile exactly -> the snapshot looks the
        # same as before the deviation record existed (no marker keys at all).
        self.save_profile()
        for snapshot in self.plan_snapshots(self.payload()):
            self.assertNotIn("modified", snapshot)
            self.assertNotIn("modified_fields", snapshot)

    def test_label_only_change_is_not_a_deviation(self) -> None:
        # A contender label is display-only: renaming does not change what is
        # measured, so it must not mark the launch as modified.
        self.save_profile()
        payload = self.payload()
        payload["contenders"][0]["label"] = "Claude Opus (renamed)"
        for snapshot in self.plan_snapshots(payload):
            self.assertNotIn("modified", snapshot)

    def test_roster_deviation_records_the_effective_roster(self) -> None:
        # Launching a subset of the declared roster is an ad-hoc test: allowed,
        # marked, and the snapshot records what actually launched.
        self.save_profile()
        payload = self.payload()
        payload["contenders"] = [payload["contenders"][0]]  # drop the codex column
        snapshots = self.plan_snapshots(payload)
        self.assertEqual(len(snapshots), 1)
        snapshot = snapshots[0]
        validate_payload("profile_snapshot.schema.json", snapshot)
        self.assertIs(snapshot["modified"], True)
        self.assertEqual(snapshot["modified_fields"], ["roster"])
        # Effective roster, not the profile's two-column declaration.
        self.assertEqual(len(snapshot["roster"]), 1)
        self.assertEqual(snapshot["roster"][0]["agent"], "claude")
        self.assertEqual(snapshot["roster"][0]["base_url"], "https://api.anthropic.com")
        # The cited rev pins the BASELINE the launch deviated from.
        self.assertEqual(snapshot["profile"], {"id": "hsw", "rev": 1, "name": "HSW sweep"})

    def test_shared_single_key_deviation_names_the_key(self) -> None:
        self.save_profile()
        payload = self.payload()
        payload["shared"]["repeat"] = 1  # profile baseline says 5
        for snapshot in self.plan_snapshots(payload):
            validate_payload("profile_snapshot.schema.json", snapshot)
            self.assertIs(snapshot["modified"], True)
            self.assertEqual(snapshot["modified_fields"], ["repeat"])
            # The snapshot records the value that took effect, not the baseline.
            self.assertEqual(snapshot["execution"]["repeat"], 1)

    def test_task_set_deviation_marks_task_set(self) -> None:
        self.save_profile()  # profile task_ids [] = every task (task_a, task_b)
        payload = self.payload()
        payload["tasks"] = ["task_a"]
        snapshot = self.plan_snapshots(payload)[0]
        validate_payload("profile_snapshot.schema.json", snapshot)
        self.assertIs(snapshot["modified"], True)
        self.assertEqual(snapshot["modified_fields"], ["task_set"])
        self.assertEqual(snapshot["task_set"]["task_ids"], ["task_a"])

    def test_explicit_selectors_matching_the_profile_are_no_deviation(self) -> None:
        # The diff compares RESOLVED task sets: naming every task explicitly
        # equals the profile's "empty selectors = every task".
        self.save_profile()
        payload = self.payload()
        payload["tasks"] = ["task_a", "task_b"]
        snapshot = self.plan_snapshots(payload)[0]
        self.assertNotIn("modified", snapshot)

    def test_combined_deviation_lists_dimensions_then_shared_keys(self) -> None:
        self.save_profile()
        payload = self.payload()
        payload["contenders"][0]["model"] = "claude-sonnet-4-6"  # roster deviation
        payload["tasks"] = ["task_b"]  # task_set deviation
        payload["shared"]["seed"] = 99
        payload["shared"]["judge_mode"] = "both"
        snapshot = self.plan_snapshots(payload)[0]
        validate_payload("profile_snapshot.schema.json", snapshot)
        self.assertEqual(
            snapshot["modified_fields"], ["roster", "task_set", "judge_mode", "seed"]
        )

    def test_spelled_out_defaults_are_no_deviation(self) -> None:
        # Both sides normalize with the runner defaults: a payload spelling
        # out what the profile leaves implicit (and vice versa) is the same
        # measurement contract.
        self.save_profile()
        payload = self.payload()
        payload["shared"]["web_search_mode"] = "task"  # profile omits it
        payload["shared"]["max_evaluator_parallel"] = 4  # runner default
        payload["shared"]["seed"] = "7"  # same value, string-typed
        snapshot = self.plan_snapshots(payload)[0]
        self.assertNotIn("modified", snapshot)


if __name__ == "__main__":
    unittest.main()
