# Agent Runtime Provenance 规划

> 目标：让一次 StarBench run 的结果可以回答"当时实际用什么运行环境跑出来的"。
> 本文是实现前规划，不是当前行为说明。当前 GUI 可以即时显示 Agent CLI 版本，
> 但这些信息还没有进入 run artifact。

## 1. 背景

Agent 版本是 benchmark 可复现性的一部分。Claude Code、Codex、Gemini CLI、
Grok Build、OpenCode 以及自定义 runtime 都会随时间更新；同一个模型、同一组
任务，在不同 CLI 版本、不同 Docker image、不同 custom runtime spec 下可能有
不同的行为。

当前系统已经记录了：

- `runs/<run_id>/summary.json`：run 级配置、agent id、model、backend、docker image。
- `runs/<run_id>/<task_run_id>/logs/status.json`：单任务进程状态、耗时、exit code、
  backend、docker image、trace/artifact 路径。
- `runs/<run_id>/<task_run_id>/logs/trace_summary.json`：从 runtime events 归一出的
  行为 trace 摘要。
- `runs/<run_id>/<task_run_id>/logs/artifact_manifest.json`：executor 输出文件清单。

但当前没有结构化记录：

- executor/evaluator CLI 的实际版本。
- 运行时解析到的 CLI path。
- Docker image 的本地 image id / repo digest。
- custom runtime spec 的 sha256。
- StarBench framework 自身版本和 git commit。

这会导致事后只能说"用了 Claude Code / Codex / custom:qwen-code"，但不能准确说
"用了哪个版本、哪个 image、哪个 spec"。

## 2. 产品原则

1. **run artifact 是最终证据**  
   GUI 的 `/api/agents/status` 是当前机器的即时检测结果，只能用于配置前提示；
   它不能代表某次已经完成的 run。可复现性信息必须由 runner 在 launch/run 时
   写入 artifact。

2. **记录实际执行环境，不记录愿望配置**  
   如果 backend 是 Docker，host CLI 版本不是主要证据；应记录 Docker image 和
   容器内可探测到的 CLI 版本。host CLI 状态可以继续留在 Agents 页面，但不能被
   当作 Docker run 的 provenance。

3. **不泄露凭证和私密环境**  
   不记录 API key、auth token、完整 env、登录态文件路径、用户目录下敏感配置。
   路径字段只记录 CLI 可执行文件 path 或 runtime spec path；如后续发现 path
   泄露风险，可改成 basename + hash。

4. **best-effort 字段要显式标注错误**  
   不是所有 CLI 都支持 `--version`，也不是所有 Docker image 都有 repo digest。
   检测失败不能阻断 run，但必须记录 `*_error`，不能静默省略。

5. **trace 和 provenance 分层**  
   `trace_summary.json` 仍然只表达 agent 行为；runtime provenance 是环境元数据，
   应进入 `summary.json` / `logs/status.json`，不塞进 trace summary。

## 3. 字段草案

建议新增一个版本化对象：

```json
{
  "runtime_provenance_schema": 1,
  "captured_at": "2026-07-07T12:34:56.000000+00:00",
  "starbench": {
    "version": "0.1.0",
    "git_commit": "abc1234",
    "git_dirty": false
  },
  "executor_runtime": {
    "role": "executor",
    "agent": "claude",
    "label": "Claude Code",
    "model": "claude-opus-4-20250514",
    "backend": "local",
    "docker_image": null,
    "docker_image_id": null,
    "docker_repo_digests": [],
    "cli_bin": "claude",
    "cli_path": "/opt/homebrew/bin/claude",
    "cli_version": "2.1.177",
    "cli_version_output": "2.1.177",
    "cli_version_error": null,
    "custom_runtime_spec": null
  },
  "evaluator_runtime": {
    "role": "evaluator",
    "agent": "codex",
    "label": "Codex",
    "model": "gpt-5",
    "backend": "local",
    "docker_image": null,
    "docker_image_id": null,
    "docker_repo_digests": [],
    "cli_bin": "codex",
    "cli_path": "/opt/homebrew/bin/codex",
    "cli_version": "0.142.5",
    "cli_version_output": "codex 0.142.5",
    "cli_version_error": null,
    "custom_runtime_spec": null
  }
}
```

Custom runtime 的 `custom_runtime_spec` 建议结构：

```json
{
  "id": "qwen-code",
  "path": "/repo/runtimes/qwen-code.json",
  "sha256": "....",
  "public_metadata": {
    "label": "Qwen Code",
    "protocol": "openai",
    "parser": "text",
    "docker_image": "starbench-qwen:latest"
  }
}
```

说明：

- `public_metadata` 只放不含密钥的运行配置摘要。
- spec 全量内容暂不写入 run artifact，避免把 `env` 中的固定值误带出。
- 如果后续需要完整 spec replay，可以增加 redacted copy，但必须先做 redaction。

## 4. 写入位置

### 4.1 `runs/<run_id>/summary.json`

写入 run 级 snapshot：

```json
{
  "runtime_provenance_schema": 1,
  "starbench": { "...": "..." },
  "executor_runtime": { "...": "..." },
  "evaluator_runtime": { "...": "..." }
}
```

这是跨任务共享的 run 配置证据。GUI 的 Run detail 应优先从这里展示环境快照。

### 4.2 `runs/<run_id>/<task_run_id>/logs/status.json`

写入单任务实际执行 snapshot：

```json
{
  "executor_runtime": { "...": "..." }
}
```

原因：

- `status.json` 已经是 executor 进程状态和执行环境的最近邻。
- 单任务失败时，即使 run 级 summary 最终没有写完，仍能保留 executor 侧证据。
- 未来如果 per-task backend/image/env 有变化，也不会被 run 级字段掩盖。

### 4.3 Judge status

Evaluator/judge provenance 应进入 judge status：

- `judges/single_status.json`
- `judges/parallel/<rubric_id>/status.json`

这一步可以在 P2 做。P1 先保证 run-level summary 里有 evaluator snapshot。

## 5. 捕获时机

### 5.1 Run start

在 `starbench-run` 解析完 adapter、runtime spec、backend、docker image 后，立即生成
run-level provenance。这样即使后续任务失败，`summary.json` 或预备文件仍能说明运行
环境。

实现建议：

- 新增 `src/starbench/runner/runtime_provenance.py`。
- 提供 `capture_runtime_provenance(role, agent, adapter, model, backend, docker_image, custom_spec)`。
- orchestrator 在构造 `run_config` 时调用。

### 5.2 Executor task start

`run_executor()` 写 `logs/status.json` 时追加 executor snapshot。该 snapshot 可以复用
run-level executor provenance；如果 Docker 容器内版本探测很贵，P1 不必每个 task
重复探测。

### 5.3 GUI launch

GUI 不应该直接把 `/api/agents/status` 的结果塞进 launch payload。它最多可以在
Review step 显示"当前机器检测到的待运行版本"，但最终写入 artifact 的必须是
runner 自己捕获的 snapshot。

## 6. Local 与 Docker 的处理

### 6.1 Local backend

记录：

- `cli_bin`
- `cli_path`
- `cli_version`
- `cli_version_output`
- `cli_version_error`

版本探测：

- 默认执行 `<resolved_cli_path> --version`。
- timeout 建议 3 秒。
- 解析 semver，保留原始输出。
- 失败时记录 error，不阻断 run。

### 6.2 Docker backend

P1 记录：

- `docker_image`
- `docker_image_id`，来自 `docker image inspect`
- `docker_repo_digests`，如果 inspect 可得
- host CLI 字段置空或标注为 `host_cli_*`，不要混淆为实际执行版本。

P2 再尝试记录容器内 CLI 版本：

- 使用 adapter 提供的容器内 bin 或 image 默认 command。
- 以只读、无任务 workspace 的方式运行 `<bin> --version`。
- 对需要登录态或 workspace 初始化的 CLI，失败可接受，记录 error。

原因：容器内版本探测容易碰到 entrypoint、HOME、权限、auth 初始化差异，不能让它
成为 P1 的阻塞项。

## 7. StarBench 自身 provenance

建议记录：

- `starbench.version`：来自 `starbench.__version__`。
- `starbench.git_commit`：`git rev-parse --short HEAD`，失败则 null。
- `starbench.git_dirty`：工作区是否有未提交改动，失败则 null。

注意：

- `git_dirty=true` 不阻断 run，只提示复现风险。
- 不记录完整 diff；如果用户要做严谨发布，可在外部归档 patch。

## 8. GUI 呈现

### Run detail

在 configuration 区增加 `Runtime provenance` 小节：

- Executor：Agent、model、backend、CLI version / Docker image id。
- Evaluator：Agent、model、backend、CLI version / Docker image id。
- StarBench：version、git commit、dirty 状态。

如果字段缺失，显示 `not recorded`，不要猜测当前机器状态。

### Task detail

在 Logs 或 Trace 旁边展示 executor status 中的 provenance 摘要。重点用于排查：

- 这个 task 是否真的用了预期 backend。
- Docker image 是否与 run-level summary 一致。
- executor CLI version 是否探测失败。

### Agents 页面

Agents 页面继续显示当前机器即时检测状态，但文案要明确：

- `Current machine`
- `Used by completed runs` 只能来自 run artifact，不能从当前机器状态反推。

## 9. 实施阶段

### P1：最小可复现快照

目标：不改变运行流程，不阻断 run，只新增字段。

- 新增 runner provenance helper。
- local backend 捕获 CLI path/version。
- Docker backend 捕获 image id/repo digests。
- custom runtime 捕获 spec sha256/public metadata。
- `summary.json` 写入 executor/evaluator/starbench provenance。
- `logs/status.json` 写入 executor provenance。
- 单元测试覆盖本地 CLI version 成功/失败、custom spec hash、Docker inspect 失败。

### P2：Judge status 与 GUI 展示

- judge status 写 evaluator provenance。
- Run detail 展示 run-level provenance。
- Task detail 展示 executor provenance。
- 缺失旧字段时保持兼容。

### P3：容器内 CLI 版本

- adapter 增加可选 `version_command` 或 `container_version_command`。
- Docker backend best-effort 记录容器内 CLI version。
- 将 host CLI version 与 container CLI version 明确分字段。

## 10. 测试策略

后端测试：

- fake CLI 输出 `tool 1.2.3`，断言 `cli_version=1.2.3`。
- fake CLI `--version` 超时/非 semver，断言 `cli_version_error` 被记录且 run 不失败。
- custom runtime spec 修改后 sha256 变化。
- Docker inspect 命令失败时，`docker_image` 仍记录，error 字段存在。
- `summary.json` 与 `logs/status.json` 都包含 P1 字段。

GUI 测试：

- 老 run 没 provenance 时显示 `not recorded`。
- 新 run 显示 executor/evaluator/starbench provenance。
- Agents 页面当前机器状态不覆盖 run detail 的历史 provenance。

回归约束：

- 不把 API key/env/token 写入任何 provenance 字段。
- 不把 full custom runtime spec 原样写入 artifact。
- `trace_summary.json` schema 不变。

## 11. 待定问题

1. Docker image digest 使用 `Id` 还是 `RepoDigests` 作为主展示？
   - 建议 UI 主展示 `RepoDigests[0]`，没有 digest 时 fallback 到 `Id`。

2. custom runtime spec 是否需要保存 redacted copy？
   - P1 不保存。等 sha256 不能满足复现需求时再加。

3. GUI Review step 是否展示即将记录的 provenance？
   - 可以展示 current machine 的预检结果，但要标注这是 launch 前检测，最终以
     run artifact 为准。

4. 版本检测失败是否阻断 Launch？
   - 不阻断。CLI missing 才阻断；version unavailable 只降低可复现性 confidence。
