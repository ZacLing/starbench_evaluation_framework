"""Experiment planning, recording and custom-runtime contenders in gui.experiments."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

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

    def test_profiles_roundtrip_and_builtin_default(self) -> None:
        loaded = experiments.load_profiles(self.runs_dir)
        self.assertFalse(loaded["persisted"])
        self.assertEqual(loaded["profiles"][0]["id"], "standard")

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


class ExperimentCustomRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_gui_expcustom_"))
        self.runs_dir = self.tmp / "runs"
        self.runs_dir.mkdir()
        self.tasks_dir = self.tmp / "tasks"
        self.tasks_dir.mkdir()
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

    def test_custom_judge_env_merges_and_conflicts_detected(self) -> None:
        payload = self.payload()
        payload["shared"]["evaluator_agent"] = "custom:kimi-code"
        payload["shared"]["judge_env"] = {"KIMI_HOME": {"value": "/tmp/kimi"}}
        plan = experiments.plan_experiment(
            payload, runs_dir=self.runs_dir, runtimes_dir=self.runtimes_dir
        )
        for item in plan["plans"]:
            self.assertIn("KIMI_HOME", item["env_keys"])
            self.assertIn("--evaluator-agent custom:kimi-code", " ".join(item["argv"]))

        # A custom judge that reads the same variables the contender injects
        # (different value) must be rejected.
        payload = self.payload(name="exp_custom2")
        payload["shared"]["evaluator_agent"] = "custom:qwen-code"
        payload["shared"]["judge_env"] = {
            "OPENAI_BASE_URL": {"value": "https://api.openai.com/v1"}
        }
        with self.assertRaisesRegex(ExperimentError, "process-wide"):
            experiments.plan_experiment(
                payload, runs_dir=self.runs_dir, runtimes_dir=self.runtimes_dir
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
                    "thinking_effort": "high",
                }
            ],
        )
        plan = experiments.plan_experiment(payload, runs_dir=self.runs_dir)
        joined = " ".join(plan["plans"][0]["argv"])
        self.assertIn("--thinking-effort high", joined)
        self.assertNotIn("--claude-thinking-effort", joined)

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
                        {"id": rid, "rubric_id": rid, "requirement": f"must {rid}"}
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


if __name__ == "__main__":
    unittest.main()
