# 结果体验规划：从"数据都在"到"故事可读"

> 2026-07-08 起草。动机：内部实际用法是 Agent 调 CLI 跑测试，对运营/测试同事是黑盒——
> 不知道进度、看不懂结果、要反复交互监控。维护者此前为 HSW 任务生产手写过一个
> trace viewer（`starbench-hsw-golden-tasks/_hsw_trace_viewer/`，零依赖 Node + 原生前端），
> 其体验品质证明了"轨迹回放"这条路的价值；本计划把同等品质带进评测框架本体。

## 0. HSW Trace Viewer 的三个可平移模式（经实物审阅）

该 viewer 面向的是**任务生产轨迹**（专家 boost 循环：冷启动→评审→boost→验收），
与本框架的**评测运行轨迹**是上下游关系。它证明有效的三个呈现模式，逐一映射：

| HSW viewer 模式 | 映射到评测框架 | 数据基础（已核实存在） |
| --- | --- | --- |
| ① 循环时间轴 + 因果溯源（评审弱点→驱动下轮） | 执行轨迹回放：工具调用/输出的时间轴 | `events.jsonl` 已被各 adapter 归一化为统一 compat 事件格式；`trace_summary.json` 已有工具统计 |
| ② 文档一等公民（渲染 Markdown、跨轮版本切换） | 交付物浏览器 + 消融变体/repeat 对比 | `outputs/` + `artifact_manifest.json`；instruction 变体天然构成"同任务多版本" |
| ③ 判定与证据互链 | rubric 判定 ↔ evidence 引用 ↔ 交付物跳转 | 判定结果每条 rubric 自带 `evidence` 文本（`judges/*_aggregate.json` 的 `results[]`） |
| 满意度收敛折线 / 弱点燃尽 | repeat 通过率收敛、ablation uplift 图 | `instruction_ablation_summary.json` 已有 uplift 数据 |

诚实原则同样平移：推算值标注"≈"、缺文件软失败显示"无内容"、不伪装。

## 1. 现状差距

Console 的 TaskRunDetail 目前是：原始事件分页 dump + final message + 数字统计 +
judge 表格 + 制品计数。数据完备但是**档案柜，不是回放**：
看不出 agent 干活的过程结构，交付物要下钻文件系统，rubric 挂了不知道 judge 看到了什么。
运营同事的"看不懂结果"，根源即此。

## 2. 分阶段计划

### R0 — 收 schema 分支（前提，≈半天）

`codex/artifact-contracts-strategy` 已完成 13 个 v1 schema + 轻量校验器 + 274 行测试
+ 稳定性分级文档（Public/Private/Diagnostic/Internal）。收尾动作：

1. 合并回 `gui-impeccable`，对账 16 个提交的漂移；
2. 补 `runtime_provenance.schema.json`（provenance 在分支分叉后才落地）；
3. 确认手写校验器对不支持的 JSON Schema 关键字**显式报错**而非静默放过；
4. 双测试套件全绿（分支 225 + 主线新增 19 都要活着）。

R1/R2 的一切装配读取都以这些 schema 为准——报告与回放建在契约上，不建在碰巧的字段上。

### R1 — 进度可见性集成 GUI（快赢，≈1 天，可与 R0 并行）

维护者已拍板：进度就在 GUI 里解决。现有基础：Runs 页 4s 轮询、`progress_events.jsonl`。

1. **Run 详情页 live 模式**：运行中的 run 显示任务泳道（每任务 executor/judge 状态：
   排队/执行中/已判定），轮询 progress 事件驱动；
2. **执行中任务的事件尾巴**：当前任务 tail 最近 N 条归一化事件（"agent 正在干什么"），
   这是黑盒感的直接解药；
3. **ETA**：基于已完成任务平均时长 × 剩余数，标注"估算"；
4. Dashboard 的 Running now 卡直达该 run 的 live 视图。

验收：运营同事打开 console 就能回答"跑到哪了、在干什么、大概还要多久"，
无需询问跑测的人。

### R2 — 执行轨迹回放（体验主升级，≈2-3 天）

TaskRunDetail 重构为三个 Tab（对应 viewer 的三视图语法）：

1. **轨迹**：时间轴卡片流（工具调用折叠卡：命令/参数摘要/输出摘录/耗时；
   思考段落；最终消息），锚点可分享；原始 JSONL 保留为"Raw"降级入口；
2. **交付物**：`outputs/` 文件树 + Markdown/代码渲染抽屉；消融 run 中同名交付物
   跨变体切换（baseline ↔ +instruction，viewer 的版本切换模式直接平移）；
3. **判定**：rubric 表升级——每行展开 judge 的 `evidence` 引用，fail-fast 红线
   视觉突出；evidence 提及的交付物可跳转到交付物 Tab。

run 级增加：repeat 通过率收敛小图、ablation uplift 图（数据现成）。

### R3 — 报告导出（交付物出口，≈1-2 天）

**自包含单文件 HTML**（内联样式、无外部请求、双击即开、可发钉钉）：

- 内容：摘要卡（配置/provenance/总分）→ 逐任务 rubric 判定 + evidence →
  失败任务 final 摘录 → 成本占位（usage 数字先行，货币化后续）；
- 三个出口共用一个生成器：`starbench-report <run_dir>` CLI、
  runner `--report` 旗标（run 结束自动生成，躺在 run 目录里）、GUI 导出按钮；
- **决策点**：生成器放 Python 端（手写模板，CLI/runner 出口不依赖 node）
  还是复用前端组件（品质高但报告出口被 node 绑架）。倾向前者，
  报告是文档不是应用，接受呈现比 console 朴素一档。

### R4 — 机会项（不排期，条件触发）

- 任务包若携带专家生产轨迹（`expert_boost_loop.v1` 的 trace/ 目录），
  任务详情加"任务出身"Tab——评测与生产的叙事闭环。触发条件：平台侧任务包
  开始随包交付 trace；
- peer-vote 共识分析器**留在生产侧**（平台/HSW 仓库），不进本框架——
  它诊断的是 rubric 生产质量，消费者是任务生产管线。

## 3. 顺序与理由

**R0 → R1 → R2 → R3。** R0 是契约地基；R1 最小成本直接止血最痛的"进度黑盒"；
R2 是体验主投资；R3 复用 R2 的装配逻辑与呈现语义（先回放后报告，
报告是回放的静态快照，反过来做会做两遍）。

## 4. 非目标

- 不做公开 leaderboard 站；不做多用户部署；不做轨迹编辑；
- 不把 HSW 生产 QC 工具整体搬进来（上游归平台，本框架只在 R4 条件成熟时读）；
- R2 不追求"每种 runtime 的私有事件全量美化"——归一化 compat 事件覆盖的部分
  做卡片，覆盖不到的落 Raw，诚实降级。

## 5. 执行状态

- [ ] R0 schema 分支合并
- [ ] R1 进度 live 模式
- [ ] R2 轨迹回放三 Tab
- [ ] R3 报告导出三出口
