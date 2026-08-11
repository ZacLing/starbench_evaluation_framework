> **[已归档 2026-07-13]** 2026-07-08 的一次性交接快照，内容已过时。结构与边界的现行权威见 `docs/ARCHITECTURE.md`。本文只读，不再更新。

# 交接文档：Codex -> Claude

> 2026-07-08 更新。读者是下一位接手的 Claude Code / AI agent。
> 本文只记录当前 `gui-impeccable` 分支的产品判断、工程事实、硬约束和下一步。

## 1. 一句话定位

StarBench 不是一个普通 GUI，也不是把几条 agent CLI 命令包起来的 toy runner。
它的目标是成为 **coding-agent 评测的标准运行时与证据工作台**：

- `starbench-run` 是无状态执行引擎：输入任务包，输出 versioned run artifacts。
- `starbench-gui` 是本地驾驶舱：配置实验、运行 agent、看 trace、复盘证据。
- 平台侧可以直接消费 CLI argv 和 runs artifacts；GUI 不替代平台 UI。
- 长期商业化围绕两层资产：开源运行时/协议建立标准位置，专家 golden tasks / rubrics / run evidence 成为可售卖、可复用、可审计的评测资产。

参考 [`trycua/cua`](https://github.com/trycua/cua) 的逻辑：CUA 不是只卖一个 demo UI，而是把 sandbox、drivers、benchmarks、SDK 组合成 computer-use agents 的基础设施层。StarBench 对应的不是 desktop control，而是 coding-agent evaluation：多 runtime 适配、任务协议、artifact 协议、trace/rubric 证据、GUI 工作台。

## 2. 当前分支状态

当前工作分支：`gui-impeccable`。

最近完成的主线：

- Provider 页面重构：
  - AI Provider 只代表模型/endpoint 能力，不应该反向限制 agent。
  - API-key provider 按 wire protocol 匹配 runtime；通用可用时用统一 runtime 图标，不铺满所有 agent icon。
  - CLI login provider 是本地 CLI 账号状态，只属于对应 runtime，不代表所有兼容协议的 runtime 已登录。
  - `key set` 只代表环境变量存在；只有从 provider API 刷新成功才是 verified model list。
  - public catalog fallback 必须明确标注，不能冒充真实 API 连接。
  - OpenRouter 内置 Anthropic endpoint：`anthropic_base_url=https://openrouter.ai/api`。
- Agents / New experiment agent picker：
  - Agents 有本地 CLI 版本检测、npm latest 检测、一键安装入口。
  - Agent picker 不再显示可用模型数量；这里用户关心的是 CLI 是否可用、版本是否最新。
  - missing CLI 在 picker 中置灰但可点击，引导安装；checking 状态保持中性，不提前染成 warning。
  - `latest unknown` 这类 wording 已收敛为更温和的 "version check unavailable" 语义。
- Runtime provenance P1：
  - 新增 `src/starbench/runner/runtime_provenance.py`。
  - run-level 写入 `run_config.json` 的 `runtime_provenance`，最终 `summary.json` 也会带上同一对象。
  - task-level 写入 `logs/status.json` 的 `executor_runtime_provenance`。
  - 记录 StarBench version/git、executor/evaluator agent/model/backend、本地 CLI path/version、Docker image inspect、custom runtime spec sha256/public metadata。
  - 不记录 full env、API key、token、登录态路径。

最近验证过的关键测试：

```bash
PYTHONPATH=src:tests PYTHONPYCACHEPREFIX=/private/tmp/starbench_pycache \
  python3 -m unittest tests.runner.test_runtime_provenance tests.runner.test_closed_loop tests.gui.test_data

PYTHONPATH=src:tests PYTHONPYCACHEPREFIX=/private/tmp/starbench_pycache \
  python3 -m unittest tests.gui.test_experiments tests.gui.test_launcher

PYTHONPYCACHEPREFIX=/private/tmp/starbench_pycache \
  python3 -m compileall \
    src/starbench/runner/runtime_provenance.py \
    src/starbench/runner/orchestrator.py \
    src/starbench/runner/executor.py \
    src/starbench/gui/data.py
```

注意：这是针对最近改动的回归，不等同于全量 test suite 证明。

## 3. 当前代码地图

后端 runner：

- `src/starbench/runner/cli.py`：CLI 参数入口。
- `src/starbench/runner/orchestrator.py`：run loop、batch/progress、run_config/summary shape、env scoping、runtime provenance 调用点。
- `src/starbench/runner/executor.py`：executor task 执行与 `logs/status.json` 写入。
- `src/starbench/runner/judge.py`：judge 执行；下一阶段需要补 evaluator provenance 到 judge status。
- `src/starbench/runner/runtime_provenance.py`：当前新增的 provenance 捕获逻辑。
- `src/starbench/runner/custom_runtime.py`：custom runtime spec loader。

Adapter / runtime truth：

- `src/starbench/adapters/`：RuntimeInfo 与内置 adapter registry 是 runtime fact 的唯一来源。
- `runtimes/`：出厂 custom specs：qwen-code、kimi-code、trae-agent。

GUI server：

- `src/starbench/gui/providers.py`：provider storage、model refresh、public catalog fallback、CLI login status。
- `src/starbench/gui/agents.py`：agent listing、CLI version/latest check、install specs。
- `src/starbench/gui/experiments.py`：experiment/profile planning。
- `src/starbench/gui/launcher.py`：GUI launch -> plain `starbench-run` argv。
- `src/starbench/gui/data.py`：runs/task detail artifact reader。
- `src/starbench/gui/contracts.py`：Python -> TS contract source；改完必须重新生成 types。

Frontend：

- `gui-frontend/src/pages/Providers.tsx`：provider page。
- `gui-frontend/src/pages/Agents.tsx`：agents page。
- `gui-frontend/src/pages/NewRun.tsx`：new experiment wizard，仍然很大，后续适合拆分。
- `gui-frontend/src/lib/api-types.ts`：生成物，不手改。
- `src/starbench/gui/static/`：frontend build artifact，前端改动后要重建。

## 4. 产品红线

这些约束比局部 UI 方便更重要。

1. 不要把 current machine status 当成 completed run 证据。
   - Agents 页面显示的是当前机器。
   - Run detail / task detail 必须优先读 run artifact 中的 provenance。
2. 不要把 public catalog 当成 provider API 事实。
   - missing key / CLI cache 不可用时可以 fallback，但必须标注来源。
3. 不要把 CLI login 泛化成 protocol login。
   - Claude Code login 只属于 Claude Code。
   - Codex CLI login 是否可被 OpenCode 等其他工具复用，必须实证后再放开；当前不要靠猜测做 UI 承诺。
4. 不要落盘凭证。
   - GUI 只保存 env var name，不保存 API key value。
   - runner 通过 `STARBENCH_EXECUTOR_ENV_*` / `STARBENCH_JUDGE_ENV_*` 拆 executor/judge env。
5. `human_reference.json` 的 `reasoning` 是专家私有思路，不能进 GUI API。
6. server 只绑 `127.0.0.1`，不要为了“更像产品”打开多用户网络服务。
7. UI 文案要诚实：
   - "key set" 不是 "verified"。
   - "CLI found" 不是 "logged in"。
   - "latest unavailable" 不是 "outdated"。
   - "OpenAI-compatible" 不等于 Responses API 一定可用。

## 5. 下一步优先级

### P1：Runtime provenance GUI 展示

当前 backend P1 已落地，GUI 还没把这些字段展示出来。

目标：

- Run detail 的 configuration 区增加 Runtime provenance 小节。
- Task detail 的 Logs 或 Trace 邻近位置展示 executor provenance 摘要。
- 旧 run 缺字段时显示 `not recorded`，不要用当前机器状态补猜。
- 展示重点：
  - StarBench version / git commit / dirty。
  - executor agent / model / backend。
  - local CLI version/path 或 Docker image id/repo digest。
  - custom runtime spec sha256。
  - 探测失败的 `*_error`。

相关文件：

- `src/starbench/gui/data.py`
- `src/starbench/gui/contracts.py`
- `gui-frontend/src/pages/RunDetail.tsx`
- `gui-frontend/src/pages/TaskRunDetail.tsx`

验收：

- 新 run 能看到 provenance。
- 老 run 不报错。
- GUI 不调用 `/api/agents/status` 来反推历史 run。

### P2：Judge/evaluator provenance status

当前 evaluator provenance 在 run-level 中，但 judge status 文件还没单独写。

目标：

- `judges/single_status.json` 写 evaluator provenance。
- parallel judge 的每个 rubric status 也写 evaluator provenance。
- GUI 可以在 judge section 展示 evaluator runtime 快照。

相关文件：

- `src/starbench/runner/judge.py`
- `src/starbench/runner/orchestrator.py`
- `tests/runner/test_closed_loop.py`

### P3：JSON Schema protocol layer

之前讨论已定：JSON Schema 协议层应该和实现层/测试层解耦。

目标：

- 新建独立 schema 目录，例如 `schemas/` 或 `docs/schemas/`。
- 第一批覆盖：
  - task package：`task.json`、`rubrics.json`、`human_reference.json`、`rigors.json`。
  - run artifacts：`run_config.json`、`summary.json`、`logs/status.json`、`trace_summary.json`、`artifact_manifest.json`。
  - runtime provenance schema v1。
- 文档 `docs/artifact_contracts.md` 用人话解释 schema 的版本、兼容策略、平台消费方式。
- 测试只验证实现输出满足 schema，不把 schema 写死在测试里。

验收：

- 平台/外部消费者可以只看 schema 和 artifact docs 就知道怎么读 runs。
- runner 输出至少有一组 schema validation test。
- schema 不包含私密字段。

### P4：Provider / Agent 细节继续打磨

待查证或待实现：

- Codex CLI login 是否能被 OpenCode 或其他 OpenAI-protocol runtime 可靠复用。
  - 需要本机实测和文档证据；没证据前不要改产品语义。
- Trae Agent 是否有官方 CLI npm 安装包。
  - 当前 `INSTALL_SPECS` 没有 Trae，一键安装不可用是合理保守状态。
- DeepSeek / vendor OpenAI-compatible 的模型数量。
  - 不要显示 gateway 全量 catalog；只显示 vendor namespace 或 provider API 返回结果。
- OpenRouter/Vercel gateway 的 runtime count。
  - Vercel 有 OpenAI + Anthropic endpoint，所以比纯 OpenAI-compatible 多一个 channel。
  - OpenRouter 已内置 Anthropic endpoint；后续如再支持 Gemini endpoint，要显式字段化，不要硬编码图标数量。

### P5：前端结构债

`gui-frontend/src/pages/NewRun.tsx` 体积过大。后续可以拆：

- Agent picker cards。
- Provider/model selector。
- Review plan。
- Profile/shared config。
- Research add-ons。

拆分时不要顺手重写业务逻辑；先建立 snapshot tests 或等价测试。

## 6. 常用命令

启动本地 GUI：

```bash
PYTHONPATH=src python3 -m starbench.gui.server --no-browser --port 8321
```

后端/GUI 数据回归：

```bash
PYTHONPATH=src:tests PYTHONPYCACHEPREFIX=/private/tmp/starbench_pycache \
  python3 -m unittest tests.runner.test_closed_loop tests.gui.test_data

PYTHONPATH=src:tests PYTHONPYCACHEPREFIX=/private/tmp/starbench_pycache \
  python3 -m unittest tests.gui.test_experiments tests.gui.test_launcher tests.gui.test_agents
```

前端改动：

```bash
cd gui-frontend
npm run build
```

改 `contracts.py` 后：

```bash
make gen-types
git diff -- gui-frontend/src/lib/api-types.ts
```

## 7. Claude 接手建议

1. 先跑 `git status -sb`，确认没有用户未提交改动。
2. 如果任务是 GUI 展示，先读 `docs/gui.md`、`docs/agent_runtime_provenance.md` 和本文件。
3. 如果任务涉及 provider/agent，先读 `src/starbench/gui/providers.py`、`src/starbench/gui/agents.py`、`gui-frontend/src/pages/Providers.tsx`、`gui-frontend/src/pages/NewRun.tsx`。
4. 如果任务涉及 artifact contract，先写 schema/docs，不要直接把 schema 逻辑嵌进 runner。
5. 每个功能点小步 commit；提交前跑和改动面匹配的测试。

最容易踩坑的点：这个项目的价值在“可复现证据”和“协议化评测资产”，不是把 UI 做热闹。任何看似聪明的 fallback，只要会让用户误判一次 run 实际用过什么环境、什么模型、什么登录态，就应该明确标注或拒绝。
