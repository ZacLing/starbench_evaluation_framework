# 配置面呈现规划（Config Surface Plan）

> 目标：把测试框架的全部可配置能力以正确的产品形态呈现在控制台里——该进向导的
> 进向导、该做资源页的做资源页、该留在任务包里的在任务库呈现、被抽象吸收的
> 绝不请回来。本文是执行前的规划；每个批次独立交付，交付时全量测试保持绿色。

## 1. 背景：39 个 CLI 参数的对账结论

对 `runner/cli.py` 的全部参数做过一次逐个对账，分四类：

1. **已正确呈现**：任务/runtime/模型/评审（runtime+provider+model+timeout+mode）/
   执行环境/seed/batch/repeat/thinking-effort（藏得深，见 B1）。
2. **被抽象有意吸收，不再暴露**：`--auth-mode`×3（Provider 的凭证方式决定）、
   `--codex-bin` 与 `--opencode-*` 网关（注入通道自动计算）、`--docker-image`
   （按 runtime 解析）、`--run-id`/`--runs-dir`/`--no-progress`（系统管理）。
3. **有通道没 UI 的运行旋钮**：`--max-evaluator-parallel`、`--claude-max-turns`
   （launcher 尚未透传）、`extra_args` 逃生舱、`--claude-bin` 等 bin 覆盖
   （经 extra_args 覆盖即可，不单独做 UI）。
4. **整块缺失的研究功能**：指令消融（`--instruction-mode/--instruction-step`）、
   executor skills 注入（`--executor-skill/-group/-root`）、rigor 注入
   （`--rigor/--rigor-mode`）。
5. **任务级事实未呈现**：`allow_web_search`（任务包属性，执行时自动转成各
   runtime 的联网工具开关）在任务详情页不可见。

## 2. 设计原则

1. **抽象优先于旋钮**：凡已被 Provider/Runtime/注入通道吸收的参数，不再以原始
   形式出现在界面上；逃生舱统一走 Advanced 区的 extra flags。
2. **研究功能是"区块"，不是散开关**：消融/技能/rigor 各自是一个有前置条件、
   有守护、有报告闭环的实验设计单元，按区块整体呈现。
3. **执行量必须先于 Launch 可见**：任何会放大执行量的选项（消融变体、repeat、
   多 agent）都要进 Review 步的账单公式。
4. **任务级事实在任务库呈现**：`allow_web_search`、超时、专家步骤数、rigor 数
   是任务的属性，徽章化显示在任务卡/详情页，不进向导表单。
5. **隐私边界**：`human_reference.json` 的 `reasoning` 与 rigor 的内部推导是
   私有内容，API 一律不返回（现有 runner 已保证不进 executor/evaluator
   工作区，GUI 沿用同一红线）。

## 3. 批次一（B1）— 运行旋钮补齐与发现性

### 3.1 Shared config 新增 "Advanced" 折叠区（默认收起）

| 控件 | 参数 | 说明文案要点 |
|---|---|---|
| Judge parallelism（数字，默认 4） | `--max-evaluator-parallel` | 并行评审数；调大加速、也放大评审端限流风险 |
| Claude max turns（数字，留空=不限） | `--claude-max-turns` | 仅作用于 Claude Code 执行；**launcher 需补透传** |
| Extra CLI flags（mono 文本框） | 追加进 argv | 逃生舱：bin 覆盖、`--docker-bin` 等工程旋钮从这里走 |

### 3.2 Thinking effort 发现性

现状要先在 Per-agent fields 勾选才出现。改为：Claude Code 参赛卡**始终**显示
thinking effort 行（默认 none）；Per-agent fields 里对应选项仅决定"是否逐 agent
个性化"，不再决定可见性。

### 3.3 任务库徽章

任务卡与任务详情页显示：`web search 允许/禁止`（`allow_web_search`，
tri-state：true/false/未声明）、超时（卡片已有，详情页补齐）、
`专家步骤 ×N` / `rigor ×N`（有则显示，为 B3/B4 的前置可见性）。

涉及文件：`gui/launcher.py`（max_turns 透传）、`gui/contracts.py` + gen-types、
`NewRun.tsx`（Advanced 区、参赛卡）、`Tasks.tsx`/`TaskDetail.tsx`、
`tests/gui/{test_launcher,test_experiments}.py`。
验收：argv 含新旗标的等价性断言；UI 截图核查；测试全绿。

## 4. 批次二 A（B2）— Skills 资源页 + 向导内嵌（形态已拍板）

### 机制事实（已核对代码）

技能库根目录（默认 `executor_skills/`，CLI `--executor-skill-root`）下
`registry.json`：`{"skills": [{id, …}], "groups": {group_id: [skill_id…]}}`；
`--executor-skill <id>`（可重复）与 `--executor-skill-group <gid>`（展开为 id 集）
选择注入哪些技能；运行时技能目录被安装进各 runtime 的技能位置（由 adapter 的
`executor_skill_install_root` 决定）并在提示词中注明位置。任务包也可自带
`executor_skills.json` 局部技能。

### 资源页（一级导航 "Skills"，位于 Agents 与 AI providers 之间）

- **v1 只读**（与"文件系统即真相源"一致）：技能卡（id、描述、文件数/大小、
  所属分组徽章、sha256 校验状态）+ 分组区；页头显示技能根目录与
  "如何添加技能"的简短指引（指向 docs/executor_skills.md）。
- registry 解析失败 → 错误卡（同 Agents 页的坏 spec 处理）。
- 后端：`GET /api/skills`（skills + groups + root + 每技能元数据），进 contracts。
- **不做 CRUD**：技能是"目录 + registry 登记"的复合资产，v1 编辑成本高收益低；
  列入"不做什么"。

### 向导内嵌（Shared config 新增 "Executor skills" 区块）

- 多选器分两栏：分组（勾一组=展开该组全部技能，显示成员）与单个技能；
  已选技能以徽章列出。
- **v1 为 shared**（所有参赛 agent 注入同样技能=对照公平，与共享评审同理）；
  per-agent 技能对比列为后续增强。
- 计划期校验：技能 id/group 存在性（复用 registry 展开逻辑），失败 →
  ExperimentError 人话报错。
- Review 步：已选技能列入摘要卡。

涉及文件：`gui/skills.py`（新 service，包装 `starbench.skills.registry`）、
`server.py` 路由、`contracts.py`、`launcher.py`（`--executor-skill*` 透传）、
前端 `pages/Skills.tsx` + 导航 + `NewRun.tsx` 区块、
`tests/gui/test_skills.py`。
验收：dry-run argv 含 `--executor-skill` 序列；不存在的 id 被计划期拦截；
资源页对空库/坏 registry 的空态与错误态。

## 5. 批次二 B（B3）— Instructions 区块（消融；形态已拍板）

### 形态

Shared config 新增 "Instructions" 区块（Judge 区之后），四张模式卡：

| 卡 | CLI | 文案要点 |
|---|---|---|
| None（默认） | `--instruction-mode none` | 基线：任务原样执行 |
| Selected steps | `select` + `--instruction-step` | 勾选的专家步骤拼进提示词，跑一次 |
| Traverse | `traverse` | 每条步骤单独一个变体 |
| Ablation | `ablation` | 基线 + 逐条 + 全合并；自动产出 uplift 报告 |

- 选 Selected 时出现**步骤多选器**：step_id、step_type、instruction 原文预览。
- 选 Ablation 时提示"建议 repeat ≥ 3"（一键把 repeat 设为 3）。
- **守护**：所选任务全部无 `human_reference` → 区块置灰并说明；部分有部分无 →
  琥珀色警告（无步骤的任务按基线跑，明说）。
- **Review 账单公式升级**：`tasks × 变体数 × repeat × agents`，变体数 =
  none/select→1、traverse→N、ablation→N+2；消融实验在摘要卡里列出变体构成。

### API 扩展

`task_package_detail` 增加 `human_reference_steps` 明细（step_id/step_type/
instruction 三个公开字段；**`reasoning` 不返回**——隐私红线写进 contracts 注释
与测试断言）。launcher 补 `--instruction-mode/--instruction-step` 透传。

涉及文件：`gui/library.py`、`launcher.py`、`experiments.py`（变体数进 plan 摘要）、
`contracts.py`、`NewRun.tsx`、`tests/gui/{test_library,test_experiments}.py`。
验收：ablation dry-run 的 argv 正确；reasoning 永不出现在任何 API 响应
（显式测试）；账单公式对四种模式的断言。

## 6. 批次二 C（B4）— Rigor 小节

机制（已核对文档与旗标）：任务包 `rigors.json`（rubric 级硬性要求）+
`task.json` 登记；`--rigor-mode select` + `--rigor <id>`（可重复）把选中要求以
"Ensure your answer reaches an equivalent level of rigor…" 前缀注入提示词。
官方口径：**受控实验用，不是默认基准设置**。

形态：并入 Instructions 区块内的并列小节（区块更名为
**"Prompt assistance (research)"**，下分 Expert instructions 与
Rigor requirements 两小节）——两者同属"往提示词注入什么"家族，文档口径也
互相引用。Rigor 小节 = 开关 + 要求多选器（id + requirement 原文），守护与
账单逻辑复用 B3。API：task detail 增加 rigors 公开明细；launcher 补透传。

验收同 B3 同构；额外一条：默认关闭 + 文案里保留"受控实验用"的官方口径。

## 7. 执行顺序与依赖

```
B1（小，独立）→ B2（Skills，独立）→ B3（Instructions）→ B4（Rigor，复用 B3 骨架）
```

四批都会改 `NewRun.tsx` 与 `contracts.py`，**必须串行**避免冲突。每批交付物：
代码 + 测试 + `make gen-types` 产物 + 前端构建产物 + 截图验证 + 里程碑 commit。
B3/B4 完成后更新 `docs/gui.md` 与 `docs/recipes.md`（"给任务加专家步骤/rigor"
菜谱）。

## 8. 不做什么

- 不做 Skills 的 GUI CRUD（v1 只读；创建走文件系统 + 文档指引）。
- 不做 per-agent 技能注入（v1 shared，对照公平优先；列为后续增强）。
- 不把 `--auth-mode`/bin 覆盖/`--docker-bin` 请回表单（逃生舱走 Advanced
  extra flags）。
- 消融不做向导分叉（与多 agent 正交，是共享配置的一个维度）。
- 不在 GUI 暴露 `reasoning`/rigor 内部推导（隐私红线）。
