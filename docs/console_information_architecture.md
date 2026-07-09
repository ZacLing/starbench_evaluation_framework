# 控制台信息架构：Task 中心模型与测量契约

> 2026-07-09 起草，同日经第一性原理讨论重写。此文档是后续 console 页面
> 重构（impeccable 执行）的设计输入。呈现红线以 docs/PRODUCT.md 为准
> （file system is the truth、诚实降级、不发明磁盘上不存在的状态）。

## 0. 目的（第一性）

本框架为 **HSW Benchmark**（Humans Still Win）服务。产品是任务集本身，
核心主张是"这些任务 AI 做不出来"。主张的证据结构：

> 任务 T 有效 = 人类参考能通过 T **且** 名册内所有 AI 配置都通不过 T

由此推出：测量对象是**每个 Task 在配置空间上的通过率地形**；
核心观测是**覆盖**（哪些格子填了、哪些空着、哪些陈旧了）。

## 1. 概念栈

```
Task            测试用例（材料最小单元：prompt + rubric + 资源）
Task Run        观测（原子事实：某配置 × 某任务 × 某次执行 → verdict）
Run             作业（一次 starbench-run：一个配置列 × 若干任务行 = 填一批格子）
Test Profile    测量契约（见 §2：roster + instrument + repeats + task_set）
Coverage Matrix 覆盖矩阵（一个 profile 的执行状态，派生视图非存储实体）
```

- Run 是文件系统的组织单元（runs/ 一级目录），是**操作**单元，不是分析单元。
- **Experiment 已降级**：`experiments/<id>.json` 保留为批量启动的历史记录；
  比较 = 矩阵按列读，可比性由 profile 契约保证，不再需要预声明分组。
  UI 不围绕 experiment 组织。
- 单次执行是抽样不是分数：agent 有随机性，格子的值是 n 次重复的聚合
  （HSW 判据形如 0/5）。

### HSW 语义翻转（波及全站视觉语义）

对任务而言 **AI pass 是坏消息**：任务失守，需要 re-boost 或退役。
系统最重要的告警是"task X 被配置 Y 攻破（1/5）"。
"名册全线 fail + 人类参考 pass"才是任务的绿色（有效）状态。
现有 pass=绿/fail=红 是 agent 中心语义，矩阵视图必须按任务中心语义重设计；
run/task run 详情页保留 agent 中心语义（那里回答的是"agent 干得怎样"）。

## 2. Test Profile：测量契约（单一真相源）

> 参考实现：`starbench-platform-step-validation-config`（VLM 平台）的
> eval profile 体系。2026-07-09 已实读其代码（models/eval_config.py、
> eval_task.py、repository/eval_configs.py）与配置中心 UI，下述模式
> 均经代码与实物核实，非仅 README 转述。

### 三层组件模型（配置组件化与复用的骨架）

```
资源层   定义一次，处处引用。Provider（端点+密钥+超时重试）、Model、
         Runtime（agent CLI）。shrimp 的 Providers 页 / Agents 页已是此层。
策略层   Test Profile：从资源层【选择引用】组成契约，不内联资源定义。
         可多个并存、一个默认、可停用；"设为默认只影响新 run"。
装配层   run 启动时解析 profile → 快照进 run_config（snapshot-on-use）。
```

```jsonc
// <runs-dir>/profiles.json 的升级形态（现有 launcher profile 是其雏形）
{
  "id": "hsw-frontier-2026Q3",
  "roster": [                       // 矩阵的列。"值得测什么"是判断，显式声明
    {"runtime": "claude", "model": "claude-opus-4-8", "added": "2026-07-01"},
    {"runtime": "codex",  "model": "gpt-5.5",         "added": "2026-07-01"}
  ],
  "instrument": {                   // 测量仪器：变更 = 换尺子 = 新版本层
    "evaluator_agent": "codex",
    "evaluator_model": "gpt-5.5",
    "judge_mode": "single"
  },
  "repeats": {"n": 5, "aggregation": "pass@n"},   // HSW 默认 n=5，可配置
  "execution": {                    // 执行策略也属于契约（影响可复现与限速）
    "batch_size": 1,
    "max_evaluator_parallel": 4,
    "thinking_effort": "none",
    "timeout_seconds": 1800
  },
  "task_set": {"tasks_dir": "tasks", "task_ids": ["..."]}
}
```

设计决定（2026-07-09 讨论钉死）：

1. **roster 显式声明 + 自动归纳浮现**：名册人填（真相源）；console 从
   runs 里扫出名册外配置，浮现为"待归册"候选，一键提升。名册不限制
   跑什么——它只是覆盖率的分母；名册外的 run 标记为探索，不静默丢失。
2. **repeats 参数化**：n 是 profile 字段不是硬编码；"这格测完了"的判据
   由 profile 定义。
3. **Snapshot-on-use（双轨引用）**：run 记录 profile id（指向"现在的
   契约"）**加**完整快照（锁定"当时的语境"）；事后改 profile 不改写
   历史 run。快照必须**层级自包含**（profile→models→providers 的端点/
   超时/重试全部内联，不留悬空引用）且**密钥脱敏**（只存
   `api_key_configured: true/false`，真 key 仅运行时使用）。
   ——以上三点为参考实现的代码级纪律，直接继承。
4. **仪器变更 = 版本层**：rubric 或 judge 变更后，旧格子不作废但归属旧
   仪器版本层；跨层不可比，矩阵默认展示当前层。
5. **执行策略入契约**：并发/限速/超时/thinking effort 等影响测量条件的
   参数属于 profile（参考实现连 temperature、调用间隔都在契约内）。

### 配置总览（预检视图，参考实现的第三个可平移模式）

一页回答"现在按默认契约启动一个 run，会发生什么、哪里会断"：

- **测量链路图**：task_set → executor roster（逐配置解析：runtime 探针
  状态 × provider 密钥状态）→ instrument（judge 可用性）→ 输出；
- 每节点显示解析结果 + 阻断红叉（runtime 未装 / key 未配 / docker 镜像
  缺失——探测能力 Agents/Providers 页已有，此页只做集中呈现）；
- 每节点一句**人话的"生产影响"**（如"每格 5 次重复，预计 25 个任务执行"）。

## 3. 可复现性：judge 身份记录现状与缺口

已核实（2026-07-09）：

| 层 | 记录 | 状态 |
| --- | --- | --- |
| run 级 | run_config.json：evaluator_agent/model/judge_mode | ✅ |
| run 级 | runtime_provenance（R0）：evaluator CLI 版本/路径/docker digest | ✅（R0 之后的真实 run） |
| 判定文件级 | judge_aggregate：**无 judge 身份字段** | ❌ 缺口 |

**待办**：`judge_aggregate.schema.json` v1 增加可选字段
`judge_agent / judge_model / judged_at`，判定文件自包含仪器身份。
单 run 单 judge 时靠目录上下文可推断，但重判与跨 run 聚合（矩阵）
需要判定文件自述。

## 4. 页面结构（按修正后的模型）

### 导航结构（2026-07-09 定，同日修正）

标签用操作者的词，不用架构词（首版"Benchmark/Results"组名被否：
对操作者而言整个工具都是 benchmark，无区分度）。唯一真实边界是
"日常工作页 vs 配置页"，所以只设一个组标签：

```
Dashboard         状态 + 攻破告警 + 覆盖率概要
Coverage          任务覆盖矩阵（新·主视图）
Task library
Runs              执行台账
──────────
Setup
  Profiles        新·测量契约
  Agents
  AI providers
  Skills
```

- "New experiment" 移出侧边栏，只保留右上角主按钮（动作不是地点，
  现状两处并存是重复）；
- Coverage 紧随 Dashboard：HSW 第一问题"防线还完整吗"的答案页；
- Setup 组内排序表达层级：Profiles（策略层）引用其下三项（资源层）；
- 新位置随对应页面落地补入，不做死链接占位。

| 视图 | 定位 | 内容 |
| --- | --- | --- |
| **覆盖矩阵**（新，主视图） | profile 的执行状态 | 行=任务，列=roster 配置；格子=聚合通过率 + 新鲜度；空格醒目；被攻破告警置顶；"待归册"配置浮现 |
| Runs 页 | 执行台账 | 平铺 + 过滤（按配置/任务集/状态/日期）；Experiments 卡片区退役；列名修正（"Executors"状态计数 vs "Executor"runtime 身份同名不同义） |
| Task 详情 | 任务档案 | 任务内容 + 配置覆盖行（本任务在各列战绩、最后测试时间、攻破告警）+ 既有 R2 下钻 |
| Run / Task Run 详情 | 观测证据 | 维持 R2 三 Tab（轨迹/交付物/判定），agent 中心语义 |
| Profile 管理 | 测量契约编辑 | roster 编辑 + 待归册提升 + repeats/instrument 配置 + 版本历史 |

## 5. Config 卡：从"环境变量 dump"到"测量配方卡"

现状：~28 个 SCREAMING_CASE key 四列字母序平铺。重构：

1. 顶部一句话配方（可复制）：
   `opencode(doubao-seed-2-0-pro) × 5 tasks × judge codex(gpt-5.5) · seed 123 · local`
2. 语义分组四栏：被测方（executor）/ 评审方（instrument）/
   实验变量（instruction/rigor/skills）/ 复现信息（seed、provenance、
   profile snapshot 引用）
3. 非默认值高亮（与 CLI 默认 diff），空值折叠
4. Raw 视图保留为降级入口

## 6. 执行器报告：确认是缺口

executor 视角的 run 级汇总不存在于 GUI，数据全在磁盘
（executor_seconds、events usage tokens、trace_summary 工具统计、超时归因）。
纳入 R3 报告导出同一装配逻辑：data.py 先做聚合，run 详情加
"Executor report" 区，报告导出复用。

## 7. 内置 Agent 助手：单独立项，先攒需求

价值真实但与"console 是只读仪表"有张力。若做，边界先立：只读解读先行
（"这任务为什么 fail"）→ 起草任务包次之（草稿进 tasks/ 待人审）→
红线：永不代表用户启动 run、永不写 runs/。架构上倾向 CLI-first
（`starbench assist`），console 只做入口。不进 R 计划；
运营真实提问清单攒满十条再立项。

## 8. 推进顺序

1. **契约补洞**（小）：judge_aggregate 增加 judge 身份字段（§3）；
2. **Profile 升级**（中）：profiles.json 扩展 roster/instrument/repeats
   + snapshot-on-use（§2）——矩阵的前提；
3. **覆盖矩阵视图**（大）：§4 主视图，impeccable 执行；
4. R3 报告导出（已规划，含 §6 执行器报告装配）；
5. Runs 页台账化 + Config 配方卡（§4/§5），impeccable 执行；
6. Agent 助手：攒需求，不排期。
