# StarBench Task Evaluation Report Template

本文档提供一份固定结构，用于汇总某个 task 的多轮运行统计结果，并按 reader-fairness 原则分析 rubrics 公平性。

本报告的主要读者是 task 标注专家和 rubric 维护者。它不是普通模型排行榜意义上的成绩单，而是用于判断一个 HSW task 是否在“读者公平”的前提下稳定暴露 Senior-Junior Gap。

项目期望的理想信号不是单纯高分，而是“公平下的低分”：如果 rubrics reader-fair，且 agent 稳定低分，说明 task 能有效区分普通可交付答案和 senior-grade 答案。

复制本模板时，建议将最终报告放入对应 run 目录下的 `reports/` 子目录，文件名使用：

```text
runs/<run_id>/reports/evaluation_report.md
```

## 1. 基本信息

- Task id:
- Task package:
- Run id:
- Run root:
- 日期:
- Executor:
- Evaluator:
- Backend:
- Instruction mode:
- Repeat:
- Judge mode:
- Web search:

填写指南：

- `Task package` 写 task 包路径。
- `Run root` 写本次 run 的完整路径或相对路径。
- Executor/Evaluator 写模型、reasoning effort、关键运行配置。
- 如果使用 Docker、固定 seed、instruction ablation、固定 executor 输出等特殊设置，也写在这里。

## 2. 运行统计

### 2.1 Summary

| passed rubrics | total rubrics | 5 runs std | score |
| ---: | ---: | ---: | ---: |
|  |  |  |  |

填写指南：

- `passed rubrics` 填 5 轮平均 `passed_count`，保留 1 位或 2 位小数。
- `total rubrics` 填 rubric 总数。
- `5 runs std` 填 5 轮 `passed_count` 的样本标准差。
- `score` 填 `passed rubrics / total rubrics` 的百分比。

### 2.2 Per-Run Details

| Run | Passed rubrics | Total rubrics | Overall pass | Failed rubrics |
| --- | ---: | ---: | --- | --- |
| 1 |  |  |  |  |
| 2 |  |  |  |  |
| 3 |  |  |  |  |
| 4 |  |  |  |  |
| 5 |  |  |  |  |

汇总：

- Passed rubrics per run:
- Mean passed rubrics:
- Sample stdev:
- Range:
- Overall pass rate:

填写指南：

- `Passed rubrics` 使用 evaluator 的 `passed_count`。
- `Total rubrics` 使用 evaluator 的 `total_count`。
- `Sample stdev` 用样本标准差。
- `Overall pass rate` 统计 `overall_pass=true` 的比例。
- 如果某轮 evaluator 明显 hallucinate 或未真实读取输出，应单独标注为 invalid run，不要混入主统计。

## 3. Rubric 失败频次

| Frequency | Rubrics |
| ---: | --- |
| 5/5 |  |
| 4/5 |  |
| 3/5 |  |
| 2/5 |  |
| 1/5 |  |
| 0/5 |  |

填写指南：

- 优先突出 `5/5` 和 `4/5` 稳定失败项。
- `0/5` 可列出稳定通过项，帮助判断主干是否达成。
- 如果失败项高度集中，说明 task 主要在考系统性能力缺口；如果同一 rubric 忽过忽不过，则可能需要检查 evaluator 稳定性或 rubric wording。

## 4. HSW 分数区间判断

| Score range | Interpretation |
| --- | --- |
| `<= 55%` | Perfect HSW zone: 公平前提下足够低，强烈说明 task 能暴露 senior gap |
| `55%-65%` | Good HSW zone: 仍然有明确区分度，但可能需要检查是否有部分 rubrics 太容易或 agent 已能覆盖主干 senior 点 |
| `> 65%` | Weaker HSW signal: task 可能偏容易，或 rubrics 未充分覆盖专家级差距 |

填写指南：

- 这里的 score 指 summary table 中的百分比分数：`mean passed rubrics / total rubrics`。
- 低分必须和 reader-fairness 一起解释。低分如果来自隐藏信息或不相关 rubrics，不是好信号。
- 理想报告结论应回答：这个 task 是否属于“公平下的低分”。

## 5. 初步结果解读

填写：

- 分数整体高/中/低。
- 是否落在 HSW perfect/good zone。
- 方差是否高。
- 失败项是集中在格式/主干，还是集中在 senior make-better rubrics。
- 结果更像 executor 能力缺口、rubric 过严、evaluator 抖动，还是 task 本身信息不公平。

填写指南：

- 不要只看均值。结合标准差、失败频次和 fail-fast 失败情况一起判断。
- 如果 fail-fast 稳定通过而 make-better 大量失败，通常说明 agent 完成了主干，但没达到 senior production-grade。
- 如果 fail-fast 大量失败，优先检查 prompt 遵循、输出路径、文件格式和核心交付要求。

## 6. Reader-Fairness 标准

本报告使用 `docs/rubric_reader_fairness.md` 中定义的 reader-fairness 原则：

> 一个 make-better rubric 是公平的，当且仅当它考核的要求可以由独立 agent 从 prompt、materials 以及相关行业知识或逻辑中推导出来。该要求不需要被 prompt 逐字明示，但不能依赖隐藏信息、私有专家偏好或与任务无关的要求。

分析时应区分：

- 明确公平：prompt/materials 明示或直接推出。
- 高级但公平：需要 senior 行业知识或生产经验，但仍能从 task 逻辑推出。
- 灰区：可解释为高级要求，但 wording 可能过窄、过满或过 checklist。
- 不公平：依赖隐藏信息、无关要求、私有偏好，或独立 agent 无法合理推导。

## 7. Rubrics 公平性分组

### 7.1 明确公平

列出 rubric ids，并说明为什么公平。

### 7.2 高级但读者公平

列出 rubric ids，并说明它们如何从 prompt/materials 和行业逻辑推出。

### 7.3 灰区或建议微调

列出 rubric ids，并说明：

- 问题是信息不公平，还是 wording 过窄。
- 是否应改为条件式。
- 是否应把完整 checklist 改成“实质覆盖关键维度”。
- 是否应从 fail-fast 降为 make-better。

### 7.4 明显不公平

列出 rubric ids。如果没有，写“未发现明显信息不公平 rubric”。

## 8. 给标注专家的建议修改

| Rubric | Current issue | Suggested action |
| --- | --- | --- |
|  |  |  |

填写指南：

- 如果 rubric 公平但太硬，建议改 wording，而不是删除。
- 如果 rubric 考的是隐藏信息或无关项，建议删除或迁移为非评分参考。
- 如果 rubric 只应在 agent 引入某个主题后适用，改成 conditional wording。

## 9. 结论

用 3-6 句话总结：

- 这次跑测的主要统计结论。
- Rubrics 是否整体 reader-fair。
- 是否属于“公平下的低分”，以及落在 perfect/good zone 哪一档。
- 低分主要反映什么 senior gap。
- 是否建议保留、微调或删除某些 rubrics。
