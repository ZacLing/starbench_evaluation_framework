# 架构优化规划

> 目标：CLI 与 GUI 尽量解耦、runtime 知识收敛到单一事实源，使后续开发（包括交给
> 小模型执行的开发任务）只需要打开一两个小文件就能完成一次改动。
> 本文档是规划，不是现状描述；每个阶段独立可交付，交付时全量测试保持绿色。

## 1. 现状

### 1.1 模块地图（按行数）

| 模块 | 行数 | 职责（现状） |
|---|---|---|
| `runner/run_benchmark.py` | 2072 | argparse + 任务编排 + **29 处 per-agent 分支**（executor 派发、judge 派发、skill 安装位置、docker 能力、镜像默认值） |
| `runner/codex_process.py` | 1472 | 名为 codex，实为全部 runtime 的：命令构建 × 7、env 准备 × 5、Docker 包装 × 6、输出解析器 × 5、进程执行 |
| `gui-frontend/pages/NewRun.tsx` | 1472 | 向导视图 + **`providerSettings()` ≈130 行纯业务逻辑**（codex config overrides / claude env / gemini env / opencode gateway 的注入通道选择） |
| `gui/experiments.py` | 475 | 实验编排 + env 冲突检测（自带一份 judge 敏感变量表） |
| `gui/agents.py` | 387 | runtime 注册表（自带一份内置 runtime 元数据表） |
| `gui/library.py` | 468 | 任务导入 + preflight（自带一份 bin 名表和凭证 env 表） |
| `tests/test_runner.py` / `test_gui.py` | 1907 / 1328 | 两个巨型测试文件 |

### 1.2 核心病灶：runtime 知识散落九处

同一批事实（某 runtime 的可执行名、协议、凭证环境变量、Docker 镜像、注入通道、
judge 敏感变量）以手工同步的表格形式存在于：

```
runner/run_benchmark.py      BUILTIN_AGENTS + if/elif 链 + 镜像默认值解析
runner/codex_process.py      DEFAULT_DOCKER_IMAGES + 各 env 白名单
gui/agents.py                BUILTIN_AGENTS 元数据表（label/protocol/docker/bin）
gui/library.py               AGENT_BINS + AGENT_ENV_KEYS
gui/experiments.py           DOCKER_CAPABLE_AGENTS + JUDGE_ENV_SENSITIVE
gui/providers.py             KIND_TO_AGENT
gui/launcher.py              AGENT_CHOICES
gui/server.py                meta 里的 agents 列表
gui-frontend/brand.tsx       compatibleProviders 协议矩阵（TypeScript 重新实现一遍）
```

**加一个内置 runtime 目前要改 9 处**；漏一处就是一次静默不一致（本次开发中
“Docker 能力表未同步”“kind=runtime 旧文案”两个 bug 都源于此）。

### 1.3 结构性观察

1. **custom runtime 机制已经证明了正确抽象**。`runtimes/<id>.json` 用一份数据
   （command/args/parser/env/docker/protocol）驱动执行、Docker、GUI 三侧——
   而五个内置 runtime 反而是硬编码的 if/elif。抽象方向应当倒转：内置也成为
   “适配器”，数据驱动的 custom 只是其中一种适配器。
2. **GUI↔CLI 的契约是隐式的**。`launcher.py` 拼 argv、`experiments.py` 知道
   “codex 配置进程全局”“opencode gateway 一进程一份”这类 CLI 内部语义。
   契约没有文件形态，靠人脑同步。
3. **前端持有业务逻辑**。`providerSettings()`（注入通道选择）和
   `compatibleProviders()`（协议矩阵）是纯业务规则，却活在 React 组件里，
   与后端 `agents.py` 的同类逻辑双轨维护。
4. **executor 与 judge 共享进程环境**。这是“参赛者注入的 OPENAI_BASE_URL 会
   改写评审路由”这一类问题的根因；目前靠 GUI 计划期检测拦截（治标）。

## 2. 目标架构

```
┌─────────────────────────────────────────────────────────┐
│ gui-frontend/            纯视图；类型从契约文件生成        │
└──────────────▲──────────────────────────────────────────┘
               │ HTTP + contracts.py（唯一契约）
┌──────────────┴──────────────────────────────────────────┐
│ starbench/gui/           路由薄壳 + 服务模块              │
│   （experiments/providers/library/data 只做编排与校验）   │
└──────────────▲──────────────────────────────────────────┘
               │ 只读 registry 元数据 + 拼 argv
┌──────────────┴──────────────────────────────────────────┐
│ starbench/adapters/  ★ 单一事实源                        │
│   base.py      RuntimeAdapter 接口 + RuntimeInfo 元数据   │
│   registry.py  get(agent_id) → adapter（内置5 + custom）  │
│   claude.py codex.py gemini.py grok.py opencode.py       │
│   spec.py      custom：数据驱动的通用适配器               │
└──────────────▲──────────────────────────────────────────┘
               │
┌──────────────┴──────────────────────────────────────────┐
│ starbench/execution/     与 runtime 无关的执行原语        │
│   process.py  spawn/stdin/超时       docker.py  容器命令  │
│   parsers.py  headless-json / jsonl / claude-stream / …  │
├──────────────────────────────────────────────────────────┤
│ starbench/runner/        CLI                             │
│   cli.py argparse  orchestrator.py 任务循环               │
│   executor.py 执行侧     judge.py 评审侧（独立 env）       │
├──────────────────────────────────────────────────────────┤
│ starbench/core/          纯领域逻辑（无 IO）               │
│   models.py evaluation.py trace.py task_loader.py        │
└──────────────────────────────────────────────────────────┘
```

依赖方向自上而下单向；`adapters/` 是唯一写着“runtime 是什么”的地方。

### RuntimeAdapter 接口（草案）

```python
class RuntimeAdapter(Protocol):
    info: RuntimeInfo          # id/label/description/protocol/bin/
                               # docker_image/env_whitelist/credential_env_keys/
                               # judge_sensitive_env/injection(channel+env names)
    def build_executor_command(self, ctx: ExecContext) -> list[str]: ...
    def build_judge_command(self, ctx: JudgeContext) -> list[str]: ...
    def prepare_env(self, ctx) -> dict[str, str]: ...
    def docker_plan(self, ctx) -> DockerPlan | None: ...
    def parse_output(self, logs: Logs) -> None: ...
```

`RuntimeInfo` 直接序列化为 `/api/agents` 的响应——GUI 的 9 张表全部由它派生，
前端协议矩阵与注入通道不再手写。

## 3. 改造阶段

### P1 — Runtime Registry（杠杆最大，先做）

- 新建 `starbench/adapters/`，把 `codex_process.py` 与 `run_benchmark.py` 中的
  per-runtime 代码搬进五个适配器文件；custom spec 加载器变为 `spec.py` 通用适配器。
- `codex_process.py` 剩余部分拆为 `execution/{process,docker,parsers}.py`，
  原文件保留为兼容 re-export（一个发布周期后删除）。
- `run_benchmark.py` 的 executor/judge 派发链收敛为
  `adapter = registry.get(agent)` 一行。
- **验收**：29 处 if/elif → 0；`DEFAULT_DOCKER_IMAGES` 等表消失；
  全量测试绿；对外 CLI 参数与运行产物零变化。
- 风险：低（纯搬移）。工作量：主要在测试同步搬移。

### P2 — GUI 读 registry + 注入逻辑后移

- `gui/agents.py`、`library.py` preflight、`experiments.py` 冲突检测全部改读
  `RuntimeInfo`，删除各自的表。
- **前端 `providerSettings()` 下沉**：`/api/experiments`（dry-run）改为接收
  `(runtime, provider_id, model)`，由后端从 registry + provider 计算
  env/gateway/codex_bin；前端删除该函数与 `compatibleProviders` 中和后端重复的
  协议判断（改用 `/api/agents` 返回的 `compatible_provider_kinds`）。
- 新增 `gui/contracts.py`（API 形状的 dataclass/TypedDict 定义）
  + `make gen-types` 生成 `gui-frontend/src/lib/api-types.ts`，
  前后端类型从此不能漂移。
- **验收**：前端不再包含任何“哪个 runtime 用哪种注入”的知识；
  改一个 API 字段只需改 contracts.py 一处。
- 风险：中（行为等价性要靠 dry-run plan 对比测试兜底——新旧路径各生成一次
  plan，argv/env 逐字段断言相等，然后删旧路径）。

### P3 — Runner 拆分与 judge env 隔离

- `run_benchmark.py`（2072 行）拆为 `cli.py / orchestrator.py / executor.py /
  judge.py`，行为不变。
- **judge 独立 env**：judge 子进程使用自己的 env dict（从宿主 env + judge 自身
  凭证构建），不再继承 executor 注入后的进程环境。GUI 计划期的冲突拦截降级为
  防御性提示，不再是唯一防线。评审可信度从“靠检测”变为“靠构造”。
- **验收**：同一实验中 “qwen-via-OpenRouter 参赛 + codex 官方评审” 从被拒绝
  变为合法且评审路由正确（新增回归测试）。
- 风险：中。judge env 隔离改变一类此前被拒绝的配置的行为，需要文档同步。

### P4 — 面向小模型的工程约定（持续执行）

- **文件预算**：每模块 ≤ 400 行，文件头 docstring 写清职责、不变量、
  “改什么来这里”。超预算即拆。
- **测试对齐模块**：`test_runner.py`/`test_gui.py` 拆为
  `tests/adapters/test_claude.py`、`tests/gui/test_experiments.py` 等——
  小上下文窗口可以只加载“被改模块 + 它的测试”。
- **菜谱文档**（`docs/recipes.md`）：
  - 加一个数据型 runtime：写一个 JSON + 建一次实验验证（零代码）。
  - 加一个深度适配 runtime：`adapters/<id>.py` 一个文件 + registry 注册一行
    + `tests/adapters/test_<id>.py` 一个文件。
  - 加一个 API 字段：contracts.py → `make gen-types` → 用它。
  - 加一个 Provider 预设：providers.py 一处。
- **事实源速查表**（写进 `docs/DESIGN.md`）：任何“要改 X 去哪”的问题
  必须有唯一答案，答案里不允许出现“以及别忘了同步…”。

## 4. 不做什么

- 不引入 Web 框架 / ORM / 数据库。stdlib HTTP + 文件系统即真相源是产品原则
  （删除 run 目录 = 删除 run），不是技术债。
- 不做 monorepo 拆包、不发独立的 SDK。GUI 与 CLI 同仓同版本，解耦发生在
  模块边界与契约文件，不发生在仓库边界。
- 不把内置五个 runtime 降级为纯 JSON。它们的流式解析、home 隔离、
  compat-events 注入是真实的代码逻辑，adapter 类是它们的正确形态；
  JSON spec 服务的是长尾。
- 不追求前后端同构校验。校验只在后端一处；前端只负责即时反馈式的轻提示。

## 5. 执行顺序与当前建议

P1 → P2 → P3 可以各自独立成一个 PR 级交付；P4 穿插进行。建议下一步直接启动
P1（收益最大、风险最低、为 P2/P3 铺路），P1 完成后 GUI 侧代码量预计净减
约 200–300 行、runner 侧净减约 400 行分支代码。
