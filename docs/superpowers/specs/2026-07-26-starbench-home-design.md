# StarBench Home（统一数据根）设计

> 目标形态一句话：`STARBENCH_HOME`（默认 `~/.starbench`）成为全部任务资产与测量事实的
> 唯一数据根；数据位置由 home 决定，绝不由进程工作目录决定；隔离靠显式换 home。
> 文件真相与四份过境契约（ARCHITECTURE §3）不动；实施计划由本文派生，冲突时以本文为准。

## 背景与问题

任务与结果目前锚定在四个互不知晓的位置，产生四个独立病灶：

1. **覆盖率碎片化（核心矛盾）**：coverage / task history / compare 只能看见启动参数
   指向的那一个 `runs/` 目录。每换一个 cwd 或 worktree，测量历史就"失忆"一次；
   Run matrix 作为产品核心承诺，被存储模型结构性削弱。
2. **CLI 默认值失效**：`DEFAULT_TASKS_DIR = PROJECT_ROOT / "tasks"`（`runner/cli.py`）
   锚在源码树根，wheel 安装后指向包安装目录，事实上不可用。
3. **任务库注册即忘**：GUI `POST /api/tasklib/dirs` 仅 append 进内存
   （`services/console.py:register_tasks_dir`），重启丢失。
4. **概念堆积**：多任务库列表、运行时注册、服务端文件夹浏览器、
   `task_history` 中按 `tasks_dir` 的归属匹配补丁——全部源于"没有一个公认的任务之家"。

## 目标

1. 零参数可用：装好即用，CLI 与 GUI 自动发现任务、写入并读取结果。
2. 测量历史在单一档案中累积，coverage 完整。
3. 病灶 2、3 随根治方案消失；病灶 4 的概念集体退役。
4. 内核零感知：env 只在进程入口解析一次，核心代码维持显式路径注入。

## 非目标（YAGNI，明确出界）

- 真相层数据库。文件工件仍是唯一真相：崩溃后已落盘证据完整可读、第三方无需
  import 即可审计、任务包保持 git 友好。
- 持久化查询索引（`home/cache/` + SQLite）。现有进程内 `RunCatalog` 在当前数据量下
  足够；档案增长到扫描可感知延迟时再演进，约束只有一条：索引可随时删除重建，
  永不持有原始事实。
- runs 档案的保留/归档/清理策略。
- 多 workspace / 分舱。切片聚合由既有维度承担（profile rev、batch、variant、seed、时间）。
- `profiles.json` / `providers.json` 迁出 runs 目录。二者随 `runs/` 整体入驻
  `home/runs/`，保持现有 console 文件所有权与路径推导不变；仅当实际造成伤害时再议。

## 语义决策

| 决策 | 选择 | 理由 |
|---|---|---|
| 数据根解析 | 显式旗标 > `STARBENCH_HOME` > `~/.starbench` | 三层各只有一个决定因素；cwd 彻底退出数据定位 |
| 隔离模型 | 显式换 home（`STARBENCH_HOME=/tmp/exp starbench-run …`） | 隔离是显式动作，不因"站错目录"而意外发生或失效 |
| 解析时机 | 仅在进程入口（`runner/cli.py` main、`gui/server.py` main）解析一次，向内传显式路径 | 内核与全部现有测试零改动；`os.environ` 不进入核心层 |
| home 缺失行为 | 读容忍缺失（诚实空态），首次写入时惰性建目录 | 与"文件系统即真相"一致，不做安装仪式 |
| GUI 透明度 | 页面副标题/页脚继续打印解析后的数据根全路径 | 环境变量是隐式状态，界面把它显式化 |
| 旧数据 | 不做自动迁移；文档给出一次性 `mv` 指引 | 迁移是操作者的一次性显式动作，不值得代码化 |

## Home 布局

```
$STARBENCH_HOME（默认 ~/.starbench）
├── tasks/       任务包库（唯一库；子目录含 task.json 即为一个任务）
├── runs/        测量事实（含 console 拥有的 profiles.json / providers.json）
├── runtimes/    custom:<id> 运行时声明
├── skills/      executor 技能库
└── cache/       （预留）可重建索引；删除安全
```

对应入口默认值变更：

- `starbench-run`：`--tasks-dir` 默认 `home/tasks`（替代 `PROJECT_ROOT/tasks`）；
  `--runs-dir` 默认 `home/runs`。
- `starbench.gui.server`：`--runs-dir` 默认 `home/runs`；`--tasks-dir` 默认
  `[home/tasks]`（替代 `[cwd/tasks, cwd/examples/tasks]`）；`--runtimes-dir`、
  `--skills-dir` 默认 `home/runtimes`、`home/skills`。
- 全部旗标保留为最高优先级覆盖（开发、CI、临时实验的逃生舱）；内部管道的
  list 类型与显式注入签名不变。

## 任务库概念坍缩

- `home/tasks` 是唯一任务库。GUI 的"注册目录"入口与 `POST /api/tasklib/dirs`、
  服务端文件夹浏览器 `GET /api/fs/list` 及其前端组件退役删除。
- 任务进入档案的唯一 UI 路径是既有导入向导（拖拽/zip → 校验 → 安装），
  安装目标固定为 `home/tasks`，目标选择控件退役。
- 仓库内 `examples/tasks/` 角色变更为"示例素材源"：契约测试的真值样本地位不变；
  操作者通过导入（或 `cp`）将示例送入 home。开发者调试仓库内数据用旗标覆盖。
- `task_history` 中 `_matches_tasks_dir` 归属匹配逻辑随多库概念一并删除
  （单库之下归属恒真；旧 run_config 中的历史 `tasks_dir` 字段仅作展示信息保留）。

## batch 标签所有权迁移

标签是测量事实的一等维度，但 `batch` 目前只写在 `run_state.json`——那是控制台的
进程监督文件，纯 CLI 发射的 run 永远无法归属实验组。迁移：

- `run_plan.schema.json`（schema_version 2）新增可选属性 `batch`（string，SafeId 词表）。
  可选属性为加法变更，不升版；缺失即"无归属"，诚实为 null。
- runner 将 `batch` 物化进 `run_config.json`；CLI 直跑同样可以 `--batch` 指定。
- 控制台 launch 路径把 batch 从 run_state 专属改为随 plan 下发（run_state 中的
  batch 字段保留写入不删，监督语义不动）。
- 读模型 `_batch_marker` 改为回退链：`run_config.batch` → 旧 `run_state.json` batch
  （旧 run 永远可读，不迁移不修补）。

## 测试策略

- 核心原则验证：现有全部测试不改一行仍然全绿（证明"入口解析、内核显式注入"成立）。
- 新增：入口解析优先级测试（旗标 > env > 默认，含 `~` 展开与相对路径拒绝）；
  batch 回退链测试（仅 run_config / 仅 run_state / 双有 / 双无 四象限）；
  库坍缩后 tasklib 载荷形状测试更新。
- 开发纪律：任何测试不得依赖真实 `~/.starbench`；涉及入口解析的测试显式设置
  `STARBENCH_HOME` 指向临时目录。

## 分期

- **v1（本设计范围）**：入口解析层 + 默认值切换 + 库坍缩（含 API/UI 退役）+
  batch 事实迁移 + 文档（README 快速开始、迁移指引、ARCHITECTURE §1 布局图更新）。
- **后续（各自独立，出现真实痛点再启动）**：`home/cache/` 持久索引；runs 保留策略；
  自由标签（batch 之外的多值 tag）；`profiles.json` 位置调整。
