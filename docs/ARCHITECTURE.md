# StarBench 架构宪法

> 本文回答三个问题：真相存在哪里？哪个概念归谁拥有？我的改动会波及谁？
> 它是本仓库结构与边界的唯一权威。与其他文档冲突时，以本文为准；
> 本文过时时，改本文，不要另开新文档。

## 0. 分支定位

- 本分支线（`gui-impeccable` → `codex/frontend-decomposition` → 后继）是
  **main@33f7b31 的实验性 fork**，聚焦控制台（GUI）与 runtime 集成的探索
  开发。main 独立演进，本线不整体合并回 main。
- 面向 main 的缺陷修复不在本线堆叠：从 main 直接切分支、保持最小改动面、
  不携带本线概念（形态参考 `fix/judge-strict-bool`、
  `fix/docker-backend-preflight`）。
- 涉及 runner **语义**的改动（verdict 计算、聚合、公平性、种子），PR/提交
  说明必须写明对测量结果的影响。

## 1. 仓库全景

```
.
├── AGENTS.md                 agent 工作守则（GEMINI.md / CLAUDE.md 是它的薄引用）
├── Makefile                  test / gen-types / sync-schemas / docker-images / gui-build
├── schemas/starbench/        ★ 公共契约的唯一编写源（v1/、v2/）
├── src/starbench/
│   ├── domain/               纯领域逻辑，零 IO：SafeId、路径边界、verdict 分类、词表
│   ├── contracts/            白名单 JSON-Schema 校验器 + schema 的打包镜像（make sync-schemas 派生）
│   ├── adapters/             ★ runtime 唯一事实源：每个 agent CLI 一个 adapter（能力、镜像、env）
│   ├── execution/            进程/docker 原语（通用容器构建、输出解析）
│   ├── runner/               执行编排：cli(--plan) → orchestrator → executor / judge → summary
│   ├── lifecycle/            run 监督（core 侧）：预约、spawn、心跳、stop、reconcile
│   ├── gui/                  控制台后端（stdlib HTTP）
│   │   ├── server.py         路由层
│   │   ├── services/         应用服务：planning（launch_batch 规划）、profiles、console
│   │   ├── read_models/      只读视图：runs、coverage、compare、trace、catalog 缓存
│   │   ├── launcher.py       启动请求归一化 → run_plan / argv 渲染（永不 spawn）
│   │   └── contracts.py      API TypedDict（gen-types 的源，生成 api-types.ts）
│   ├── skills/ skill_distiller/ report/   executor 技能库 / 轨迹蒸馏 / 报告
│   └── fsio.py               共享原子 JSON 写
├── gui-frontend/src/
│   ├── pages/                路由页（Dashboard、Coverage、Runs、Compare、Profiles…）
│   ├── features/             多文件页面域（样板：new-run/ 五步向导）
│   ├── components/           ★ 共享控件（写控件前必先清点这里）
│   └── lib/                  api.ts（纯 fetch）+ api-types.ts（生成物，勿手改）
├── tests/                    按层镜像：domain / contracts / runner / lifecycle / gui / security
├── examples/tasks/           自带示例任务包（契约测试的真值样本）
├── docker/                   每 runtime 一个隔离镜像的 Dockerfile
├── runtimes/                 custom:<id> 运行时声明（runtimes/<id>.json）
├── scripts/                  gen_api_types.py、sync_schemas.py
├── docs/                     本文 + PRODUCT/DESIGN + 操作参考；archive/ 为历史规划
└── runs/                     运行产物（gitignored；文件系统即真相的落点）
```

★ = 单一事实源。`build/`、`__pycache__`、`src/starbench/gui/static/`（前端构建产物，
committed）不列。树只到达"该去哪个目录"的粒度；目录内布局以各模块 docstring 为准。

## 2. 分层与所有权

```
                    ┌─ gui-frontend/            控制台前端（React）
  console（操作面）─┤
                    └─ src/starbench/gui/       控制台后端（stdlib HTTP）
                         server → services → read_models → domain
  ───────────── 契约边界（见 §3，唯一过境点）─────────────
                    ┌─ src/starbench/runner/    执行编排（任务→执行→评审→聚合）
                    ├─ src/starbench/lifecycle/ run 监督（预约/spawn/心跳/stop/reconcile）
                    ├─ src/starbench/adapters/  runtime 唯一事实源（每个 CLI 一个 adapter）
  core（测量仪器）──┤─ src/starbench/execution/ 进程/docker 原语
                    ├─ src/starbench/domain/    纯领域逻辑，零 IO（SafeId、路径边界、verdict 分类、词表）
                    └─ src/starbench/contracts/ 契约校验器 + 打包的 schema 副本
```

| 概念 | 拥有者 | 落盘位置 |
|---|---|---|
| Task / Rubric / 执行与评审语义 | core | 任务包、run artifacts |
| run artifacts（summary、aggregate、trace…） | core（runner 是唯一写者） | `runs/<run_id>/` |
| `run_state.json`、`.runner_claim` | 监督器（`lifecycle/`，由 console 进程运行）——runner 之外唯一可写 run 目录的角色，且仅限这两个文件 | `runs/<run_id>/` |
| Profile（测量契约）、Coverage、向导、凭证目录 | console | `runs/profiles.json` 等 console 文件 |
| runtime 能力事实（docker_capable、thinking_efforts…） | adapters | 代码内 `RuntimeInfo` |

依赖方向单向：console 可以 import core，**core 永远不 import gui**。
read_models 不得向上 import services（需要 services 数据时由调用方注入参数）。

## 3. 过境契约

console 与 core 之间只允许通过以下契约对话，全部落盘、全部有 schema：

1. **artifact schemas**（`schemas/starbench/v1|v2/`）——读结果的唯一途径。
   镜像副本在 `src/starbench/contracts/schemas/`（随 wheel 发布），
   相等性测试守护，两处必须同步修改。
2. **`run_state.json`**——监督生命周期（含心跳、预约 token）。
3. **`progress_events.jsonl`**——进行中观测（append-only，可 tail）。
4. **`run_plan.schema.json`**——类型化启动契约：`starbench-run --plan plan.json`
   （互斥于逐旗标 argv；profile 快照内嵌其中；runner 将其物化为
   `<run-root>/run_plan.json` 工件）。自由旗标逃生舱（extra_args）走
   argv 传输（`gui/launcher.py` 渲染，与 plan 共享同一归一化校验）。

推论：任何第三方（人、agent、CI 脚本）凭这四份契约即可替换 console，
不需要 import 本仓库任何代码。新能力应优先扩展契约，而不是私开旁路。

## 4. 修改守则

- **schema 纪律**：凭证只允许出现环境变量**名**（`api_key_env`），永远不出现
  密钥值；`profile_snapshot` 全层级 `additionalProperties:false`（结构性防泄密）；
  artifact schema 变更走版本号（v1→v2），旧 artifact 永远可读（诚实降级，
  见 `domain/verdicts.py` 的 legacy 分类）。
- **HSW 语义**：AI pass = 任务被突破 = 坏消息。verdict 展示必须
  字形+文字+颜色三重编码；缺数据 = 诚实缺席，不发明状态。
- **前端复用**：写控件前先清点 `gui-frontend/src/components/`；页面超过约
  600 行或聚合多个独立 widget 时拆 `features/<名字>/`（样板：`features/new-run/`）。
- **测试**：runtime 兼容一律先写确定性 fake-CLI 测试；
  `PYTHONPATH=src uv run python -m unittest discover -s tests` 必须全绿才可提交。

## 5. 路线图（fork 内部，按序）

1. ~~fork 章程 + 文档收编~~（本文）
2. ~~概念清算~~：experiment 实体已移除（对比 = 无状态 `/api/compare`，
   批次名记录在 `run_state.json`）；schema 双树由 `make sync-schemas` 派生
3. ~~`gui/launcher.py` 拆分~~：argv 装配留在 `gui/launcher.py`，
   进程监督器独立成模块
4. ~~启动缝契约化~~：`run_plan.schema.json` + `--plan` 落地；
   监督器已迁 `starbench/lifecycle/`（core 侧，console 是它的第一个客户）
5. 前端大页 features/ 化（RunDetail 起）；UI 措辞清扫（experiment → launch/batch）

## 6. 文档地图

| 文档 | 角色 |
|---|---|
| `ARCHITECTURE.md`（本文） | 结构、边界、所有权——**唯一权威** |
| `AGENTS.md` | agent 工作守则（凭证红线、运行时注意事项） |
| `PRODUCT.md` / `DESIGN.md` | 前端设计宪法 / 视觉 token |
| `BRD.md` | 产品需求叙事（"做什么、为什么"） |
| `runner_reference.md`、`artifact_contracts.md`、`task_package.md` 等 | 操作参考 |
| `results_experience_plan.md` | 活跃规划（R3 报告导出未做） |
| `docs/archive/` | 已被取代的历史规划，只读不更新 |
