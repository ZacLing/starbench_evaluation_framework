# StarBench Evaluation Report Template

本文档是一份 StarBench 测试报告模板，用于记录某个 task 或 task package 的多轮评测结果，并分析结果是否构成稳定、读者公平的 HSW signal。

本报告的主要读者是 task 标注专家、rubric 维护者和 benchmark 维护者。它不是普通排行榜成绩单，而是用于回答三个问题：

- 这次运行是否有效、可复现、没有明显 runner/evaluator 异常。
- 结果是否在 reader-fairness 前提下稳定暴露 Senior-Junior Gap。
- 是否需要修改 prompt、rubrics、runtime 配置或补测失败样本。

复制本模板时，把最终报告写在 run 目录**之外**，并在文件里注明它分析的是哪个
`run_id`：

```text
<你自己的报告目录>/<run_id>-evaluation_report.md
```

不要写进 `runs/<run_id>/`。run 目录的文件所有权是互斥的：runner 是所有 run 制品的
唯一写者，监督器只拥有 `run_state.json` 和 `.runner_claim`（见
`docs/ARCHITECTURE.md` §2）。人工报告落在 run 目录里会破坏这条边界，
让"这个文件是谁写的"不再可判定。

## 1. 基本信息

- Task id: `<task_id>`
- Task package: `<tasks/.../task_package>`
- Run id: `<run_id>`
- Run root: `<runs/<run_id> 或绝对路径>`
- 日期: `<YYYY-MM-DD>`
- Executor: `<agent/runtime>`, model `<model>`, reasoning/thinking `<effort>`
- Evaluator: `<agent/runtime>`, model `<model>`, reasoning `<effort>`
- Backend: `<local/docker>`, image `<image or n/a>`, auth mode `<env/copy-auth/global>`
- API route/provider: `<direct/openrouter/yunwu/etc.>`
- Instruction mode: `<none/traverse/select/ablation>`
- Repeat: `<N>`
- Judge mode: `<single/parallel/both>`
- Web search: `<enabled/disabled by task configuration>`
- Seed: `<seed>`
- Max turns / timeout: `<executor max turns>`, `<task/evaluator timeout>`
- QC note: `<evidence 文件是否真实存在、是否有 evaluator hallucination、是否有 runner 异常>`

填写指南：

- Executor/Evaluator 写清楚 runtime 和模型，不只写模型名。例如 `Claude Code + OpenRouter anthropic/claude-opus-4.8`。
- 如果失败样本不跑 judge，明确写 `skip judge on executor failure: true`。
- 如果有补测、重跑、半成品 run 或 invalid run，在本节说明纳入/排除规则。
- QC note 要检查 evaluator evidence 是否引用真实存在的文件，避免把评估异常当成模型失败。

## 2. 运行有效性与稳定性

### 2.1 Execution Summary

| Metric | Count | Notes |
| --- | ---: | --- |
| Expected executor runs | `<N>` |  |
| Executor success | `<x>/<N>` |  |
| Executor failed | `<x>/<N>` |  |
| Executor timeout | `<x>/<N>` |  |
| Judge success | `<x>/<N>` |  |
| Judge failed | `<x>/<N>` |  |
| Judge skipped | `<x>/<N>` | Usually due to executor failure |
| Invalid/excluded runs | `<x>/<N>` | Explain exclusion rule |

### 2.2 Runtime Failure Types

| Failure type | Count | Affected runs | Interpretation |
| --- | ---: | --- | --- |
| `api_error_socket_closed` |  |  | API/transport/provider route may be unstable |
| `max_turns` |  |  | Agent may need higher turn budget or task may be too tool-heavy |
| `timeout` |  |  | Distinguish true slow task from idle/stalled process |
| `evaluator_error` |  |  | Judge run invalid or needs rerun |
| Other |  |  |  |

填写指南：

- executor 失败的样本不要混入 rubric score 统计，除非报告明确说明它们按 0 分处理。
- `socket closed`、`ECONNRESET`、HTTP `429/502/503` 等要和模型能力失败分开。
- `max_turns` 是运行预算失败，不等同于 task 解题失败。

## 3. 运行统计

### 3.1 Rubric Score Summary

| passed rubrics | total rubrics | runs std | score |
| ---: | ---: | ---: | ---: |
| `<mean passed_count>` | `<total_count>` | `<sample stdev>` | `<mean / total>` |

本次平均 score 为 `<xx.xx%>`，落在项目定义的 `<perfect/good/weaker>` HSW zone。`<N>` 轮标准差为 `<std>`，说明 `<结果稳定/有明显抖动>`。

填写指南：

- `passed rubrics` 填有效 judge 轮次的平均 `passed_count`，保留 1-2 位小数。
- `runs std` 使用样本标准差。
- 如果有效 judge 少于预期 repeat，必须说明统计分母。

### 3.2 Per-Run Details

| Run | Executor | Turns | Exec sec | Judge | Passed rubrics | Total rubrics | Overall pass | Failed rubrics |
| --- | --- | ---: | ---: | --- | ---: | ---: | --- | --- |
| 1 | `<success/failed>` |  |  | `<success/skipped/failed>` |  |  |  |  |
| 2 |  |  |  |  |  |  |  |  |
| 3 |  |  |  |  |  |  |  |  |
| 4 |  |  |  |  |  |  |  |  |
| 5 |  |  |  |  |  |  |  |  |

汇总：

- Passed rubrics per valid judge run:
- Mean passed rubrics:
- Sample stdev:
- Range:
- Overall pass rate:
- Executor success rate:
- Judge success rate:

填写指南：

- `Turns` 可从 runtime event 中提取，例如 Claude Code `num_turns`。
- `Exec sec` 用真实 wall time，避免只看 runtime 内部误报字段。
- 若某轮 executor 失败且 judge skipped，`Passed rubrics` 留空并在失败类型表解释。

## 4. Rubric 失败频次

| Frequency | Rubrics |
| ---: | --- |
| 5/5 |  |
| 4/5 |  |
| 3/5 |  |
| 2/5 |  |
| 1/5 |  |
| 0/5 |  |

填写指南：

- `5/5` 和 `4/5` 稳定失败项通常最能解释 senior gap。
- `0/5` 可列出稳定通过项，帮助判断主干交付是否达成。
- 如果失败项高度集中，说明 task 主要在考系统性能力缺口。
- 如果同一 rubric 忽过忽不过，优先检查 evaluator 稳定性、rubric wording 或输出证据是否模糊。

## 5. HSW 分数区间判断

| Score range | Interpretation |
| --- | --- |
| `<= 55%` | Perfect HSW zone: 公平前提下足够低，强烈说明 task 能暴露 senior gap |
| `55%-65%` | Good HSW zone: 仍然有明确区分度，但可能需要检查是否有部分 rubrics 太容易或 agent 已能覆盖主干 senior 点 |
| `> 65%` | Weaker HSW signal: task 可能偏容易，或 rubrics 未充分覆盖专家级差距 |

填写：

- 本 task 得分 `<xx.xx%>`，属于 `<zone>`。
- 方差 `<高/低>`，说明 `<稳定/不稳定>`。
- 低分主要来自 `<format/fail-fast/senior make-better/runtime failures>`。
- 该结果是否可以解释为“公平下的低分”。

## 6. 初步结果解读

填写：

- executor 是否完成了显性主干要求。
- 稳定失败项集中在哪些高级能力上。
- 失败更像 executor 能力缺口、rubric 过严、evaluator 抖动、runtime/API 问题，还是 task 信息不公平。
- 和上一版 task、上一轮模型或补测结果相比有什么变化。

示例句式：

> 本次结果很适合作为“公平下低分”的样本。executor 能完成完整、可读的主干交付，但稳定无法把 `<senior mechanism>` 落实成可执行机制。失败项不是随机散落，而是集中在 `<capability cluster>`，这更像 senior-grade gap，而不是单轮偶然失败。

## 7. Reader-Fairness 标准

本报告使用 `docs/rubric_reader_fairness.md` 中定义的 reader-fairness 原则：

> 一个 make-better rubric 是公平的，当且仅当它考核的要求可以由独立 agent 从 prompt、materials 以及相关行业知识或逻辑中推导出来。该要求不需要被 prompt 逐字明示，但不能依赖隐藏信息、私有专家偏好或与任务无关的要求。

分析时应区分：

- 明确公平：prompt/materials 明示或直接推出。
- 高级但公平：需要 senior 行业知识或生产经验，但仍能从 task 逻辑推出。
- 灰区：可解释为高级要求，但 wording 可能过窄、过满或过 checklist。
- 不公平：依赖隐藏信息、无关要求、私有偏好，或独立 agent 无法合理推导。

## 8. Rubrics 公平性分组

### 8.1 明确公平

- `<Rubric ids>`: `<为什么可以从 prompt/materials 直接推出>`

填写指南：

- 这里通常包括格式、文件路径、显性章节、明确禁止事项、明确比较对象等。
- 失败时基本可解释为 agent 没遵循显性要求。

### 8.2 高级但读者公平

- `<Rubric ids>`: `<它们如何从任务目标、领域逻辑、生产约束、审计/治理/安全要求推出>`

填写指南：

- 这些项可以偏 senior，但不能依赖隐藏答案。
- 重点说明“为什么独立 agent 有理由想到它”，而不是只说“专家觉得重要”。

### 8.3 灰区或建议微调

- `<Rubric ids>`: `<wording/权重/条件适用/重复计分问题>`

填写指南：

- 问题是信息不公平，还是 wording 太窄。
- 是否应改为条件式。
- 是否应把完整 checklist 改成“实质覆盖关键维度”。
- 是否应从 fail-fast 降为 make-better。
- 是否与另一个 rubric 重复惩罚。

### 8.4 明显不公平

- `<Rubric ids>`: `<为什么独立 agent 无法合理推导>`

如果没有，写：

> 未发现明显信息不公平 rubric。当前 rubrics 整体可以从 prompt、materials、领域逻辑和 reader-fairness 原则中推出。

## 9. 给标注专家的建议修改

| Rubric | Current issue | Suggested action |
| --- | --- | --- |
| `<id>` | `<问题>` | `<保留/删除/降权/改 wording/改 conditional>` |

填写指南：

- 如果 rubric 公平但太硬，优先建议改 wording，而不是删除。
- 如果 rubric 依赖隐藏信息或无关项，建议删除或迁移为非评分参考。
- 如果 rubric 只应在 agent 引入某个主题后适用，改成 conditional wording。
- 如果两个 rubrics 高度重叠，说明应如何区分报告制度、系统机制、自动检测或 fail-fast 权重。

## 10. 复现信息与产物索引

### 10.1 Commands

```bash
# Fill in the exact command or script used for the run.
starbench-run \
  --task <task> \
  --repeat 5 \
  --judge-mode single \
  --run-id <run_id>
```

### 10.2 Important Artifacts

| Artifact | Path |
| --- | --- |
| Run summary | `<run_root>/summary.json` |
| Progress events | `<run_root>/progress_events.jsonl` |
| Per-run task summary | `<run_root>/<task_run_id>/task_summary.json` |
| Executor events | `<run_root>/<task_run_id>/logs/events.jsonl` |
| Executor final output | `<run_root>/<task_run_id>/workspace/outputs/...` |
| Judge result | `<run_root>/<task_run_id>/judges/single_result.json`（judge workspace 内的原件在 `judges/single_workspace/single_result.json`，只在 judge 成功写出时才会被复制到上面这个稳定路径） |
| Judge aggregate（本报告的分数来源） | `<run_root>/<task_run_id>/judges/single_aggregate.json` |

### 10.3 Exclusions / Backfill Queue

| Run | Reason | Backfill needed |
| --- | --- | --- |
| `<task_run_id>` | `<executor failed / judge invalid / timeout / API error>` | `<yes/no>` |

填写指南：

- 失败样本如果没有 judge，应进入 backfill queue，而不是静默消失。
- 如果补测使用不同 runtime/provider/max-turns，要单独写明。

## 11. 结论

用 3-6 句话总结：

- 这次跑测的主要统计结论。
- 运行是否有效，是否有 API/runtime 异常。
- Rubrics 是否整体 reader-fair。
- 是否属于“公平下的低分”，以及落在 perfect/good/weaker 哪一档。
- 低分主要反映什么 senior gap。
- 是否建议保留、微调或删除某些 rubrics。
- 是否需要补测失败样本或调整 runtime 参数。

示例：

> 本次 `<task>` 5 轮结果为 `<passed_counts>`，平均通过 `<mean>/<total>`，score 为 `<score>`，标准差 `<std>`，属于 `<zone>`。有效 judge evidence 均指向真实输出文件，未发现明显 evaluator 异常。Rubrics 整体 reader-fair，低分主要反映 agent 在 `<senior gap cluster>` 上的系统性遗漏。因此该 task `<建议保留/微调/重写>`，并建议 `<specific follow-up>`。
