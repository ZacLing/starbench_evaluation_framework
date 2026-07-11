> **[已归档 2026-07-13]** 契约策略已落地，现行参考见 ../artifact_contracts.md。结构与边界的现行权威见 `docs/ARCHITECTURE.md`。本文只读，不再更新。

# 制品契约策略：从评测脚本到 Coding-Agent Evaluation Infrastructure

> 2026-07-06 讨论稿。本文沉淀当前对 StarBench 产品定位与
> artifact contract 的理解，不是正式协议。正式协议应在 schema、测试与版本策略
> 明确后落到 `docs/artifact_contracts.md`。

## 1. 背景判断

StarBench 不应只被理解为“一个测试框架 + 一个 GUI”。更准确的定位是：

**StarBench 是面向 coding agent 的 evaluation infrastructure。**

这个定位下，GUI 只是本地驾驶舱；真正的核心产品边界是：

- 如何用统一 task package 描述一个可复现评测任务；
- 如何用 runtime adapter 真实驱动不同 coding-agent CLI；
- 如何隔离 executor / judge 的工作区、凭证和环境；
- 如何产出平台、CI、GUI、分析脚本都能稳定消费的 run artifacts；
- 如何让专家 task packs、rubrics、human references、rigors、skills 成为可复用的高价值内容资产。

因此，artifact contracts 不是“补一篇格式说明”，而是 StarBench 从内部工具走向基础设施产品的地基。

## 2. 为什么参考 CUA

这里参考的是 [`trycua/cua`](https://github.com/trycua/cua) 的产品形态，而不是照搬它的具体技术栈。

CUA 的价值不在于某个单点 UI，而在于它把 computer-use agent 需要的底层能力拆成一组基础设施模块：驱动层、sandbox、benchmark、本地工具、VM/环境管理。它面向的是一个更大的问题：

> agent 如何稳定、可复现、可组合地使用电脑？

StarBench 面向的是相邻但不同的问题：

> coding agent 如何稳定、可复现、跨 runtime 地被评测？

这个类比有几个重要启发。

### 2.1 从“工具”转向“基础设施层”

如果只说 StarBench 是测试框架，用户会自然期待一个命令、一个 GUI、一些 demo tasks。这个叙事太窄。

参考 CUA 后，StarBench 的叙事应变成：

- 它不是某个 benchmark 的脚手架；
- 它是 coding-agent eval 的运行时与互操作层；
- task package 和 run artifact 是生态边界；
- runtime adapters 是护城河；
- GUI 是本地调试与实验驾驶舱，而不是平台本身。

这会直接影响工程优先级。页面打磨重要，但 contract、adapter registry、isolation、artifact stability 更基础。

### 2.2 StarBench 与 CUA 的模块映射

可以把 CUA 的模块化思路映射到 StarBench：

| CUA 形态 | StarBench 对应层 | 作用 |
| --- | --- | --- |
| Drivers | Runtime adapters | 统一驱动 Codex、Claude Code、Gemini CLI、Grok Build、OpenCode、自定义 CLI |
| Sandbox / VM | Workspace isolation + Docker/local backend | 给 executor 一个可控运行环境 |
| Cua-Bench | Task package + rubrics + judge | 评测 agent 是否完成任务 |
| Local tooling | `starbench-gui` | 本地配置实验、查看 run、debug task |
| Infrastructure brand | Artifact contracts + CLI API | 让外部平台、CI、第三方任务集敢接入 |

这个映射说明：StarBench 的独立价值不是“有一个 GUI 可以点按钮跑任务”，而是“有一套可复用的 coding-agent 评测基础设施”。

### 2.3 CUA 类比也划清了 GUI 的边界

CUA 的基础设施定位并不要求它把所有东西做成一个 SaaS。类似地，StarBench GUI 不应该演化成半吊子多用户平台。

当前交接文档里的定位是合理的：

- `starbench-run` 是无状态引擎；
- StarBench 平台可以直接消费 CLI 和 artifacts；
- `starbench-gui` 是单研究员本地驾驶舱；
- 多用户、权限、数据库、共享凭证不是这个 GUI 的职责。

参考 CUA 后，这个边界更清楚：GUI 是 infra 的一个操作面，不是 infra 的全部。

### 2.4 CUA 类比强化了 artifact contract 的优先级

基础设施产品最重要的不是“当前实现能跑”，而是“外部系统敢依赖”。

CUA 如果要被 agent 框架依赖，就需要稳定驱动接口、环境语义和 benchmark 输入输出。StarBench 如果要被平台、CI、第三方任务作者依赖，就需要稳定的 artifact contracts：

- task package 格式；
- rubrics 格式；
- human reference 的公开/私有边界；
- run 目录结构；
- summary / task summary / manifest / progress events 的稳定字段；
- 版本演进与兼容策略。

所以 `artifact_contracts.md` 不是普通文档，而是 StarBench 作为基础设施层的公开接口说明。

### 2.5 类比的边界

这个参考也不能过度延伸。

CUA 解决的是“agent 控制电脑”的通用环境问题；StarBench 解决的是“coding agent 被公平评测”的任务、执行、裁判与证据问题。StarBench 不需要追求 CUA 那样的 VM 管理广度，也不应该为了基础设施叙事牺牲评测可信度。

StarBench 的差异化应集中在：

- 多 coding CLI runtime adapters；
- 真实执行而非 mock UI；
- 无单元测试任务的 rubric judge；
- executor / judge 隔离；
- 专家数据钩子：human reference、instruction ablation、rigor injection、executor skills；
- 可被平台与 CI 消费的 artifact contract。

## 3. 什么是 artifact contract

Artifact contract 是 StarBench 与外部消费者交换数据的稳定协议。

输入制品包括：

- `task.json`
- `prompt.md`
- `rubrics.json`
- `human_reference.json`
- `rigors.json`
- optional materials
- optional executor-skill references

输出制品包括：

- `runs/<run_id>/summary.json`
- `runs/<run_id>/progress_events.jsonl`
- `runs/<run_id>/<task_run_id>/manifest.json`
- `runs/<run_id>/<task_run_id>/task_summary.json`
- `runs/<run_id>/<task_run_id>/logs/status.json`
- `runs/<run_id>/<task_run_id>/logs/trace_summary.json`
- `runs/<run_id>/<task_run_id>/logs/artifact_manifest.json`
- judge result / aggregate files
- `workspace/outputs/` deliverables

contract 需要回答：

- 哪些文件是公开契约，哪些只是调试制品；
- 哪些字段稳定，哪些字段 optional，哪些字段 internal；
- 缺失字段如何处理；
- unknown fields 如何处理；
- schema version 如何演进；
- private expert data 和 credential data 的红线在哪里。

## 4. 只有文档不够

Markdown 文档可以声明协议，但不能保证协议。真正的 artifact contract 至少需要四层。

### 4.1 人读语义层

`docs/artifact_contracts.md` 解释每类制品的含义、稳定性、隐私边界和兼容策略。它服务于维护者、平台接入者、任务作者和未来的 agent。

### 4.2 机器可读 schema 层

JSON Schema 定义结构，服务于校验器、CLI、GUI import、CI、平台集成和 contract tests。schema 不应只是文档附录，而应该是可执行协议的一部分。

### 4.3 contract tests 层

测试证明实现没有破坏协议。它应该验证：

- bundled examples 符合 task schemas；
- fake-CLI closed-loop 输出符合 run artifact schemas；
- GUI reader 不依赖未声明字段；
- private `human_reference.reasoning` 不进入任何公开 API 或公开 artifact；
- legacy artifact 的读取行为明确。

### 4.4 版本与兼容层

稳定制品需要 `schema_version` 或等价机制。项目需要明确：

- 新增 optional field 是否兼容；
- 删除/重命名 stable field 是否 breaking；
- 字段含义变化如何处理；
- unknown future version 如何报错或降级；
- deprecation 周期如何执行。

一句话：

**docs 定义语义，schema 定义形状，tests 定义承诺，versioning 定义演进。**

## 5. 当前仓库现状

当前仓库已经有一些 contract seeds，但还没有完整 artifact contract。

已有机器可读 schema：

- `src/starbench/runner/schemas/single_result.schema.json`
- `src/starbench/runner/schemas/rubric_result.schema.json`

这两个 schema 约束 evaluator 输出，不约束 task package 输入，也不约束 run artifacts 输出。

当前可推断来源：

- `src/starbench/runner/task_loader.py` 隐含 task package 的加载规则；
- `src/starbench/runner/models.py` 隐含 `Rubric`、`HumanReferenceStep`、`Rigor`、`ExecutorSkill`、`TaskSpec`、`TaskRunSpec`、`ProcessResult` 等结构；
- `src/starbench/gui/library.py` 有 GUI 导入校验；
- `src/starbench/runner/orchestrator.py`、`executor.py`、`judge.py`、`trace.py`、`evaluation.py` 写出 run artifacts；
- `docs/task_package.md`、`docs/runner_reference.md` 等文档描述了部分格式。

重要判断：

**可以从现有代码推断第一版 schema，但不能把当前实现行为直接等同于协议。**

原因是：

- 实现可能包含历史包袱；
- GUI 需要不等于平台契约；
- runner 当前 dump 出来的字段不一定都该稳定；
- truthiness coercion、绝对路径、debug 字段、fallback 语义等都需要人工判断；
- 输出 artifact 目前缺少版本字段和 contract tests。

## 6. 解耦原则

协议层、实现层、测试层需要解耦。

- 协议不应该等于“GUI 当前要读什么”。
- 协议不应该等于“runner 当前刚好写什么”。
- 实现应该逐步向协议校验靠拢，而不是无意中定义协议。
- 测试应该守住兼容承诺，而不只是跑通 happy path。
- 文档应该区分 stable / optional / internal / diagnostic / private。
- `docs/artifact_contracts.md` 不应从代码盲生成，而应由代码事实启发，再被产品策略裁剪。

## 7. 建议的 schema 家族

Task package schemas：

- `task.schema.json`
- `rubrics.schema.json`
- `human_reference.schema.json`
- `rigors.schema.json`
- `executor_skills.schema.json`

Run artifact schemas：

- `run_summary.schema.json`
- `task_manifest.schema.json`
- `task_summary.schema.json`
- `executor_status.schema.json`
- `trace_summary.schema.json`
- `artifact_manifest.schema.json`
- `progress_event.schema.json`
- `judge_aggregate.schema.json`

schema 放置位置还需要决策：

- `src/starbench/contracts/schemas/`：便于随 Python package 分发；
- `schemas/`：更像语言无关的根级公开协议；
- `src/starbench/runner/schemas/`：继续放 runtime-private evaluator response schema，但不宜混淆为 artifact contract schema。

关键不是路径，而是语义边界：evaluator response schema 与 artifact contract schema 不是同一种东西。

## 8. 版本策略方向

对外消费者会依赖的稳定制品应带版本。

候选形式：

```json
{
  "schema_version": 1
}
```

初步兼容规则：

- 新增 optional field 兼容；
- 删除或重命名 stable field breaking；
- 字段含义变化即使 JSON 类型不变也是 breaking；
- reader 通常应忽略 unknown fields，除非某个窄 schema 明确 `additionalProperties: false`；
- unknown future `schema_version` 应根据 reader 角色 warning 或 fail fast；
- 缺失 `schema_version` 的旧 artifacts 可视为 legacy v0。

还需要区分 public artifacts 与 diagnostic artifacts。`summary.json`、`task_summary.json`、`manifest.json` 很可能是 public contract；raw runtime events 可能更偏 diagnostic，版本策略可以更松。

## 9. 隐私与凭证红线

artifact contract 必须写入当前产品红线：

- `human_reference.json` 可以包含专家私有 `reasoning`；
- `reasoning` 绝不进入 GUI API response、executor prompt、public run artifact；
- API key 不属于 artifact contract；
- GUI / runner 可以传环境变量名，不能传 credential value；
- executor 与 judge 的凭证作用域必须隔离；
- 本地绝对路径默认不应成为稳定 public artifact 字段，除非明确标为 diagnostic。

这些不是 UI 偏好，而是产品可信度规则。

## 10. 建议落地路线

### Phase 1：盘点与草拟

- 从 bundled examples 和 fake-CLI closed-loop 输出生成字段清单；
- 阅读每类 artifact 的 writer / reader；
- 草拟非强制 schema；
- 写 `docs/artifact_contracts.md`，明确它是 curated contract，不是源码字段 dump。

### Phase 2：contract tests

- 新增 `tests/contracts/`；
- 校验示例 task packages；
- 运行小型 fake-CLI closed-loop 并校验 emitted artifacts；
- 增加 privacy tests，守住 `human_reference.reasoning` 不外泄；
- 增加 legacy/missing-version 行为测试。

### Phase 3：共享校验

- 引入 runner 与 GUI 共用的小型 validation module；
- 将 GUI import validation 迁移到共享校验；
- 保持用户可读、具体的错误提示；
- 避免一次性开启过严 schema 导致已有任务包无法使用。

### Phase 4：版本化输出

- 给稳定 public artifacts 增加 `schema_version`；
- 对 legacy artifacts 做兼容读取；
- 明确未知版本行为；
- 保留必要的 migration / warning 机制。

### Phase 5：公开协议打磨

- 发布正式 `docs/artifact_contracts.md`；
- 从 `docs/task_package.md`、`docs/runner_reference.md`、`docs/gui.md` 链接过去；
- 标注 public / private / diagnostic / deprecated；
- 将 artifact contract 纳入贡献与 review checklist。

## 11. 不要做什么

- 不要把当前实现怪癖固化为永久协议；
- 不要让 GUI 单独定义 artifact shape；
- 不要只为了两个 demo tasks 写 schema；
- 不要为了方便暴露专家私有 reasoning；
- 不要把 credential value 写进任何 artifact；
- 不要把本地绝对路径默认做成稳定字段；
- 不要在没有 legacy 策略的情况下突然强制严格 schema。

## 12. 待定问题

- 哪些 run artifacts 是 public contract，哪些只是 diagnostic？
- schema 应放在 `src/starbench/contracts/schemas/` 还是仓库根 `schemas/`？
- 哪些 artifacts 第一批必须加 `schema_version`？
- task package 是否也应声明 `schema_version`？
- 缺失 version 的任务包是否视为 v1，还是 legacy v0？
- JSON Schema 是否作为唯一机器可读契约，还是从 schema 生成 Python / TypeScript 类型？
- StarBench 平台正在消费哪些字段？这些字段的 deprecation policy 如何定义？

