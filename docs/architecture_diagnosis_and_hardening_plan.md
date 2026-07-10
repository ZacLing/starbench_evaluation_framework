# StarBench 架构诊断报告与生产化优化规划

> 文档状态：诊断结论与实施规划
>
> 诊断日期：2026-07-10
>
> 诊断分支：`gui-impeccable`
>
> 诊断基线：`d055438`（`Improve task table selection`）
>
> 远端状态：诊断时本地比 `origin/gui-impeccable` 领先 1 个提交，工作区干净
>
> 适用范围：runner、runtime adapters、GUI backend、GUI frontend、artifact
> contracts、任务包、Judge 输出与本地进程生命周期

本文档固定当前分支的完整诊断结果，并给出从“高级工程原型”走向“可安全复用、
结论可信、可恢复运行”的实施路线。它不替代 `docs/architecture_plan.md`：后者记录了
runtime adapter、execution primitive 和 executor/judge env 拆分的上一轮重构；本文
聚焦上一轮之后仍未闭环的安全边界、HSW 测量语义、运行生命周期和工程规模问题。

---

## 1. 执行摘要

### 1.1 总体判断

StarBench 当前不是“架构混乱”，而是**局部抽象已经成立，系统级不变量尚未闭环**：

- `RuntimeAdapter`、`ExecutorContext`、`JudgeContext` 的方向正确，新增 runtime
  已经不必把所有逻辑重新塞进一个巨型 runner。
- executor、judge、process、docker 和 parser 已形成可识别的模块边界。
- 文件系统作为事实源、run artifact 可审计、runtime provenance 可追溯，符合
  benchmark 基础设施的产品定位。
- 但任务包路径、ID、Judge 输出、进程树、安装包资源和实验启动事务仍缺少强边界。
- GUI planner、runner CLI、生命周期和查询模型之间仍靠隐式约定连接，新增功能容易
  穿透多个层次。

综合评价：

| 维度 | 当前评价 | 说明 |
|---|---:|---|
| Runtime 扩展性 | 7/10 | Adapter/registry 方向正确，内置 runtime 已基本收敛。 |
| Executor/Judge 分层 | 6/10 | 环境开始隔离，但 plan、bin、gateway 和兼容规则仍有共享语义。 |
| Artifact/协议边界 | 4/10 | Schema 已存在，但打包、入口校验和 Judge 边界执行不完整。 |
| 安全隔离 | 3/10 | Docker 内执行不等于宿主机 staging 安全；路径和 symlink 尚未收口。 |
| 生命周期治理 | 3/10 | 进程注册在内存中，stop 不覆盖完整进程树，批量启动非事务。 |
| GUI/Runner 解耦 | 4/10 | 前端、GUI backend 和 runner 仍重复理解部分业务规则。 |
| 测试与可演进性 | 6/10 | 全量测试较完整，但关键边界缺少攻击性和故障注入测试。 |
| 综合 | 5.5/10 | 高级工程原型，骨架可保留，尚未达到生产级可信。 |

### 1.2 必须先处理的结论

在继续扩展 Provider、Agent、Profile 和结果页面之前，应优先完成 P0 hardening：

1. Judge 输出必须严格校验，任何字符串布尔值都不能进入评分模型。
2. `expected`、`fail_fast` 和 `passed` 的最终解释权必须属于任务协议和聚合器，
   不能由 Judge 自报。
3. 所有来自任务包、CLI、Profile 和 Judge 的 ID/相对路径必须通过统一边界类型。
4. Stop 必须终止完整进程树或容器，GUI 重启后必须能恢复控制状态。
5. Schema 必须随 wheel 安装，并增加“安装 wheel 后运行”的 CI smoke test。

如果这些问题不先解决，新增的 GUI 能力只会把不可靠的底层状态展示得更漂亮，无法
提升 HSW 结论的可信度。

---

## 2. HSW 的产品语义与测量不变量

### 2.1 HSW 不是普通 pass-rate benchmark

本框架服务于 **HSW Benchmark（Humans Still Win）**。任务资产的核心主张是：

```text
有效 HSW Task
= human reference 可以通过
+ roster 内 AI 配置在公平、可复现的测量契约下稳定无法通过
```

因此，系统必须同时支持两种视角：

- **Agent 视角**：Agent pass 表示本次执行满足全部 rubric。
- **Task/HSW 视角**：Agent pass 表示任务防线被突破，是需要关注的坏消息。

Coverage Matrix 必须使用 Task/HSW 视角；Task Run 详情可以保留 Agent 视角，但必须
明确标注，不能仅靠红绿颜色隐式表达。

### 2.2 HSW 不是“通过制造故障让 Agent 失败”

有效失败必须来自能力差距，而不是测量系统故障。以下情况都不能计入“Agent fail”：

- executor CLI 启动失败、超时、崩溃或凭证错误；
- Judge 启动失败、输出缺失、输出不符合 Schema；
- Docker、网络、Provider 429/5xx 等基础设施异常；
- task package 损坏或 rubric 自相矛盾；
- 隐藏要求、信息不对称或 human reference 也无法满足的任务。

建议将单次 Task Run 从一个 `overall_pass: bool` 提升为显式状态机：

```text
agent_pass                 有效 Judge 证据表明 Agent 满足全部 rubric
agent_fail                 有效 Judge 证据表明 Agent 未满足至少一个 rubric
inconclusive_executor      executor 失败，不能判断 Agent 能力
inconclusive_judge         Judge/解析失败，不能判断 Agent 能力
invalid_task               task/rubric/package 无效，测量不成立
```

只有 `agent_pass` 和 `agent_fail` 可以进入 HSW pass@n 的分母。其余状态必须单独显示，
不能被静默折算为 fail，否则会产生“虚假守住”；也不能折算为 pass，否则会产生
“虚假突破”。

### 2.3 Rubric 的权威字段

建议将数据所有权固定为：

| 字段 | 权威来源 | Judge 是否可写 |
|---|---|---|
| `rubric_id` | task package | 只能引用，必须存在且唯一 |
| `expected` | task package | 否 |
| `fail_fast` | task package | 否 |
| `answer` | Judge | 是，必须为 JSON boolean |
| `evidence` | Judge | 是，必须可审计 |
| `passed` | 聚合器派生 | 否，`answer == expected` |
| `overall_pass` | 聚合器派生 | 否 |

Judge 不应同时给出 `expected`、`fail_fast` 和 `passed`。让测量对象参与定义评分语义，
会扩大不一致和提示注入影响面。

---

## 3. 当前架构与实际依赖

### 3.1 当前主链路

```text
GUI React
  -> GUI HTTP API
  -> experiment/profile planner
  -> CLI argv
  -> runner orchestrator
  -> RuntimeAdapter
  -> local process / Docker
  -> executor artifacts
  -> Judge RuntimeAdapter
  -> Judge JSON
  -> normalize + aggregate
  -> run artifacts
  -> GUI filesystem read models
```

这条链路已经有模块，但关键数据在层间主要以 `dict`、JSON 和 CLI argv 传递。文件分开
不等于语义解耦：当同一个字段需要 GUI、planner、CLI、runner、adapter 和 artifact
共同解释时，任何一处默认值或校验漂移都会产生静默差异。

### 3.2 已经值得保留的部分

1. **RuntimeAdapter/registry**：runtime 专属命令、环境、parser 和 Docker 计划已有
   合理归属，不应回退到 shell wrapper 或 GUI 条件分支。
2. **Execution primitives**：process、docker 和 parsers 是可复用基础设施，适合
   继续下沉进 supervisor。
3. **Executor/Judge 分离**：两者概念和环境已经开始隔离，下一步应在 typed plan 和
   credential scope 上彻底分开。
4. **Filesystem as truth**：run artifact 是本产品的重要审计资产，不需要为了“现代化”
   强行改成数据库唯一事实源。
5. **Fake runtime tests**：确定性 fake CLI 是兼容测试的正确方法，真实 CLI 应只作为
   smoke test。

### 3.3 尚未真正解耦的部分

1. GUI 生成 runner argv，而不是提交稳定的 `RunPlan`。
2. GUI 和 runner 都理解 runtime/provider 注入、冲突和 fallback 规则。
3. task package、Judge response 和 artifact schema 没有形成一个强制执行的协议层。
4. launcher 既负责进程创建，又承担内存状态；server 负责批量启动顺序和实验落盘。
5. GUI 查询层直接遍历 run 文件系统并即时聚合，读模型、缓存和 API DTO 混在一起。
6. 前端页面持有大量向导状态、校验、派生计划和展示逻辑。

---

## 4. 信任边界诊断

### 4.1 正确的边界模型

```text
[不可信 task package]
          |
          v
[宿主机解析/路径校验/材料 staging]  <- 当前主要缺口
          |
          v
[Docker 或本地 executor]
          |
          v
[不可信 executor artifacts / trace]
          |
          v
[Judge runtime]
          |
          v
[不可信 Judge JSON]
          |
          v
[严格 Schema + 领域校验 + 派生 verdict] <- 当前主要缺口
          |
          v
[可信、不可变 run artifacts]
```

Task package、executor output 和 Judge output 都必须视为不可信输入。即使它们由内部
人员生产，也可能包含错误路径、symlink、旧 Schema 或模型生成的类型错误。

### 4.2 Docker 为什么不能覆盖宿主机路径风险

当前流程先在宿主机执行：

1. 读取 `task.json`；
2. 解析 materials 路径；
3. 创建 run/workspace/judge 目录；
4. 复制 task materials；
5. 再启动 Docker 并 bind mount 已经生成的 workspace。

因此，`../` 路径或目录内 symlink 在 Docker 启动前就可能读取宿主机文件。这里不是
“容器逃逸”，而是容器边界建立之前的 host-side staging 越界。

---

## 5. 完整诊断报告

### 5.1 诊断方法与基线

诊断基于以下证据：

- 阅读 runner、task loader、models、evaluation、judge、orchestrator、launcher、
  experiment API、adapter registry、contract schema 和 packaging 配置；
- 全量 Python 单元测试：345 项通过；
- `compileall` 通过；
- frontend lint 和 production build 通过；
- wheel 构建、解包和临时安装 smoke probe；
- path traversal、symlink、ID escape、字符串布尔值、重复 rubric ID 和进程树停止的
  定向 probe。

绿色测试不能推翻以下诊断，因为现有测试没有覆盖这些不变量。相反，这说明 CI 需要
补充边界测试，而不是说明问题不存在。

### 5.2 P0：会破坏安全或测量可信度

#### D-001 Judge 字符串布尔值会产生错误 verdict

- 位置：`src/starbench/runner/models.py` 的 `RubricResult.from_dict()`。
- 现状：使用 `bool(data["answer"])`、`bool(data["expected"])`、
  `bool(data["passed"])`。
- Python 语义：`bool("false") is True`。
- 触发条件：Judge 返回 JSON 字符串 `"false"`，而不是 JSON boolean `false`。
- 已验证：字符串 `"false"` 被构造成 `answer=True`、`passed=True`。
- 边界缺口：`normalize_single_result()` / `normalize_parallel_results()` 在构造领域对象
  前没有强制执行精确类型校验。

HSW 影响：

- 对常见的 `expected=true` rubric，Agent 实际未满足要求，却可能被记为 rubric pass；
- aggregate 可能进一步产生 `overall_pass=true`；
- Coverage Matrix 会把有效 HSW task 误报为被突破，即“虚假 HSW breach”；
- 对 `expected=false` 的禁止项也可能反向误判，因此不是单向偏差。

修复原则：

1. 只接受 `type(value) is bool`；禁止 truthy/falsy coercion。
2. Judge response schema 在构造领域对象之前强制校验。
3. Judge 只返回 `rubric_id/answer/evidence`。
4. `expected/fail_fast` 从 task rubric 读取，`passed/overall_pass` 由聚合器派生。
5. 非法 Judge 输出标记 `inconclusive_judge`，不得算作 Agent fail 或 pass。

#### D-002 Task materials 可以读取 task 根目录外的宿主机文件

- 位置：`src/starbench/runner/task_loader.py::_discover_material_paths()`。
- 现状：配置材料通过 `(task_dir / material).resolve()` 解析，但未验证解析结果仍在
  `task_dir` 内。
- 已验证：`materials: ["../outside_secret.txt"]` 可把 task 外文件复制进 workspace。
- 影响：任何 runner 当前用户可读文件都可能成为材料；若 Agent 或 Provider 能读取
  workspace，信息可进一步离开本机。

修复原则：

- 所有相对路径先做 lexical 校验，再 `resolve()` 并执行 containment check；
- 拒绝绝对路径、`..`、空路径和解析后越界；
- 错误信息只暴露必要路径，不打印凭证内容。

#### D-003 materials 目录内 symlink 会复制外部内容

- 位置：`src/starbench/runner/executor.py::copy_task_material()`。
- 现状：目录复制采用 `shutil.copytree()` 默认行为，会跟随文件 symlink。
- 已验证：task 材料目录中的 symlink 可把外部文件内容复制进 workspace。
- 影响：即使 `materials` 本身在 task 根内，目录内部仍可绕过边界。

修复原则：

- Task package 默认禁止所有 symlink；导入和运行前均扫描；
- 若未来确需支持，只允许解析后仍位于 task 根内的 symlink，并把策略写入协议版本；
- zip 导入也必须防 Zip Slip 和 symlink entry。

#### D-004 run/task/rubric ID 可以逃出目标目录

- 位置：
  - `src/starbench/runner/orchestrator.py`：`runs_dir / run_id`；
  - run task ID：task ID 与 instruction variant 参与目录名；
  - `src/starbench/runner/judge.py`：rubric ID 参与 parallel judge 目录名。
- 现状：这些 ID 没有统一 Safe ID 约束。
- 已验证：`../escaped_run`、多级 `../` instruction variant、rubric ID 可产生目标根外路径。
- 影响：跨 run 写入、覆盖其他实验目录、污染工作区，严重时可写到项目其他位置。

修复原则：

- 引入统一 `SafeId`，建议只允许 `[A-Za-z0-9][A-Za-z0-9._-]{0,127}`；
- ID 只能作为单个 path segment，不能包含 `/`、`\\`、`.`、`..` 或控制字符；
- 所有目标路径最终仍执行 `resolve_within(root, candidate)`，不能只依赖正则；
- task、rubric、rigor、instruction step、profile、experiment 和 run ID 使用同一规则。

#### D-005 Stop 没有终止完整进程树

- 位置：`src/starbench/gui/launcher.py::LaunchRegistry.stop()`。
- 现状：只对 runner 父进程调用 `process.terminate()`。
- 已验证：父进程退出后，其创建的子进程仍存活。
- 影响：Agent CLI、Judge、Docker、网络请求和 Token 消耗可能在 GUI 显示 stopped 后继续；
  子进程仍可能修改 workspace。

修复原则：

- POSIX 本地运行使用独立 process group/session；stop 先 TERM 整组，宽限后 KILL；
- Docker 记录 container ID/name，通过 `docker stop` + `docker kill` 收口；
- 启动时持久化 supervisor handle，退出时执行 best-effort cleanup；
- Stop API 必须幂等，并返回每个受控资源的停止结果。

#### D-006 Wheel 未携带公共 artifact schemas

- 位置：`src/starbench/contracts/validation.py` 与 packaging 配置。
- 现状：Schema 路径按源码仓库相对位置计算；root `schemas/starbench/v1` 未完整进入 wheel。
- 已验证：wheel 临时安装后调用公共 payload 校验触发 `FileNotFoundError`。
- 影响：源码 checkout 中测试正常，正式安装包运行失败；发布前 CI 无法发现。

修复原则：

- Schema 移入 Python package data，例如 `starbench/contracts/schemas/v1/`；
- 使用 `importlib.resources.files()` 读取；
- wheel/sdist 都显式包含；
- CI 构建 wheel、安装到空虚拟环境、运行 contract smoke tests。

### 5.3 P1：会造成结果不确定、孤儿任务或配置漂移

#### D-007 重复 rubric ID 未被拒绝

- rubric schema 和 task loader 未强制数组内 ID 唯一；
- parallel judge 会写入相同 rubric 目录；
- aggregate 使用 `{rubric_id: result}`，重复项静默覆盖；
- 已验证：同一 task 可以加载两个相同 rubric ID。

结果可能受并发完成顺序影响，违反 benchmark 可复现性。应在 task load 阶段 fail closed，
并对 rubric、rigor 和 instruction step ID 分别做唯一性校验。

#### D-008 多 Agent 实验启动不是事务

- 位置：`src/starbench/gui/server.py::_handle_create_experiment()`。
- 现状：逐个 `registry.launch()`，全部成功后才形成完整 experiment record。
- 风险：中途失败时，前面已启动的 runner 继续运行，API 却返回失败；操作者缺少完整记录
  和统一 stop 入口。

应采用 prepare/commit 两阶段：先验证所有 plan、run ID、目录和资源，再统一启动；commit
阶段失败则回滚已启动 handle，并写入包含失败原因的 experiment record。

#### D-009 LaunchRegistry 只在内存中保存真实进程句柄

- GUI 重启后丢失 process handle；
- 当前 run status 会退化到 artifact 和 progress mtime 推断；
- 长时间没有 progress 写入的合法任务可能被误判 interrupted；
- 重启后无法可靠停止仍在运行的进程或容器。

应持久化 `run_state.json`，记录 PID、process group、container ID、started_at、heartbeat、
stop intent 和终态。GUI 启动时执行 reconcile，而不是仅凭 mtime 猜测。

#### D-010 `overall_pass=false` 混合了能力失败和测量失败

当前 aggregate 的布尔结果不足以表达 executor error、Judge error、missing result 与真实
Agent fail。HSW 中，这会同时产生两类危险：

- 把 Judge/运行故障计为 Agent fail，制造“任务仍然守住”的虚假证据；
- 把解析错误计为 Agent pass，制造“任务被突破”的虚假告警。

这不是单纯 UI 文案问题，而是领域模型缺失。必须引入 `TaskRunOutcome`，并让 Coverage
只聚合有效 judged samples。

#### D-011 Runtime single source of truth 尚未完全闭环

- 内置 runtime 已主要由 adapter registry 驱动；
- custom runtime 的 protocol、credential env、base URL env 等元数据仍有 GUI 读取 raw
  JSON 的旁路；
- GUI 仍保留部分历史“process-wide env conflict”规则；
- executor 和 Judge 的 bin/gateway 配置仍有共享字段，容易让合法组合被阻止，或未来
  再次发生路由串扰。

应让 adapter 只产出 `RuntimeInvocation`，GUI 不理解 env key 或 CLI flag；executor 与
Judge 分别拥有独立 typed config，不共享可变 gateway/bin 字段。

### 5.4 P2：会持续放大维护成本和性能问题

#### D-012 GUI backend 读模型过大且重复扫描文件系统

- `src/starbench/gui/data.py`：1734 行；
- `src/starbench/gui/experiments.py`：1330 行；
- task history、coverage、run list 和 JSONL 分页会重复遍历或读取完整数据；
- run 数量增长后，页面延迟会随磁盘对象数量近似线性增长。

文件系统仍应是事实源，但应增加可重建的 `RunCatalog` 读索引，以 path + mtime + size
作为增量键。索引损坏可删除重建，不能成为第二事实源。

#### D-013 前端页面与 API 类型边界过大

- `gui-frontend/src/pages/NewRun.tsx`：3882 行；
- `gui-frontend/src/lib/api.ts` 仍有大量手写接口；
- 向导状态、服务端 plan、校验、preflight、Profile 偏差和 UI 展示混在单页；
- production bundle 已出现大 chunk 警告。

应按步骤与领域 hook 拆分，所有服务端 DTO 从 Python contracts 生成。前端可以做即时
表单反馈，但不能重新实现 runtime、credential、HSW verdict 或 launch eligibility。

---

## 6. 根因归纳

以上问题并非十三个互不相关的 bug，主要来自五个系统性根因：

### 6.1 协议存在，但没有成为强制边界

Schema、文档和 dataclass 都存在，但输入经常直接进入 `dict -> bool()/str() -> model`。
协议没有在进程、文件、HTTP 和安装包边界统一执行。

### 6.2 路径和值对象没有领域类型

`run_id: str`、`rubric_id: str`、`material: str` 看起来简单，却分别承担 path segment、
引用和相对路径语义。普通字符串无法携带这些不变量。

### 6.3 Launch 被当作函数调用，不是生命周期聚合

启动一个实验实际上包含计划、预留、创建多个进程、持久化、监控、停止和恢复。当前
分散在 server、launcher 和 artifact 推断中，因此无法提供事务与重启恢复。

### 6.4 Artifact truth 与 query model 没有分层

“文件系统是真相源”被误解为“每次请求都重新扫描全部文件”。事实源和可重建读索引
并不冲突，应明确区分 write model 与 read model。

### 6.5 HSW 语义没有进入领域状态机

单个 `passed`/`overall_pass` 同时服务 Agent 详情和 HSW Coverage，导致能力失败、系统
失败、任务突破和任务守住缺少明确类型，只能依赖页面文案反转颜色。

---

## 7. 目标架构

### 7.1 依赖方向

```text
gui-frontend
    |
    v
gui API routes -> application services -> domain
                       |                 ^
                       v                 |
                 repositories      contracts/value objects
                       |
                       v
              filesystem artifacts/read index

runner CLI -> RunPlanner -> RunSupervisor -> RuntimeAdapter -> execution primitives
                 |              |                 |
                 v              v                 v
              RunPlan       RunState        RuntimeInvocation
```

规则：

- UI 和 HTTP route 不直接拼 runtime env/argv；
- adapter 不负责业务聚合或 artifact 状态；
- domain 不依赖 GUI、subprocess、Docker 或具体 Provider；
- repository 不决定 HSW verdict，只负责可靠读写；
- 所有跨层 payload 都是版本化 typed contract。

### 7.2 建议模块

```text
src/starbench/
  contracts/
    schemas/v1/              随 wheel 安装的 JSON Schema
    validation.py            Schema 入口
    versions.py              兼容策略

  domain/
    identifiers.py           SafeId 及各类 ID
    paths.py                 SafeRelativePath / resolve_within
    rubrics.py               RubricDefinition / JudgeAnswer
    verdicts.py              TaskRunOutcome / aggregate 纯函数
    plans.py                 RunPlan / ExecutorPlan / JudgePlan

  adapters/
    base.py                  RuntimeAdapter / RuntimeInfo
    ...                      只实现 runtime 差异

  execution/
    invocation.py            RuntimeInvocation
    process.py               spawn/process group/timeout
    docker.py                container lifecycle
    supervisor.py            Handle/stop/reconcile

  runner/
    planner.py               输入配置 -> typed RunPlan
    orchestrator.py          消费 RunPlan，不重新解释配置
    staging.py               task workspace 安全物化
    judging.py               Judge response 校验与领域转换
    artifacts.py             原子写入/versioning

  gui/
    routes/                  薄 HTTP 层
    services/                launch/profile/task application services
    repositories/            run/profile/experiment artifact access
    read_models/             runs/tasks/coverage/traces
    catalog.py               可重建增量索引
```

### 7.3 Typed RunPlan

GUI 与 CLI 最终都必须调用同一个 planner，得到不可变的 typed plan：

```python
@dataclass(frozen=True)
class RunPlan:
    run_id: RunId
    task_refs: tuple[TaskRef, ...]
    executor: ExecutorPlan
    judge: JudgePlan
    repeat: int
    seed: int
    artifact_version: str

@dataclass(frozen=True)
class RuntimeInvocation:
    argv: tuple[str, ...]
    env: Mapping[str, str]
    cwd: Path
    mounts: tuple[Mount, ...]
    backend: Literal["local", "docker"]
    parser: ParserId
```

Planner 负责业务合法性，adapter 负责 runtime 差异，supervisor 负责执行。GUI dry-run
展示的 plan 与 runner 实际消费的 plan 必须是同一对象的序列化结果。

### 7.4 安全路径 API

所有路径操作必须只能通过少数 helper：

```python
def parse_safe_id(raw: str, *, kind: str) -> SafeId: ...
def parse_relative_path(raw: str) -> SafeRelativePath: ...
def resolve_within(root: Path, relative: SafeRelativePath) -> Path: ...
def assert_no_symlinks(root: Path) -> None: ...
def atomic_directory(target: Path) -> ContextManager[Path]: ...
```

禁止业务代码直接写 `root / user_value`。Code review 和静态搜索应把这类表达列为检查项。

### 7.5 Judge 可信转换管线

```text
raw JSON bytes
  -> JSON parse
  -> judge response JSON Schema
  -> rubric ID existence/uniqueness check
  -> JudgeAnswer(rubric_id, answer: bool, evidence)
  -> join authoritative RubricDefinition
  -> derive passed
  -> derive TaskRunOutcome
  -> validate artifact schema
  -> atomic write
```

任何一步失败都产生结构化 `inconclusive_judge` artifact，保留原始输出路径和错误摘要，
但不能产生可计分的 `agent_fail` 或 `agent_pass`。

### 7.6 运行生命周期

建议状态机：

```text
planned -> preparing -> running -> judging -> completed
              |           |          |
              v           v          v
            failed      stopping    failed
                           |
                           v
                         stopped
```

`RunState` 至少记录：

- schema version、run ID、experiment ID；
- planner fingerprint；
- PID、process group、container ID；
- state、state reason、started/updated/ended timestamps；
- heartbeat；
- stop intent 与 cleanup 结果；
- artifact paths。

每次状态变更原子写入。GUI 重启后由 supervisor reconcile：检查 PID/PGID、容器状态和
终态 artifact，恢复 active handle 或标记明确的 `orphaned`，而不是用 120 秒 mtime
窗口猜测。

---

## 8. 分阶段实施计划

### Phase 0：固定基线与保护网

目标：不改变行为，先把已知问题变成会失败的测试。

任务：

- 为 D-001 至 D-009 添加最小回归测试；
- 建立 `tests/security/`、`tests/contracts/`、`tests/lifecycle/`；
- 保存 wheel-install smoke test；
- 固定当前 artifact fixture，避免 hardening 意外改变历史格式；
- 在 CI 中独立运行 fast unit、security probes、wheel smoke、frontend checks。

退出标准：每个 P0/P1 缺陷都有先红后绿的确定性测试，probe 不读取真实敏感文件。

### Phase 1：P0 协议与文件系统 hardening

目标：关闭评分、路径、symlink 和 packaging 漏洞。

任务：

- 引入 `SafeId`、`SafeRelativePath`、`resolve_within()`；
- task import 和 runner staging 使用同一套路径策略；
- 默认拒绝 task package symlink；
- task load 时校验所有 ID 唯一；
- 简化 Judge response schema，只保留 Judge 权威字段；
- 严格 boolean 校验并由 aggregate 派生 `passed`；
- 引入 `TaskRunOutcome`，invalid/missing Judge 输出为 inconclusive；
- Schema 移入 package resources；
- 通过 wheel 安装 smoke test。

退出标准：

- 所有 traversal/symlink probe 被拒绝且没有在 root 外创建或读取文件；
- `"false"`、`0`、`1`、`null` 等非 boolean answer 全部 fail closed；
- Judge 不能通过伪造 `expected/passed/fail_fast` 改写 verdict；
- wheel 与源码 checkout 的 contract 行为一致。

### Phase 2：Typed Plan 与配置彻底解耦

目标：GUI、CLI 和 runner 共享同一规划语义。

任务：

- 实现 `RunPlan/ExecutorPlan/JudgePlan/RuntimeInvocation`；
- GUI plan API 返回 versioned RunPlan；
- runner 接收 plan snapshot，CLI 参数只作为 plan 输入适配层；
- executor 与 Judge 使用完全独立的 runtime/provider/bin/gateway/auth 配置；
- custom runtime 元数据进入 adapter registry，删除 GUI raw JSON 旁路；
- 删除已失效的 process-wide conflict 规则，只保留真实共享资源冲突。

退出标准：

- GUI dry-run plan 与 runner 实际执行 plan fingerprint 相同；
- 前端不包含 runtime env key、CLI flag、gateway override 规则；
- executor 使用 OpenRouter、Judge 使用官方 OpenAI 等组合有明确等价测试；
- 新增 custom runtime 不需要修改 GUI 业务判断。

### Phase 3：Supervisor、事务启动与重启恢复

目标：Launch/Stop/Restart 具备生产级生命周期语义。

任务：

- 引入 `RunSupervisor` 和统一 `ExecutionHandle`；
- 本地进程使用 process group，Docker 使用 container ID；
- `run_state.json` 原子持久化；
- experiment launch 使用 prepare/commit/rollback；
- GUI 启动时 reconcile；
- stop/cleanup 幂等，保留每个 handle 的结果；
- SIGINT/SIGTERM 和 GUI 退出路径执行一致清理。

退出标准：

- stop 后无 runner、executor、Judge 或容器残留；
- 第 N 个 contender 启动失败时，前 N-1 个全部回滚或被完整记录；
- GUI 重启后可继续显示、停止仍在运行的任务；
- 状态不再依赖固定 mtime 阈值。

### Phase 4：Read Model 与 GUI backend 拆分

目标：保持文件系统为真相源，同时让查询性能和模块职责可控。

任务：

- 拆分 `data.py` 为 runs/tasks/coverage/traces read models；
- 拆分 `experiments.py` 为 profiles/planning/records/coverage 服务；
- 建立可删除重建的 `RunCatalog`；
- JSONL 支持偏移分页和增量索引；
- HTTP route 只做 parse/auth/error mapping；
- 为 catalog 重建、损坏降级和并发读取添加测试。

退出标准：

- 页面查询不再每次全量读取全部 JSONL；
- catalog 删除后可从 artifacts 完整重建；
- 新增一个 coverage 字段只改一个 read model 和一个 contract；
- backend 核心业务模块原则上控制在 400-600 行内。

### Phase 5：Frontend 拆分与生成式 API 契约

目标：前端回到视图和交互职责。

任务：

- `NewRun.tsx` 按 Mode/Tasks/Agents/SharedConfig/Review 拆组件；
- 使用 `useRunDraft`、`usePlanPreview`、`usePreflight` 等领域 hook；
- Python API contracts 生成全部 TS DTO；
- Coverage 直接消费 `TaskRunOutcome` 和 HSW cell semantics；
- 统一 Agent 视角与 Task 视角 verdict 组件；
- 对向导阻断、错误恢复和 responsive layout 做浏览器回归。

退出标准：

- 页面组件不重新实现后端业务规则；
- `NewRun.tsx` 只负责编排，步骤组件可独立测试；
- 手写 API interface 降至仅本地 view model；
- HSW breach、defended、inconclusive、untested 有明确且无歧义的视觉语义。

---

## 9. 测试策略与验收矩阵

| 类别 | 必测场景 | 期望 |
|---|---|---|
| Judge 类型 | `false`、`"false"`、`0`、`null` | 只有 JSON `false` 合法，其余 inconclusive |
| Judge 权威 | Judge 伪造 expected/passed | 被 schema 拒绝或字段被忽略，聚合由 task 定义 |
| HSW 状态 | executor/Judge 故障 | 不进入 pass@n 分母 |
| HSW breach | 5 次中 1 次真实 pass | cell 显示 1/5 breach，可钻取证据 |
| Path traversal | materials/run/rubric ID 含 `..` | 创建任何目录前拒绝 |
| Symlink | file/dir/zip symlink | 默认拒绝，不读取目标 |
| Duplicate ID | rubric/rigor/step 重复 | task load fail closed |
| Stop | 父进程派生多级子进程 | TERM/KILL 后全部退出 |
| Docker stop | runner 中断 | 关联容器被停止并记录结果 |
| Launch rollback | 第 N 个 plan 启动失败 | 已启动 plan 回滚，无孤儿进程 |
| Restart | GUI 在运行中重启 | reconcile 后状态和控制能力恢复 |
| Packaging | 安装 wheel 后读 schema | 与源码运行一致 |
| Compatibility | GUI plan vs runner plan | fingerprint 和关键字段一致 |
| Catalog | 索引删除/损坏 | 可重建且 artifacts 不受影响 |

测试分层：

1. 纯领域单元测试：ID、path、verdict、aggregate、state transition；
2. Fake CLI integration：process group、parser、Judge schema、rollback；
3. Filesystem security probes：只使用临时目录和虚构 secret；
4. Wheel smoke：空环境安装并运行最小 task contract；
5. Browser tests：关键向导、错误态、HSW Coverage；
6. 真实 CLI smoke：人工执行，不进入默认 CI，不使用个人 Claude Code 登录态作为 executor。

---

## 10. 分支、提交与迁移策略

### 10.1 当前诊断分支

- 当前分支：`gui-impeccable`
- 诊断基线：`d055438`
- 本文档提交只记录诊断与计划，不包含任何运行时代码修复。
- 当前本地已有一个尚未推送的 GUI commit；后续 push 时应同时明确推送该提交与本文档。

### 10.2 推荐实施分支

从包含本文档的最新 `gui-impeccable` 创建阶段分支：

```text
codex/hardening-contracts-paths
codex/typed-run-plan
codex/run-supervisor
codex/read-models
codex/frontend-decomposition
```

每个分支只做一个阶段，避免把安全修复、架构搬移和 UI 改版混进同一提交。Phase 1
优先合并；后续阶段均在最新 hardening 基线上创建。

### 10.3 Artifact 兼容策略

- 旧 artifact 保持只读兼容；
- 新增 `TaskRunOutcome` 时提升 artifact schema minor/major version；
- reader 支持旧 `overall_pass`，但必须标记 `legacy_verdict=true`，不能伪装成新状态；
- writer 只写最新版本；
- 不原地重写历史 run，必要时提供显式 migration/report 工具。

### 10.4 回滚策略

- 每个阶段保持 CLI 入口和 artifact 根目录不变；
- typed plan 初期可双写：旧 argv snapshot + 新 RunPlan snapshot；
- RunCatalog 永远可删除，不影响事实 artifacts；
- supervisor 先接管新启动 run，不尝试无证据接管历史 PID；
- Judge schema 切换前保留 raw response，便于诊断兼容问题，但 raw response 不参与计分。

---

## 11. 非目标

本轮优化不包含：

- 把文件系统事实源替换成数据库；
- 重写所有 runtime adapter；
- 引入 Kubernetes、远端队列或多租户调度；
- 为追求“纯架构”而改变 CLI 的用户入口；
- 自动修复或静默兼容非法 task package；
- 把运行故障当作 Agent 能力失败；
- 使用个人订阅登录态承担 benchmark executor 流量。

这些能力未来可能有价值，但不是关闭当前可信度缺口的必要条件。

---

## 12. 完成定义

当以下条件全部满足，才可认为本轮架构优化完成：

1. 不可信 task package 无法读取或写入授权根目录之外。
2. Judge 非法输出永远不会产生可计分 pass/fail。
3. HSW Coverage 明确区分 breach、defended、inconclusive 和 untested。
4. `expected/fail_fast/passed/overall_pass` 的权威来源唯一且有测试固定。
5. Stop 能终止完整本地进程树和 Docker 容器。
6. GUI 重启后能 reconcile 运行状态并恢复控制。
7. 多 contender launch 要么完整提交，要么完整回滚并留下记录。
8. wheel 安装环境与源码 checkout 使用同一份 Schema。
9. GUI 与 runner 消费同一个 versioned RunPlan。
10. 文件系统仍是唯一事实源，查询索引可删除重建。
11. 新增 runtime/provider 不需要在前端复制 env/CLI 规则。
12. 全量单测、security probes、wheel smoke、frontend checks 持续通过。

---

## 13. 下一步建议

下一开发节点直接执行 Phase 0 + Phase 1，不继续扩展功能面。建议先以 D-001 为第一条
垂直修复：

1. 写字符串布尔值和伪造 `passed` 的失败测试；
2. 定义最小 Judge response schema；
3. 引入严格 `JudgeAnswer`；
4. 由 task rubric 派生 `passed`；
5. 引入 `inconclusive_judge`；
6. 更新 Coverage 聚合只统计有效样本；
7. 再处理 SafeId、SafeRelativePath 和 symlink policy。

这样可以最快修复 HSW 最核心的风险：**测量系统不能把 Agent 的真实失败误报为任务被
突破，也不能把测量故障包装成 Humans Still Win 的证据。**

---

## 14. 实施进度（2026-07-10）

原始诊断基线和章节编号保持不变；本节记录后续实施结果。可信度修复落在
`codex/hardening-contracts-paths`，Phase 4 读模型重构继续在 `codex/read-models`
实施，Phase 5 前端与 API 契约收敛在 `codex/frontend-decomposition` 实施。

### 14.1 已完成的正确性闭环

- `4f1f74a`：关闭 D-001，Judge 只提交 answer/evidence，权威 rubric 字段由 task
  定义回填；非法 Judge 输出进入 inconclusive，不再参与 HSW pass/fail。
- `44ea3d4`：关闭 D-002、D-003、D-004、D-006、D-007、D-010 的主要风险；统一
  Safe ID/relative path/symlink 策略，Schema 随 wheel 安装，重复引用 fail closed，
  executor 故障与能力 verdict 分离。
- 当前工作提交：关闭 D-005、D-008、D-009 和 D-011 的运行正确性风险；新增
  `run_state.json`、process-group TERM/KILL、Docker label + stop/kill、prepare/commit/
  rollback、重启 reconcile，以及 executor/evaluator 独立 bin、OpenCode gateway、
  credential env 和 custom runtime 元数据来源。

配套回归覆盖真实父子进程树、GUI 重启后恢复控制、第 N 个启动失败回滚、Docker
清理顺序、显式 stop 终态优先、角色级 Provider/key/bin 预检，以及 wheel 空环境
Schema smoke。

### 14.2 本轮停止边界

本轮以 D-001 至 D-011 的严重正确性与安全问题闭环为停止边界。Phase 2 中完整
`Typed RunPlan` 对象化、plan fingerprint 和 application-service 分层仍是后续结构化
迁移；当前先用角色级 typed fields 消除了真实路由串扰和错误 preflight，不宣称已完成
整个目标架构搬迁。

D-012（RunCatalog/查询性能）和 D-013（前端大模块拆分）没有被当作 bug 修复混入本
分支，继续保留在 Phase 4/5 路线中。它们影响扩展性和维护成本，但不阻塞本轮可信度
修复的完成判定。

### 14.3 Phase 4：Read Model 与 GUI backend（已完成）

- `data.py` 已成为兼容 facade；runs、tasks、coverage、artifacts、trace、live 和 task
  facts 分别落入独立 read model，核心模块均控制在 500 行以内。
- `experiments.py` 已成为兼容 facade；profile persistence、planning inputs、profile
  snapshot、planning 和 experiment records 分别落入应用服务。
- 新增可删除重建的 `RunCatalog`：artifact signature 只失效对应 run，写入使用
  fsync + atomic replace；catalog 缺失、损坏或位于只读挂载时均从 artifacts 正确
  降级重建。
- JSONL 查询使用持久化 byte-offset index；events 只解码目标页，trace 保留物理非空
  行号，文件 append 时仅增量扫描，截断、替换或损坏 index 时自动重建。
- HTTP handler 已收敛为 URL/body 解析、状态码和异常映射；预检、目录注册、读查询、
  launch transaction 与 rollback 进入可直接测试的 `ConsoleApplication`。
- 回归覆盖 catalog 删除/损坏/并发构建/单 run 失效/只读降级，以及 JSONL malformed
  row、append、截断语义、损坏和只读降级；完整 Python suite 408 tests 通过。

Phase 4 的停止边界是查询性能和模块职责闭环，不引入数据库，也不改变文件系统作为
唯一事实源的地位。D-012 至此关闭；D-013 继续由 Phase 5 处理。

### 14.4 Phase 5：Frontend 与生成式 API 契约（已完成）

- `NewRun.tsx` 从 3882 行收敛为 518 行编排层；Mode、Tasks、Agents、SharedConfig、
  Review 分别进入步骤组件，draft、plan preview 和 preflight 分别由
  `useRunDraft`、`usePlanPreview`、`usePreflight` 管理。draft 发生变化时旧 plan 立即
  失效，Launch 不可能消费过期预览。
- Python `contracts.py` 成为 HTTP wire DTO 的唯一来源；生成器当前输出 131 个
  TypeScript 类型，`api.ts` 只保留请求客户端和导出，测试禁止重新引入手写 wire
  interface。Profile、experiment planning、preflight、runs、tasks、coverage 和
  provider/agent payload 均走同一生成链路。
- planning service 明确返回 `profile_modified` 与 `profile_modified_fields`，前端不再
  推导 profile contract 偏差；dry-run 使用只读 preview path，不创建临时 snapshot，
  只有真实 launch 才物化冻结配置。
- Coverage read model 为完整 task × agent 矩阵生成 cell，并直接给出 `breached`、
  `defended`、`inconclusive`、`untested` 四态；前端只负责呈现，不再根据 pass/fail
  字段二次推断 HSW 结论。Agent/Task 视角共用 verdict primitive。
- 页面按 route lazy load；production build 已消除原有大 chunk 警告。NewRun route
  约 85 kB，Coverage 约 10 kB，基础入口约 353 kB，Recharts 只随图表 route 加载。
- 浏览器回归覆盖：未选 task 时 Next 禁用并提示；整行可选择 task；无效实验名会清空
  plan 并禁用 Launch，修复后 plan 与 Launch 自动恢复；Coverage 四态完整显示；
  390 × 844 移动端和 1280 px 桌面端均无页面级横向溢出，浏览器 error log 为空。
- 最终验证：411 项 Python tests 通过，generated contracts freshness 通过，frontend
  lint 无 error（保留 11 条既有 Fast Refresh warning），production build 通过。

Phase 5 的停止边界是关闭 D-013、消除前端对后端业务规则的重复解释，并建立可持续的
wire contract 生成链路。本阶段不引入数据库、远程调度、多租户或 Kubernetes，也不
改变文件系统 artifact 的事实源地位。至此本文 Phase 4/5 目标均已达到退出标准。
