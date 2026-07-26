> **[已归档 2026-07-26]** 2026-07-09 的一次性需求基线快照，描述的是当时的系统，
> 不是现在的系统。其结构与所有权部分已被 `docs/ARCHITECTURE.md` 取代（该文是唯一权威），
> 里程碑与待确认问题已由 `docs/ARCHITECTURE.md` §5 路线图接管，
> 功能事实以代码与 `docs/` 下的操作参考为准。本文只读，不再更新。

# StarBench 测试框架 BRD：业务需求与功能需求

> 版本：v0.1  
> 日期：2026-07-09  
> 范围：基于当前 `gui-impeccable` 分支代码结构、公开文档、schema、GUI routes 与测试结构整理。  
> 目的：给产研、平台集成方和后续 AI agent 一份可执行的功能需求基线。

## 1. 文档定位

本文是 StarBench 测试框架的 Business Requirements Document（BRD）。

它回答四个问题：

1. StarBench 要服务什么业务场景。
2. 测试框架必须提供哪些功能能力。
3. 每个功能能力的业务规则、验收标准和数据制品是什么。
4. 当前代码中这些能力大致落在哪些模块，后续需求变更应该从哪里切入。

本文不是 API 参考，也不是代码架构说明。详细命令行参数以
[Runner Reference](../runner_reference.md) 为准，制品字段以
[Artifact Contracts](../artifact_contracts.md) 和 `schemas/starbench/v1/` 为准，
GUI 使用说明以 [StarBench Console](../gui.md) 为准。

## 2. 背景与业务目标

### 2.1 背景

Coding-agent CLI 正在快速分化：Claude Code、Codex、Gemini CLI、Grok Build、
OpenCode、Pi，以及各种厂商或开源 agent，运行方式、认证方式、事件格式、模型能力、
推理档位和工具权限都不同。企业或研究团队如果要选择、回归测试或持续改进 agent，
不能只看一次 demo 成功与否，需要有可重复的任务集、统一的执行隔离、稳定的评分规则、
可复盘的 trace 和可审计的 run artifacts。

StarBench 的定位是：

- `starbench-run`：无状态 benchmark 执行引擎。
- `starbench-gui`：本地单用户评测驾驶舱。
- task package 与 run artifacts：面向平台、GUI、CI、外部脚本的公开协议。
- profiles / coverage / schema：把一次次运行沉淀成可复用的测量合同和覆盖矩阵。

### 2.2 业务目标

| 目标 | 描述 |
| --- | --- |
| 标准化评测 | 用统一 task package、rubric 和 artifact contract 评测不同 coding-agent runtime。 |
| 降低运行门槛 | GUI 帮助操作者配置实验、选择任务、选择 agent/provider/model、运行预检并启动评测。 |
| 提高可复现性 | 每次 run 记录配置、profile snapshot、runtime provenance、trace summary 和 artifacts。 |
| 支持横向对比 | 通过 experiment/profile/coverage 矩阵比较多个 agent 或模型在同一任务集上的表现。 |
| 支持专家数据资产 | 通过 human reference、rigor、executor skills 把专家知识作为可控变量注入评测。 |
| 保护隐私与凭证 | 私有专家 reasoning、API key value、登录态文件不进入公开 API 或 artifacts。 |
| 支撑平台集成 | 平台可以直接调用 CLI 或消费 runs 目录，不需要依赖 GUI 内部状态。 |

### 2.3 产品边界

StarBench 是本地/CLI 优先的评测框架，不是多租户 SaaS。

| 范围内 | 范围外 |
| --- | --- |
| 本地运行 coding-agent benchmark。 | 多用户权限系统。 |
| 本地 GUI over `runs/` 文件系统。 | 中央数据库和远程队列服务。 |
| 多 runtime / provider / model 对比。 | 托管模型账号或代存 API key。 |
| 任务包导入、预览、schema 校验。 | 任务生产平台的完整工作流。 |
| 运行 trace、结果、coverage、profile snapshot 展示。 | 替代平台侧 eval UI。 |
| CLI argv 和 artifact contract 作为集成接口。 | 私有 GUI 状态作为平台 API。 |

## 3. 用户与使用场景

### 3.1 目标用户

| 用户 | 典型问题 | 核心需求 |
| --- | --- | --- |
| Benchmark operator | 这次 run 是否通过？哪个 rubric 失败？agent 实际做了什么？ | 快速启动、监控、复盘与定位问题。 |
| Agent 研发团队 | 新版本 agent 是否回退？某模型在哪些任务上失败？ | 批量重复运行、稳定 artifacts、横向比较。 |
| 任务/专家数据团队 | task package 是否合规？专家 instruction 是否带来 uplift？ | 任务校验、instruction ablation、rigor 注入、coverage 反馈。 |
| 平台集成方 | 如何调用 runner？如何读取结果？ | 稳定 CLI 参数、schema、run artifacts、兼容策略。 |
| 维护者/扩展开发者 | 如何接入新 runtime 或 provider？ | adapter registry、custom runtime spec、测试约束。 |

### 3.2 核心业务流程

1. 操作者把任务包导入 home 任务库。
2. 操作者配置 AI providers、agent runtimes、executor skills。
3. 操作者选择 profile 或临时配置一次实验。
4. 系统预检任务、agent CLI、凭证、Docker、provider/model 等运行条件。
5. 系统为每个 contender 生成并启动一个 plain `starbench-run`。
6. runner 为每个 task run 准备隔离 workspace，执行 executor，捕获 trace 和输出。
7. runner 用 evaluator 按 rubrics 评分，写入 judge artifacts。
8. GUI 从 runs 目录读取结果，展示 live progress、verdicts、trace、deliverables、logs。
9. Coverage 与 experiment 视图把多次运行沉淀成任务 × 配置的覆盖矩阵。
10. 平台或外部工具基于 artifacts/schema 消费结果。

## 4. 系统结构视图

### 4.1 代码模块边界

| 模块 | 主要职责 | 关键路径 |
| --- | --- | --- |
| Runner CLI | 参数解析、默认值、profile snapshot 校验、启动 run。 | `src/starbench/runner/cli.py` |
| Orchestrator | task ordering、batch、progress、executor/judge 调度、summary 写入。 | `src/starbench/runner/orchestrator.py` |
| Runtime adapters | 内置 runtime 运行命令、环境、解析逻辑。 | `src/starbench/adapters/` |
| Execution primitives | subprocess、Docker、parser、CLI probe。 | `src/starbench/execution/` |
| Task loader | task package 解析、材料复制、instruction/rigor variants。 | `src/starbench/runner/task_loader.py` |
| Evaluation | rubric result 聚合、single/parallel judge。 | `src/starbench/runner/evaluation.py`, `src/starbench/runner/judge.py` |
| Trace | raw events 到 normalized `trace_summary.json`。 | `src/starbench/runner/trace.py` |
| Runtime provenance | 捕获 CLI/Docker/spec/StarBench 版本证据。 | `src/starbench/runner/runtime_provenance.py` |
| Artifact contracts | schema 读取与校验。 | `src/starbench/contracts/`, `schemas/starbench/v1/` |
| GUI server | 本地 HTTP API、静态资源、launch registry。 | `src/starbench/gui/server.py` |
| GUI data reader | runs/task detail/live/coverage 读盘聚合。 | `src/starbench/gui/data.py` |
| GUI experiments | profiles、experiment plan、profile snapshot。 | `src/starbench/gui/experiments.py` |
| GUI resources | providers、agents、skills、task library。 | `src/starbench/gui/providers.py`, `agents.py`, `skills.py`, `library.py` |
| Frontend | Dashboard、Coverage、Tasks、Profiles、Agents、Providers、Runs、Details、NewRun。 | `gui-frontend/src/` |

### 4.2 单一事实源原则

| 事实 | 单一事实源 |
| --- | --- |
| runtime 能力、protocol、Docker image、provider filter、thinking levels | `RuntimeInfo` in `src/starbench/adapters/base.py` |
| custom runtime spec | `runtimes/<id>.json` |
| GUI API shape | `src/starbench/gui/contracts.py` -> `gui-frontend/src/lib/api-types.ts` |
| task package / run artifact 协议 | `schemas/starbench/v1/` + `docs/artifact_contracts.md` |
| 已完成 run 的结果事实 | `runs/<run_id>/` |
| 当前机器 CLI/版本状态 | `/api/agents/status`，只代表当前机器，不代表历史 run |
| provider 配置 | `<runs-dir>/providers.json` |
| profile 配置 | `<runs-dir>/profiles.json` |
| profile launch-time contract | `<run-root>/profile_snapshot.json` |

## 5. 功能需求总览

| 需求域 | 编号前缀 | 优先级 | 概述 |
| --- | --- | --- | --- |
| 任务包管理 | TASK | P0 | 定义、校验、导入、预览任务包。 |
| 运行引擎 | RUN | P0 | 批量运行 executor 和 evaluator，生成 artifacts。 |
| Runtime/Agent | AGENT | P0 | 管理内置和 custom agent runtime，检测安装与版本。 |
| Provider/Model | PROVIDER | P0 | 管理 endpoint、credential env name、model catalog。 |
| 实验与 Profile | EXP | P0 | 多 contender 对比，保存 profile，写 profile snapshot。 |
| Judge/Rubric | JUDGE | P0 | 单/并行 judge，rubric verdict 和证据。 |
| Trace/Artifacts | RESULT | P0 | 展示 trace replay、deliverables、logs、raw events。 |
| Coverage | COVERAGE | P1 | 任务 × 配置覆盖矩阵，发现缺口和 breach。 |
| Research controls | RESEARCH | P1 | instruction sweep、rigor、skills、thinking、web search。 |
| Artifact contracts | CONTRACT | P0 | schema 与公开制品兼容策略。 |
| Security/Privacy | SEC | P0 | 凭证、私有 reasoning、路径与环境隔离。 |
| GUI Console | GUI | P0 | 本地单用户驾驶舱，无数据库。 |

## 6. 详细功能需求

### 6.1 TASK：任务包与任务库

#### TASK-001 任务包基本结构

- 优先级：P0
- 用户价值：任务作者和平台可以用稳定目录结构交付 benchmark task。
- 功能描述：
  - 系统必须识别一个目录型 task package。
  - task package 至少包含 `task.json`、`prompt.md`、`rubrics.json`。
  - 可选包含 `human_reference.json`、`rigors.json`、`executor_skills.json`、materials。
  - executor 运行时只能看到 prompt 与 input materials，不能看到 rubrics 或私有 expert reasoning。
- 验收标准：
  - 合规 task package 能被 CLI 和 GUI 读取。
  - 缺少必需文件时，GUI task library 和导入流程必须给出明确错误。
  - task id 必须是安全 ID，不能逃逸目录。
- 模块映射：
  - `src/starbench/runner/task_loader.py`
  - `src/starbench/gui/library.py`
  - `docs/task_package.md`
  - `schemas/starbench/v1/task.schema.json`

#### TASK-002 任务材料复制与隔离

- 优先级：P0
- 功能描述：
  - runner 为每个 task run 创建独立 `workspace/`。
  - task materials 复制到 `workspace/inputs/`。
  - executor deliverables 必须写入 `workspace/outputs/`。
  - 每个 repeat / instruction variant 都应有独立 task run 目录。
- 验收标准：
  - executor 不能修改源任务包。
  - 不同 task run 的 workspace 互不污染。
  - artifact manifest 只统计 outputs 下的产物。
- 模块映射：
  - `src/starbench/runner/executor.py`
  - `src/starbench/runner/task_loader.py`
  - `src/starbench/runner/trace.py`

#### TASK-003 GUI 任务库浏览与导入（单一 home 库）

- 优先级：P0
- 功能描述：
  - GUI 只服务单一任务库：默认 `$STARBENCH_HOME/tasks`（`~/.starbench/tasks`），
    或启动时 `--tasks-dir` 指定的目录；应显示该目录及其中的 task package。
  - 目录注册与多目录浏览已下线：没有额外的"注册 task folder"入口；要服务
    另一个目录，需用不同的 `--tasks-dir` 重启控制台。
  - 用户可以拖拽 task folder 或 `.zip` 导入任务包到当前库。
  - 导入前必须做 server-side 校验；不合法时不能写入。
  - 上传大小必须受限，路径必须防 traversal。
- 验收标准：
  - dry run 能返回 errors/warnings/task summary。
  - 包含 `../` 或绝对路径的上传文件被拒绝。
  - 重名 task package 不覆盖已有目录。
- 模块映射：
  - `src/starbench/gui/library.py`
  - `src/starbench/gui/server.py`
  - `gui-frontend/src/pages/Tasks.tsx`
  - `gui-frontend/src/components/task-import.tsx`

#### TASK-004 任务预览

- 优先级：P1
- 功能描述：
  - GUI 应展示 prompt preview、rubrics、human reference step 数、rigor 数。
  - human reference 只展示 `step_id`、`step_type`、`instruction`。
- 验收标准：
  - `reasoning` 字段绝不出现在 API response。
  - 大 prompt 应截断而不是阻塞页面。
- 模块映射：
  - `src/starbench/gui/library.py`
  - `src/starbench/gui/data.py`
  - `gui-frontend/src/pages/Tasks.tsx`

### 6.2 AGENT：Runtime / Agent 管理

#### AGENT-001 内置 runtime 支持

- 优先级：P0
- 功能描述：
  - 系统必须支持 Codex、Claude Code、Gemini CLI、Grok Build、OpenCode、Pi 六类内置 runtime。
  - 每个 runtime 必须声明 id、label、protocol、bin、Docker image、provider filter、credential env、thinking capability。
  - runner 通过 adapter registry 解析 runtime，不应在 orchestrator 中硬编码 runtime 分支。
- 验收标准：
  - `--executor-agent` / `--evaluator-agent` 能解析内置 runtime。
  - `/api/agents` 能返回与 adapter registry 一致的 runtime metadata。
  - 新增 runtime 时只需要新增 adapter 并注册。
- 模块映射：
  - `src/starbench/adapters/base.py`
  - `src/starbench/adapters/registry.py`
  - `src/starbench/adapters/*.py`
  - `src/starbench/gui/agents.py`

#### AGENT-002 Custom runtime

- 优先级：P0
- 功能描述：
  - 用户可以通过 `runtimes/<id>.json` 定义 custom runtime。
  - custom runtime 必须声明 command、args、judge_args、prompt delivery、parser、env、Docker 配置等。
  - GUI 可创建、编辑、删除 custom runtime spec。
  - 预置 Qwen Code、Kimi Code CLI、Trae Agent spec。
- 验收标准：
  - `custom:<id>` 能被 CLI 和 GUI 共同识别。
  - spec 解析失败时 GUI 显示 error card，不崩溃。
  - custom runtime 的 provider filter 根据 protocol 派生。
- 模块映射：
  - `src/starbench/runner/custom_runtime.py`
  - `src/starbench/adapters/spec.py`
  - `src/starbench/gui/agents.py`
  - `runtimes/`

#### AGENT-003 CLI 安装、版本和更新检测

- 优先级：P1
- 功能描述：
  - GUI 应检测 agent CLI 是否存在、路径、当前版本。
  - 可安装 runtime 应提供安装/更新命令。
  - latest 检测可能访问 npm registry，应由用户显式触发或异步进行，避免阻塞首屏。
- 验收标准：
  - missing CLI 显示为不可直接运行，但可引导安装。
  - checking 状态不提前显示 warning。
  - version unavailable 不等于 outdated。
- 模块映射：
  - `src/starbench/gui/agents.py`
  - `gui-frontend/src/pages/Agents.tsx`
  - `gui-frontend/src/pages/NewRun.tsx`

#### AGENT-004 Agent 与 provider 兼容矩阵

- 优先级：P0
- 功能描述：
  - Agent 只表达运行时能力；provider 只表达模型/endpoint 能力。
  - runtime 是否能使用某 provider 由 `provider_filter` 和 injection channel 决定。
  - CLI login provider 只属于对应本地 CLI，不泛化成 protocol login。
- 验收标准：
  - OpenAI-compatible provider 不自动等同所有 OpenAI family runtime 可用。
  - 有 Anthropic endpoint 的 gateway 可被 Claude Code 使用。
  - UI 对通用 provider 用统一 runtime 图标，不铺满所有 agent icon。
- 模块映射：
  - `src/starbench/adapters/base.py`
  - `src/starbench/gui/injection.py`
  - `src/starbench/gui/providers.py`
  - `gui-frontend/src/pages/Providers.tsx`

### 6.3 PROVIDER：AI Provider 与模型目录

#### PROVIDER-001 Provider 配置

- 优先级：P0
- 功能描述：
  - GUI 管理 `<runs-dir>/providers.json`。
  - provider 字段包括 id、name、kind、auth、base_url、api_key_env、models、models_source、可选 anthropic/gemini endpoint。
  - GUI 只保存 API key 环境变量名，不保存 key value。
- 验收标准：
  - `key_present` 只能表示服务进程环境中 env var 存在。
  - key value 不出现在 providers.json、profile snapshot、run artifacts。
  - 内置 provider 首次读取时无需持久化即可显示。
- 模块映射：
  - `src/starbench/gui/providers.py`
  - `gui-frontend/src/pages/Providers.tsx`

#### PROVIDER-002 模型目录刷新与来源标记

- 优先级：P0
- 功能描述：
  - provider model list 应优先来自 provider 自己的 models API。
  - CLI login provider 可从本地 CLI cache 获取模型列表。
  - 缺 key 或 API 不可用时可 fallback 到 public catalog，但必须标注 `models_source=catalog`。
  - vendor OpenAI-compatible provider 的 catalog fallback 应按 vendor namespace 过滤，不能显示 gateway 全量模型。
- 验收标准：
  - public catalog 在 UI 中明确标注，不冒充真实 API 连接。
  - DeepSeek 等 vendor provider 不显示 OpenRouter/Vercel 的全部模型。
  - refresh 失败必须有可解释错误或保留旧数据，不导致 providers 页面不可用。
- 模块映射：
  - `src/starbench/gui/providers.py`
  - `gui-frontend/src/pages/Providers.tsx`
  - `tests/gui/test_providers.py`

#### PROVIDER-003 CLI login 状态检测

- 优先级：P1
- 功能描述：
  - 对支持检测的 CLI login provider，应显示 CLI 是否存在、登录状态和状态信息。
  - 检测应缓存，避免页面频繁触发慢命令。
  - 不支持检测的 CLI login 应显示 unknown，而不是 logged in。
- 验收标准：
  - Claude Code 未登录时不显示 logged in。
  - Codex CLI login 状态不代表 OpenCode 或其他 runtime 已可用。
- 模块映射：
  - `src/starbench/gui/providers.py`
  - `gui-frontend/src/pages/Providers.tsx`

### 6.4 RUN：运行引擎与调度

#### RUN-001 CLI run 基础配置

- 优先级：P0
- 功能描述：
  - `starbench-run` 支持 tasks-dir、runs-dir、task selection、repeat、seed、batch-size、run-id。
  - seed 控制 task shuffle、batch grouping 和 evaluator launch order；不承诺控制模型内部随机性。
  - batch-size 控制 executor 并发。
- 验收标准：
  - 指定 task list 与 repeat 后，`run_config.json` 记录 task_order。
  - run id 对应稳定输出目录。
  - batch-size 小于 1 被拒绝。
- 模块映射：
  - `src/starbench/runner/cli.py`
  - `src/starbench/runner/orchestrator.py`
  - `tests/runner/test_closed_loop.py`

#### RUN-002 Executor 执行与失败处理

- 优先级：P0
- 功能描述：
  - 每个 task run 执行一个 executor runtime。
  - executor status 需要记录 command、exit_code、timed_out、started_at、ended_at、duration。
  - executor crash/timeout 不能中断整个 run；该 task 标记失败并继续后续任务。
  - timeout 时 Docker container 必须被清理。
- 验收标准：
  - executor 失败时 `logs/status.json` 存在。
  - 单 task 失败不阻断其他 task 或 summary 写入。
  - `workspace/outputs/` 的产物被 manifest 捕获。
- 模块映射：
  - `src/starbench/runner/executor.py`
  - `src/starbench/execution/process.py`
  - `src/starbench/execution/docker.py`
  - `src/starbench/runner/orchestrator.py`

#### RUN-003 Local 与 Docker backend

- 优先级：P0
- 功能描述：
  - runtime 可声明默认 executor backend。
  - Docker capable runtime 可在每个 task run 中使用独立 container。
  - Docker image 默认来自 runtime metadata，也可由 CLI override。
  - 不支持 Docker 的 runtime 选择 Docker 时必须 fail fast。
- 验收标准：
  - Codex 默认 Docker；其他 runtime 按 metadata 决定。
  - custom runtime 只有声明 docker section 时才可 Docker。
  - Docker image 和 backend 进入 run config/status/provenance。
- 模块映射：
  - `src/starbench/adapters/base.py`
  - `src/starbench/runner/cli.py`
  - `docker/`

#### RUN-004 Progress events 与 live view

- 优先级：P0
- 功能描述：
  - runner 写入 append-only `progress_events.jsonl`。
  - GUI 根据 progress events 和 on-disk artifacts 判断 run 是否 running/complete/interrupted。
  - live view 应展示 task lanes、当前执行任务、event tail 和 ETA。
- 验收标准：
  - in-flight run 刷新时无需等待 summary.json。
  - 没有足够样本时 ETA 显示 estimating，不编造数值。
  - run stopped/interrupted 时 GUI 显示诚实状态。
- 模块映射：
  - `src/starbench/runner/progress.py`
  - `src/starbench/gui/data.py`
  - `gui-frontend/src/pages/RunDetail.tsx`

### 6.5 JUDGE：Rubric 与评审

#### JUDGE-001 Rubric yes/no 评估

- 优先级：P0
- 功能描述：
  - 每个 task package 提供 rubrics。
  - evaluator 根据 executor outputs、final message、trace summary、artifact manifest、prompt 和 rubrics 评估。
  - Judge 每条 rubric 只输出 rubric_id、JSON boolean answer、evidence。
  - expected、fail_fast 来自 task package，passed 由 runner 派生；Judge 不得自报最终 verdict。
- 验收标准：
  - judge aggregate 包含 outcome、overall_pass、passed_count、total_count、missing、fail_fast_failures。
  - Judge 输出缺失、类型非法或不可解析时 outcome 为 inconclusive_judge，overall_pass 为 null，不进入 HSW pass@n。
  - evidence 可在 GUI verdict pane 查看。
  - rubrics 不暴露给 executor。
- 模块映射：
  - `src/starbench/runner/judge.py`
  - `src/starbench/runner/evaluation.py`
  - `src/starbench/runner/prompts.py`
  - `schemas/starbench/v2/judge_aggregate.schema.json`（新写入）；v1 仅用于历史读取兼容。

#### JUDGE-002 Judge mode

- 优先级：P0
- 功能描述：
  - 支持 `single`：一个 evaluator 评估所有 rubrics。
  - 支持 `parallel`：每个 rubric 一个 evaluator。
  - 支持 `both`：同时输出 single 和 parallel 结果。
  - 支持 evaluator 并发上限。
- 验收标准：
  - `--judge-mode` 控制输出文件。
  - `--max-evaluator-parallel` 小于 1 被拒绝。
  - single/parallel aggregate 能在 task detail 中展示。
- 模块映射：
  - `src/starbench/runner/cli.py`
  - `src/starbench/runner/judge.py`
  - `src/starbench/runner/evaluation.py`

#### JUDGE-003 Executor/Judge 环境隔离

- 优先级：P0
- 功能描述：
  - 同一 `starbench-run` 进程中 executor 和 judge 必须有独立环境作用域。
  - `STARBENCH_EXECUTOR_ENV_*` 只注入 executor。
  - `STARBENCH_JUDGE_ENV_*` 只注入 judge。
  - 未加前缀的变量按传统 CLI 行为对两侧可见。
- 验收标准：
  - contender provider endpoint 不会意外 reroute judge。
  - 凭证值不通过 argv 或临时文件传输。
  - 测试覆盖 env scope。
- 模块映射：
  - `src/starbench/runner/env_scope.py`
  - `src/starbench/gui/launcher.py`
  - `tests/runner/test_env_scope.py`

### 6.6 EXP：Experiment、Profile 与 Profile Snapshot

#### EXP-001 Launch fan-out

- 优先级：P0
- 功能描述：
  - 一次批量启动 = 固定任务集 + 共享 judge/参数 + 多个 contenders。
  - 每个 contender 启动一个独立 `starbench-run`；批次名记录在各 run 的
    `run_state.json`（无独立启动记录实体）。
- 验收标准：
  - dry run 返回每个 contender 的 argv。
  - launch 后每个 contender 有独立 run id 和 launch log。
  - `/api/compare?runs=…` 能对任意 run 组合聚合 pass/fail 和 rubric matrix
    （无状态，从 artifacts 现算）。
- 模块映射：
  - `src/starbench/gui/experiments.py`
  - `src/starbench/gui/server.py`
  - `gui-frontend/src/pages/NewRun.tsx`
  - `gui-frontend/src/pages/ExperimentDetail.tsx`

#### EXP-002 Profiles

- 优先级：P0
- 功能描述：
  - GUI 支持保存 profiles 到 `<runs-dir>/profiles.json`。
  - profile 包含 shared config、per-contender fields、可选 roster、可选 task_set。
  - profile 保存时由 server 分配和递增 `rev`。
  - 内置 profile 包括 standard evaluation 和 HSW frontier sweep。
- 验收标准：
  - profile id 必须安全且唯一。
  - roster 不允许 credential-shaped unknown fields。
  - 内容不变的保存不递增 rev；内容变化递增 rev。
- 模块映射：
  - `src/starbench/gui/experiments.py`
  - `gui-frontend/src/pages/Profiles.tsx`
  - `schemas/starbench/v1/profile_snapshot.schema.json`

#### EXP-003 Profile snapshot

- 优先级：P0
- 功能描述：
  - 从带 roster 的 profile launch 时，系统必须生成 launch-time `profile_snapshot.json`。
  - snapshot 包含 profile identity/rev、contender、roster、instrument、execution、task_set。
  - provider reference 必须解析成 endpoint value 和 env var name。
  - snapshot 不包含 secret value。
  - runner 必须在创建 run 目录前校验 snapshot schema，失败则 fail closed。
- 验收标准：
  - profile 后续编辑不改变历史 run 的 snapshot。
  - snapshot schema violation 时不创建半成品 run。
  - ad-hoc deviation 记录 `modified` 和 `modified_fields`。
- 模块映射：
  - `src/starbench/gui/experiments.py`
  - `src/starbench/runner/cli.py`
  - `src/starbench/runner/orchestrator.py`
  - `schemas/starbench/v1/profile_snapshot.schema.json`
  - `tests/runner/test_profile_snapshot.py`

### 6.7 RESEARCH：专家能力与控制实验

#### RESEARCH-001 Human reference instruction modes

- 优先级：P1
- 功能描述：
  - `instruction-mode=none`：不注入专家指令。
  - `select`：注入选中 steps。
  - `traverse`：每个 step 生成一个 variant。
  - `ablation`：baseline + 每个 step + all-instructions variant。
  - 仅 `instruction` 可进入 prompt，`reasoning` 永远私有。
- 验收标准：
  - selected steps 写入 task manifest / summary。
  - ablation run 生成 `instruction_ablation_summary.json/md`。
  - private reasoning 不进入 executor workspace、GUI API 或 artifacts。
- 模块映射：
  - `src/starbench/runner/task_loader.py`
  - `src/starbench/runner/summary.py`
  - `src/starbench/gui/data.py`
  - `gui-frontend/src/pages/NewRun.tsx`

#### RESEARCH-002 Rigor prompt injection

- 优先级：P1
- 功能描述：
  - task 可提供 `rigors.json`。
  - 用户可选择 rigor requirement，把 rubric-level 要求重述为 executor hard requirement。
  - 默认关闭，作为可控实验变量。
- 验收标准：
  - 未选择 rigor 时 baseline prompt 不变。
  - 选择 rigor 后 manifest 记录所选 rigor。
  - GUI 显示 rigor 作为 Prompt assistance 的一部分。
- 模块映射：
  - `src/starbench/runner/task_loader.py`
  - `src/starbench/gui/data.py`
  - `gui-frontend/src/pages/NewRun.tsx`

#### RESEARCH-003 Executor skills

- 优先级：P1
- 功能描述：
  - 支持 task-local skills 和 shared registry skills。
  - 支持按 skill id 或 skill group 选择。
  - runner 把 selected skills 安装到 runtime-specific path。
  - skill 内容作为私有执行指导，不直接拼进 prompt。
  - skill 目录 sha256 应记录/校验。
- 验收标准：
  - selected skills 进入 run_config、manifest、task_summary。
  - hash mismatch 时 fail fast。
  - GUI Skills 页展示 skill 库、groups、文件数、大小、sha256。
- 模块映射：
  - `src/starbench/skills/registry.py`
  - `src/starbench/gui/skills.py`
  - `src/starbench/runner/executor.py`
  - `docs/executor_skills.md`

#### RESEARCH-004 Thinking effort 和 web search

- 优先级：P1
- 功能描述：
  - `thinking_effort` 根据 runtime capability 走 native_config 或 prompt instruction。
  - runtime 不支持的 effort level 必须启动前拒绝。
  - `web_search` 支持 task/allow/deny，对可强制 runtime 生效；其他 runtime 明确不保证。
- 验收标准：
  - GUI 只提供当前 runtime 支持的 thinking levels。
  - 不把 prompt-level request 误称为 native switch。
  - task `allow_web_search` 能被 run-level override。
- 模块映射：
  - `src/starbench/adapters/base.py`
  - `src/starbench/runner/cli.py`
  - `src/starbench/gui/experiments.py`
  - `tests/adapters/test_thinking_and_web.py`

### 6.8 RESULT：结果、Trace 与制品浏览

#### RESULT-001 Runs 列表与 Dashboard

- 优先级：P0
- 功能描述：
  - GUI 应列出 runs 目录中的所有 run。
  - run 状态包括 complete、running、interrupted。
  - Dashboard 展示 run 数、task pass rate、executor success、running now、recent runs。
  - Runs 页面支持排序、过滤和 profile/experiment 标记。
- 验收标准：
  - 缺 summary 的 running/interrupted run 仍可展示。
  - 单个坏 run 目录不能让整个列表崩溃。
- 模块映射：
  - `src/starbench/gui/data.py`
  - `gui-frontend/src/pages/Dashboard.tsx`
  - `gui-frontend/src/pages/Runs.tsx`

#### RESULT-002 Run detail

- 优先级：P0
- 功能描述：
  - 展示 run summary cards、live progress、task rows、configuration、profile snapshot、runtime provenance、ablation uplift。
  - 支持停止 GUI 启动的 running run。
  - 展示可复制的 recipe / command context，便于复现。
- 验收标准：
  - old run 缺 profile snapshot 或 runtime provenance 时显示 absence，不猜测。
  - live progress 从 `progress_events.jsonl` 和 on-disk artifacts 推导。
  - stop 只作用于本 GUI registry 启动的进程。
- 模块映射：
  - `src/starbench/gui/data.py`
  - `src/starbench/gui/launcher.py`
  - `gui-frontend/src/pages/RunDetail.tsx`

#### RESULT-003 Task detail

- 优先级：P0
- 功能描述：
  - Task detail 提供 Verdicts、Trace、Final message、Artifacts/Deliverables、Logs。
  - Trace replay 从 `logs/events.jsonl` 归一化 timeline，支持分页和 deep link。
  - Deliverables 读取 `artifact_manifest.json`，缺失时 fallback 到 outputs listing。
  - 文件预览必须处理 binary、超大文件、truncated 状态。
- 验收标准：
  - raw events 大文件分页，不能一次性塞爆页面。
  - artifact 路径不能逃逸 `workspace/outputs/`。
  - binary 文件显示不可预览，不乱码。
- 模块映射：
  - `src/starbench/gui/data.py`
  - `gui-frontend/src/pages/TaskDetail.tsx`
  - `schemas/starbench/v1/trace_summary.schema.json`
  - `schemas/starbench/v1/artifact_manifest.schema.json`

#### RESULT-004 Runtime provenance

- 优先级：P0
- 功能描述：
  - 每个 run 应记录 StarBench version/git、executor/evaluator runtime、model、backend、CLI path/version、Docker image id/digest、custom spec hash。
  - task status 应记录 executor runtime snapshot。
  - 检测失败不阻断 run，但必须记录 error。
- 验收标准：
  - `run_config.json` 和 `summary.json` 带 `runtime_provenance`。
  - `logs/status.json` 带 `executor_runtime_provenance`。
  - 不记录 full env、API key、token、登录态路径。
- 模块映射：
  - `src/starbench/runner/runtime_provenance.py`
  - `src/starbench/runner/orchestrator.py`
  - `schemas/starbench/v1/runtime_provenance.schema.json`
  - `tests/contracts/test_runtime_provenance_contract.py`

### 6.9 COVERAGE：覆盖矩阵

#### COVERAGE-001 任务 × 配置矩阵

- 优先级：P1
- 功能描述：
  - GUI 应聚合 library tasks 与 observed runs，形成任务 × executor config 矩阵。
  - config column 可来自 profile roster 或历史 run config。
  - cell 展示 total、judged、passed、inconclusive、last_tested、recent_refs。
  - 对 HSW 语义，某 task 在某配置上 `passed > 0` 表示该 task 被突破，需要被重点关注。
- 验收标准：
  - rostered 但未测试的 column 显示 coverage hole。
  - run 里存在但任务库已删除的 task 仍可作为 observed row 展示。
  - 点击 cell 能 drill down 到 contributing runs。
- 模块映射：
  - `src/starbench/gui/data.py`
  - `gui-frontend/src/pages/Coverage.tsx`

#### COVERAGE-002 Profile-aware coverage

- 优先级：P1
- 功能描述：
  - 当 profile 声明 roster 时，coverage denominator 来自 profile roster。
  - 没有 roster 时，coverage 从 runs 目录归纳 observed configs。
  - coverage payload 标注 profile id/name/rev。
- 验收标准：
  - 切换 profile 后 matrix columns 随 roster 变化。
  - profile rev 可见，避免误读旧合同。
- 模块映射：
  - `src/starbench/gui/data.py`
  - `src/starbench/gui/experiments.py`
  - `gui-frontend/src/pages/Coverage.tsx`

### 6.10 CONTRACT：公开协议与 schema

#### CONTRACT-001 Task package schema

- 优先级：P0
- 功能描述：
  - 任务输入协议应有 JSON Schema。
  - GUI 导入时应校验 task、rubrics、human_reference、rigors、executor_skills。
  - runner 读取时保留兼容，但公开协议按 schema 收敛。
- 验收标准：
  - 示例任务通过 schema tests。
  - schema 可独立供平台侧校验。
  - private field 只在明确标注为 private 的输入中出现。
- 模块映射：
  - `schemas/starbench/v1/*.schema.json`
  - `src/starbench/contracts/validation.py`
  - `tests/contracts/test_artifact_schemas.py`

#### CONTRACT-002 Run artifact schema

- 优先级：P0
- 功能描述：
  - 稳定 run artifacts 需要 schema_version 和 JSON Schema。
  - 支持 legacy run 缺 `schema_version` 的读取兼容。
  - 消费方应忽略未知字段，并对未知 future version 给出明确处理。
- 验收标准：
  - fake-runner output 通过 artifact schema tests。
  - GUI 对缺失字段宽容，不因单文件损坏崩溃。
  - runner 输出稳定 public artifacts 时带 `schema_version: 1`。
- 模块映射：
  - `schemas/starbench/v1/`
  - `src/starbench/contracts/`
  - `docs/artifact_contracts.md`

#### CONTRACT-003 API type generation

- 优先级：P0
- 功能描述：
  - GUI backend API shape 在 Python `TypedDict` 定义。
  - `make gen-types` 生成 TypeScript 类型。
  - 前后端字段名、nullability 不能漂移。
- 验收标准：
  - 修改 `src/starbench/gui/contracts.py` 后必须更新 `gui-frontend/src/lib/api-types.ts`。
  - tests 能检测 generated types drift。
- 模块映射：
  - `src/starbench/gui/contracts.py`
  - `scripts/gen_api_types.py`
  - `gui-frontend/src/lib/api-types.ts`
  - `tests/gui/test_contracts.py`

### 6.11 GUI：本地驾驶舱

#### GUI-001 本地单用户服务

- 优先级：P0
- 功能描述：
  - `starbench-gui` 启动本地 HTTP server。
  - 默认绑定 `127.0.0.1:8321`。
  - GUI 无数据库，所有状态来自 runs_dir、providers.json、profiles.json、runtimes、skills。
- 验收标准：
  - 删除 run 目录后 GUI 不再显示该 run。
  - 复制 run 目录进 runs_dir 后 GUI 可读取。
  - server 不默认暴露到局域网。
- 模块映射：
  - `src/starbench/gui/server.py`
  - `docs/gui.md`

#### GUI-002 New experiment wizard

- 优先级：P0
- 功能描述：
  - 新实验流程应覆盖：选择 mode/profile、选择 tasks、添加 contenders、配置 shared judge/execution/research controls、review plan、launch。
  - Review 必须展示实际将执行的命令和 launch plan。
  - 支持 dry run。
- 验收标准：
  - unknown runtime、missing task、duplicate run id 在 launch 前被拒绝。
  - preflight gate 能发现 CLI/Docker/credential 基础问题。
  - 用户可以从 profile 复用配置，也可以 ad-hoc 修改。
- 模块映射：
  - `gui-frontend/src/pages/NewRun.tsx`
  - `src/starbench/gui/experiments.py`
  - `src/starbench/gui/launcher.py`
  - `src/starbench/gui/library.py`

#### GUI-003 Navigation and resource pages

- 优先级：P1
- 功能描述：
  - GUI routes 至少包括 Dashboard、Coverage、Tasks、Profiles、Agents、Skills、Providers、Runs、Run detail、Task detail、Experiment detail、New experiment。
  - Shell 导航应按测量工作流组织，而不是营销页面。
  - 所有页面应处理 loading/error/empty 状态。
- 验收标准：
  - `/` 默认进入 Dashboard。
  - 不存在 route 重定向到 Dashboard。
  - 页面错误以可读 error note 呈现，不白屏。
- 模块映射：
  - `gui-frontend/src/App.tsx`
  - `gui-frontend/src/components/shell.tsx`
  - `gui-frontend/src/pages/`

## 7. 非功能需求

### 7.1 安全与隐私

| 编号 | 需求 |
| --- | --- |
| SEC-001 | API key value、auth token、登录态文件内容不得写入 prompts、artifacts、profiles、schemas、GUI API response。 |
| SEC-002 | GUI 只保存 credential env var name；运行时由 server/runner 从环境解析。 |
| SEC-003 | `human_reference.reasoning` 是 private expert data，不得进入 executor prompt、GUI API、public artifacts。 |
| SEC-004 | 文件路径输入必须防 path traversal；artifact 读取不能逃逸 run/task/output 目录。 |
| SEC-005 | GUI 默认绑定 `127.0.0.1`，不作为多用户网络服务。 |

### 7.2 可复现性

| 编号 | 需求 |
| --- | --- |
| REP-001 | run 必须记录 task_order、seed、repeat、batch_size、judge mode、models、agents、backend。 |
| REP-002 | profile-based run 必须保存 profile snapshot，历史 run 不受 profile 后续编辑影响。 |
| REP-003 | runtime provenance 必须 best-effort 记录 CLI/Docker/custom spec 版本证据。 |
| REP-004 | selected skills 必须记录 sha256；custom runtime spec 必须记录 sha256。 |
| REP-005 | instruction/rigor variants 必须在 manifest/task_summary 中可追溯。 |

### 7.3 可靠性与降级

| 编号 | 需求 |
| --- | --- |
| REL-001 | 单 task executor crash 不应中断整个 run。 |
| REL-002 | 缺失或损坏的 run artifact 不应导致 GUI 整页崩溃。 |
| REL-003 | 外部 CLI 版本、npm latest、provider model refresh 失败时应显示 error/warning，不阻塞核心浏览。 |
| REL-004 | 大日志、大 events、大 artifacts 必须分页、截断或标注不可预览。 |
| REL-005 | Docker timeout 必须清理容器。 |

### 7.4 可扩展性

| 编号 | 需求 |
| --- | --- |
| EXT-001 | 新内置 runtime 通过 adapter + registry 接入。 |
| EXT-002 | 非内置 runtime 通过 declarative custom spec 接入。 |
| EXT-003 | 新 public artifact 字段必须遵循 schema/version policy。 |
| EXT-004 | 新 GUI API 字段必须从 `contracts.py` 生成 TS types。 |
| EXT-005 | 新 provider kind/injection channel 必须和 runtime provider filter 一起定义。 |

### 7.5 可访问性与产品体验

| 编号 | 需求 |
| --- | --- |
| UX-001 | GUI 是 lab instrument 风格，信息密度高但不装饰化。 |
| UX-002 | verdict 必须用 glyph + text + color，不只靠颜色。 |
| UX-003 | 关键执行事实不能只藏在 tooltip。 |
| UX-004 | loading/checking 状态不能提前表达成功或失败。 |
| UX-005 | UI 文案必须区分 current machine status、run artifact evidence、public catalog fallback。 |

## 8. 数据与制品需求

### 8.1 输入制品

| 制品 | 业务含义 | 稳定性 |
| --- | --- | --- |
| `task.json` | task identity、prompt/rubric/materials 指针、timeout、web-search permission。 | Public |
| `prompt.md` | executor-facing task statement。 | Public |
| `rubrics.json` | evaluator-facing scoring criteria。 | Public |
| `human_reference.json` | expert steps；instruction public，reasoning private。 | Mixed |
| `rigors.json` | 可注入的 hard requirements。 | Public |
| `executor_skills.json` | task-local skills 声明。 | Public |
| `runtimes/<id>.json` | custom runtime spec。 | Public config |
| `<runs-dir>/providers.json` | GUI provider catalog config。 | GUI config |
| `<runs-dir>/profiles.json` | GUI profile config。 | GUI config |

### 8.2 输出制品

| 制品 | 业务含义 | 消费者 |
| --- | --- | --- |
| `run_config.json` | run 启动配置和 runtime provenance。 | GUI、平台、调试 |
| `summary.json` | run 级最终摘要。 | GUI、平台、报告 |
| `progress_events.jsonl` | live progress stream。 | GUI、monitor |
| `profile_snapshot.json` | launch-time measurement contract。 | GUI、平台、审计 |
| `<task_run>/manifest.json` | task run 输入和 research variant。 | GUI、审计 |
| `<task_run>/task_summary.json` | task run 结果摘要。 | GUI、平台 |
| `logs/events.jsonl` | runtime raw events。 | trace replay、debug |
| `logs/trace_summary.json` | normalized trace。 | GUI、judge、报告 |
| `logs/status.json` | executor status 和 runtime snapshot。 | GUI、平台 |
| `logs/final.md` | executor final answer。 | GUI、judge |
| `logs/artifact_manifest.json` | deliverables 文件清单。 | GUI、平台 |
| `judges/*` | judge result/status/aggregate。 | GUI、平台 |
| `instruction_ablation_summary.*` | expert instruction uplift summary。 | GUI、研究报告 |

## 9. 关键业务规则

1. 文件系统是 GUI 的事实源；GUI 不维护独立数据库。
2. Provider 的 `key set` 只代表 env var 存在，不代表 API 已验证。
3. CLI login 只属于对应 runtime，不代表同协议 runtime 已登录。
4. Public catalog fallback 必须标注来源，不可冒充 provider API。
5. Profile 是测量合同模板，profile snapshot 是某次 run 的合同证据。
6. Run artifact 是历史事实；current machine status 不能反推历史 run。
7. Executor 与 judge 环境必须隔离，防止 contender endpoint 影响 judge。
8. Rubrics 是 evaluator-facing，不得复制给 executor。
9. Human reference reasoning 是 private，不得跨 API/artifact 边界。
10. Schema evolution 要兼容 legacy v0，新增字段优先 optional。

## 10. 验收与测试映射

| 能力 | 主要测试入口 |
| --- | --- |
| Adapter registry / runtime commands | `tests/adapters/` |
| Runner closed loop | `tests/runner/test_closed_loop.py` |
| Environment scope | `tests/runner/test_env_scope.py` |
| Runtime provenance | `tests/runner/test_runtime_provenance.py`, `tests/contracts/test_runtime_provenance_contract.py` |
| Profile snapshot | `tests/runner/test_profile_snapshot.py`, `tests/contracts/test_profile_snapshot_contract.py` |
| Artifact schemas | `tests/contracts/test_artifact_schemas.py` |
| GUI data readers | `tests/gui/test_data.py` |
| GUI experiments/profiles | `tests/gui/test_experiments.py` |
| GUI agents/providers | `tests/gui/test_agents.py`, `tests/gui/test_providers.py` |
| GUI launch argv equivalence | `tests/gui/test_launcher.py`, `tests/gui/test_equivalence.py` |
| Task library import (single home library) | `tests/gui/test_library.py` |
| API type generation | `tests/gui/test_contracts.py` |

## 11. 里程碑建议

### M1：协议稳定化

- 把 `docs/artifact_contracts.md` 从草案推进为 v1。
- 明确 legacy v0 读取策略和 breaking change 流程。
- 平台侧以 schema 做一次读写契约验收。

### M2：Profiles / Coverage 产品闭环

- Profile roster/task_set 成为标准实验入口。
- Coverage matrix 支持 profile 切换、drill-down、缺口导出。
- Run detail 强化 profile snapshot drift 展示。

### M3：Runtime 生态扩展

- 完善 custom runtime templates。
- 明确 Trae Agent CLI 安装路径。
- 增加更多 provider injection channel 的实证支持。
- 将 Docker support 和 container-internal version provenance 做到更完整。

### M4：结果报告与平台集成

- 基于 run artifacts 生成标准评测报告。
- 提供平台侧读取 examples。
- 支持 CI 式回归阈值与失败摘要。

## 12. 待确认问题

1. `docs/artifact_contracts.md` 当前仍标为草案，何时进入强制 v1？
2. GUI Profiles 是否要支持导入/导出为独立文件，供团队共享？
3. Coverage 里的 HSW breach 语义是否应配置化，支持普通 pass-rate 场景？
4. Provider model refresh 是否需要后台队列或更明确的超时/重试策略？
5. Runtime provenance 是否要增加容器内 CLI version，而不只是 Docker image inspect？
6. 平台接入时是否只消费 `summary.json`，还是需要稳定读取 task-level artifacts？
7. 是否需要为 report/export 定义新的 public artifact schema？

## 13. 术语表

| 术语 | 定义 |
| --- | --- |
| Task package | 一个 benchmark 任务目录，包含 prompt、rubrics、materials 等。 |
| Runtime / Agent | 执行 task 的 coding-agent CLI，如 Codex、Claude Code、OpenCode。 |
| Executor | 被评测的 agent 侧。 |
| Evaluator / Judge | 根据 rubrics 评分的 agent 侧。 |
| Provider | 模型 endpoint 与 credential env name 的配置。 |
| Contender | 一次 experiment 中的一个被测 agent/model/provider 配置。 |
| Profile | 可复用的测量合同模板。 |
| Profile snapshot | 某次 run 启动时固化的 profile 合同证据。 |
| Run artifact | `runs/<run_id>/` 下的公开或诊断制品。 |
| Runtime provenance | 某次 run 实际运行环境的版本/路径/image/spec 证据。 |
| Coverage matrix | task × executor config 的历史测试覆盖矩阵。 |
| Rigor | 从 rubric 派生出的 executor hard requirement。 |
| Executor skill | 安装到 agent workspace 的私有执行指导目录。 |
