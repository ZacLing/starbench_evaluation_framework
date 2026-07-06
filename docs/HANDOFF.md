# 交接文档：StarBench Console 产品方向与工程状态

> 2026-07-06 由 Claude Code 会话交接给 Codex。本文自包含：产品定位决议、当前状态、待办清单（含已定方案）、硬约束。读者是接手的 AI agent 与维护者本人（Lucas / 王立奇）。

## 1. 产品定位决议（本次会话与维护者讨论的结论，指导所有 scope 决策）

背景事实：星尘已有覆盖 HSW 全流程的 StarBench 平台（专家招募、任务生产、Boosting、Peer Voting、eval），开发测试中；**平台 eval 环节接入的就是本仓库的 CLI（`starbench-run`）**。

三层定位：

1. **`starbench-run` 是无状态引擎**。CLI 进出、文件制品进出（任务包 → runs 目录）。平台是它的第一个平台级消费者；argv 就是 API。
2. **GUI console（`starbench-gui`）是本地驾驶舱**，服务单个研究员：配实验、跑评测、看轨迹、debug 任务包。它**不做**服务器多用户部署（单实例多用户 = runs 混杂 + 共享凭证 + 无隔离，明确拒绝这个中间态）；平台不需要这个 console，平台自己的 UI 消费引擎制品。Electron 打包不做（收益低）。
3. **独立产品愿景（维护者判断，方向认同）**：框架有潜力独立产品化，形态是"刀架与刀片"——框架开源建立"agent CLI 评测标准运行时"的位置，星尘的专家 golden task 集是商品，框架是任务集的官方运行时；增长场景是企业 agent 选型评测与 agent 团队的 CI 式回归测试。差异化：多 CLI adapter 注册表（脏活护城河）+ rubric judge 使无单元测试的任务可评（对比 SWE-bench 生态的空位）+ 专家数据钩子（instruction 消融量化专家指令 uplift、rigor 注入、skills 注入）。竞品参照：Terminal-Bench（最近）、Inspect AI（通用位已被占，不去打通用）。

由此得出的工程纪律：**任务包格式与 runs 制品（summary.json 等）是对外契约**，改动要有版本意识；GUI 按对外产品的标准打磨（这解释了本分支大量产品质量整改）。

## 2. 当前状态

- 分支 `gui-impeccable`（已推送 origin，领先 main 60+ commits），工作树干净。测试双绿：`uv run --with pytest pytest tests/ -q`（219 passed）与 `make test`（unittest discover）。
- 本分支主线（按时间）：runner/adapter 架构重构（P1–P4：adapter 注册表单一事实源、GUI 读注册表、runner 拆分、judge env 隔离、生成式 TS contracts）→ 配置面完备（B1–B4：高级旋钮、Skills 页、instruction 消融、rigor 注入）→ B5/B6 就绪体系（坏任务包可视化、traverse/ablation 计划期硬拦、Review 预检门禁 Launch、任务事实条、Research add-ons 折叠）→ thinking-effort/web-search 真开关（见下）→ Providers 页目录来源诚实化 + 模型清单弹窗 → 侧边栏调试残留清理。
- **Thinking effort 现状**（经文档 + 本机 CLI `--help` 双重实锤）：通用 `--thinking-effort`，per-runtime 原生机制——Claude Code `--effort`（none/low/medium/high/xhigh/max）、Codex `-c model_reasoning_effort`（none/minimal/low/medium/high/xhigh）、OpenCode `run --variant`（内置变体并集，含 max）；Gemini/Grok/custom 为提示词三档。档位集是 `RuntimeInfo.thinking_efforts` 声明的 runtime 事实：参赛卡按集合渲染、计划期与 runner 启动双重校验。`--claude-thinking-effort` 是兼容别名。
- **Web search**：`--web-search {task,allow,deny}`，仅 Claude（工具白名单）与 Codex（`--search`）可强制；其他 runtime 在计划里收到"不可强制"警告。
- 关键文件地图：`src/starbench/adapters/`（RuntimeInfo + 5 内置 + spec.py 自定义；**runtime 事实唯一来源**）、`src/starbench/runner/`（cli/orchestrator/executor/judge/summary/env_scope，run_benchmark.py 是兼容壳）、`src/starbench/gui/`（server/data/library/providers/experiments/launcher/injection/contracts）、`gui-frontend/src/`（React；`lib/api-types.ts` 是 `make gen-types` 生成物，勿手改）、`runtimes/`（出厂 custom spec：qwen-code/kimi-code/trae-agent）、`docker/`（7 个镜像）。

## 3. 待办清单（优先级排序，P1 方案已与维护者定稿）

### P1：文件夹选择器重做（`gui-frontend/src/components/task-import.tsx` 的 `DirectoryPickerDialog` + `src/starbench/gui/library.py` 的 `browse_directories`）

已确认的缺陷与已定稿的方案：

1. 路径条的 `dir="rtl"` 截断 hack 造成 bidi 重排（前导 `/` 消失、尾部多 `/`），观感如渲染 bug。**换成面包屑 + 可编辑双态**：平时显示可点击路径段（点任一段跳转），点击进入编辑态可直接粘贴绝对路径回车跳转。
2. 后端 `_is_allowed` 把浏览范围白名单限制在 home + cwd。**按"本地驾驶舱"定位放开为全盘**（server 以用户权限跑且只绑 127.0.0.1，CLI 的 `--tasks-dir` 本就无限制，白名单是伪安全）。至少加 `/Volumes`；建议直接放开。
3. 起始目录持久记忆（现在只在组件内存里）：localStorage 记住上次使用目录；首开时若已有注册任务库，从最近库的父目录开始。
4. 适格性前置：绿色小字 "contains N task packages" 升级进确认按钮文案（"Use this folder — N task packages"）；0 个时按钮旁明确说明（仍可注册，之后导入）。
5. 细节：列表高度对齐行高（当前 h-64 永远裁半行）；目录多时加过滤框（参照 Providers 模型清单弹窗的模式）。

### P2：制品契约文档 `docs/artifact_contracts.md`（产品化奠基，平台立即受益）

任务包格式（task.json/prompt.md/rubrics.json/human_reference.json/rigors.json——注意 human_reference 的 `reasoning` 字段是私有的）与结果制品（runs 目录布局、summary.json、status.json、manifest.json）各给 schema 与版本号。导入校验逻辑（`gui/library.py`）已覆盖八成，抽出规范即可。

### P3：CLI 兼容政策正式化

argv 是平台消费的 API。把 `--claude-thinking-effort` 别名先例升格为政策：deprecation 周期、CHANGELOG、语义版本。写进 `docs/runner_reference.md` 或独立短文档。

### P4：机会项（有闲再做）

- Grok Build 装上 CLI 后实锤 `--reasoning-effort`（第三方 guide 称有，取值 none/minimal/low/medium/high/xhigh；官方文档未直接列出，**未实锤前不接**），确认后把 grok 的 `thinking_channel` 升级为 native_config。
- Gemini（settings.json `thinkingBudget`/`thinkingLevel`）与 OpenCode 的 Docker seed 配置升级路径（Kimi 镜像有 seeded config 先例：`docker/kimi-config.toml`）。
- 超大文件拆分：`gui-frontend/src/pages/NewRun.tsx`（2600+ 行）最迫切；`skill_distiller.py` 等见 `docs/architecture_plan.md` §6 审计。

## 4. 硬约束（红线，违反即返工）

1. **隐私**：`human_reference.json` 每步的 `reasoning`（专家私有思路）**绝不进任何 API 响应**。唯一合法读取器是 `gui.data.read_human_reference_steps`，测试有断言。
2. **凭证**：API key 不落盘、不走浏览器——GUI 只传环境变量**名**，值由 server 从自身环境解析；executor/judge 凭证用 `STARBENCH_EXECUTOR_ENV_*` / `STARBENCH_JUDGE_ENV_*` 前缀传输并在 runner 里拆成隔离作用域；绝不上 argv、绝不写临时文件。
3. server 只绑 127.0.0.1。
4. **流程**：改 `gui/contracts.py` 后必须 `make gen-types`（有 drift 测试）；每次改动跑双测试套件；前端改动 `npx tsc -b && npm run build`，并用 Playwright 截图回读验证（脚本模式见 scratchpad 惯例，勿把测试产物提交进仓库）。
5. **产品语言纪律**（维护者多次强调，违者被骂）：UI 不出现内部黑话（"spec"、"custom:" 前缀、文件路径小字等调试残留）；runtime/任务的每个执行事实要可见（不藏 tooltip）；不假装——不可强制的开关要明说不可强制，目录数据不冒充连通性证明；档位/枚举必须对应 CLI 真实取值（先查文档再本机 `--help` 实锤）。
6. commit 信息用英文、讲清 why；Codex 的提交署 Codex 的 co-author 行。commit 前测试须绿；维护者要求定期按功能点 commit，不堆积。

## 5. 维护者工作偏好（对齐成本最低的合作方式）

- 产品视角优先：动手前先想"用户读到的故事是什么"，而不是"数据有没有"。被质疑时先查证事实（文档 + 本机实锤双重验证）再回答，不凭训练记忆断言 CLI 参数。
- 大改动先出规划文档（docs/ 下有 architecture_plan.md、config_surface_plan.md 先例：目标/方案/验收标准，执行后回写状态）。
- 需求模糊时先对齐方向和 70 分标准再执行；讨论请求（"我们讨论一下"）只给分析不动代码。
- 不可逆操作（删除/覆盖/force push）先列清单等明确同意。
