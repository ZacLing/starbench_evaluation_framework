# Pi Agent 运行时接入（一等 adapter）设计

> 目标形态一句话：`pi`（pi.dev 的多 provider 编码代理）成为第六个内置运行时——
> `adapters/pi.py` + 注册表一行登记，GUI/CLI/预检/注入全部自动派生；
> 凭证只走环境变量，操作者的个人 `~/.pi` 与基准流量完全隔离。
> 本轮同时是 B 轮注册表架构"新增运行时只碰个位数文件"承诺的实战验收。

## 背景

Pi（`@earendil-works/pi-coding-agent`，源码 `github.com/earendil-works/pi`）是
headless 友好的多 provider 编码代理，形态完全落在本仓适配器的既定假设内
（headless CLI + 一次性 prompt + 文件系统工作区，见 RuntimeAdapter 边界档案）。

一手事实（来源：pi.dev 官方文档与 GitHub 源码仓 docs/，2026-07-26 抓取）：

| 事实 | 内容 | 来源 |
| --- | --- | --- |
| headless | `pi -p "<prompt>"`；stdin 管道输入会被合并 | docs/usage |
| 事件流 | `pi --mode json`：JSONL 到 stdout；首行 `{"type":"session",...}`，随后 `agent_start/turn_*/message_*/tool_execution_*/agent_end` | docs/json.md |
| 事件类型定义 | TypeScript：`packages/coding-agent/src/core/agent-session.ts`、`packages/agent/src/types.ts` | 源码 |
| 模型选择 | `--provider <name>` + `--model <pattern>`；`--model` 支持 `provider/id` 与 `:<thinking>` 思考档后缀 | docs/usage |
| 思考档位 | `off / minimal / low / medium / high / xhigh / max`（`PI_REASONING_LEVEL` 值域） | docs/environment-variables |
| 凭证 | 按 provider 环境变量（`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` / `XAI_API_KEY` 等）；`--api-key` 旗标优先；OAuth 订阅存 `~/.pi/agent/auth.json` | docs/providers |
| 配置隔离 | `PI_CODING_AGENT_DIR` 覆盖配置目录（默认 `~/.pi/agent`）；`PI_CODING_AGENT_SESSION_DIR` 覆盖会话存储；`PI_OFFLINE=1` 关闭启动网络操作（更新检查、遥测）；`PI_SKIP_VERSION_CHECK=1` | docs/environment-variables |
| 技能 | 实现 Agent Skills 标准；`--skill <path>` 可重复、显式路径在 `--no-skills` 下仍装载；项目级 `.pi/skills`、`.agents/skills` 受 trust 门控 | docs/skills |
| trust | 非交互模式（`-p`/`--mode json`）不弹 trust 提示；无既存决定时默认忽略项目资源；`--approve/-a` 可单次覆盖 | docs/security |
| 权限 | 无内置沙箱、无逐工具确认；隔离靠运行环境 | docs/security |

## 目标

1. Pi 成为一等内置运行时：执行器与评审两种角色，GUI 各页自动呈现。
2. R1 支持四种原生 provider kind：`anthropic` / `openai` / `google` / `xai`，
   经环境变量 + `--provider/--model` 直驱，零配置文件。
3. 思考档走原生通道（`--model` 的 `:<level>` 后缀），档位集全量声明。
4. 操作者隔离与凭证红线成立（见"红线"节）。
5. 确定性 fake-CLI 测试为验收标准；真机冒烟为可选跟进。

## 非目标（明确出界）

- **openai-compatible provider（自定义 base-url 端点）**：推 R2。前置条件是核实
  pi `models.json` 的 `apiKey` 字段是否支持环境变量引用——若只能明文落盘则密钥
  会进 run 目录，触红线；核实通过前不做。
- Docker 执行后端（pi 有 containerization 文档，留待需要时另立）。
- 品牌图标：R1 用现有 fallback（pi 不在 `@lobehub/icons`）；品牌 SVG 可后补。
- custom runtime 平权（图标自由化 + options 旋钮字段进 JSON schema）：独立一轮，
  与本轮无依赖关系。
- pi 的扩展（extensions）、包（packages）、RPC 模式：基准执行不需要。

## 设计

### 1. RuntimeInfo 档案（`adapters/pi.py`）

- `id="pi"`，`label="Pi"`，`bin="pi"`，`docker_image=None`（宿主本地，
  与 Claude Code / Gemini CLI / Grok Build 同站位），`default_executor_backend="local"`。
- `provider_filter`：`kinds=("anthropic", "openai", "google", "xai")`。R1 不声明
  endpoint 接受位（openai-compatible 出界）。
- `injection`：新增 kind `"pi_gateway"`，镜像 `opencode_gateway` 的三旋钮模式——
  wiring surface 的 `provider` / `api_key_env` 选项（`base_url` 留待 R2，R1 不声明）。
  消费点为 `gui/injection.py` 的一个新分支：把所选 provider 的 kind 映射为 pi 的
  `--provider` 名与该 provider 的 key 环境变量。
- `thinking_channel="native_config"`；`thinking_efforts=("default", "off", "minimal",
  "low", "medium", "high", "xhigh", "max")`。`"default"` 表示不加后缀、留 CLI 默认。
- `judge_sensitive_env`：各 provider key 环境变量全集，外加 `PI_CODING_AGENT_DIR`、
  `PI_CODING_AGENT_SESSION_DIR`——参赛者注入这两个变量可重定向评审侧配置，必须列管。
- `credential_env_keys=()`：与 OpenCode 同策——凭证按所选 provider 经 wiring 旋钮
  声明，预检读旋钮而非固定 key。
- `enforces_web_search=False`（待核实项 3 若翻案则改）。
- `options`：仅 wiring surface（`provider`、`api_key_env`）；R1 无 user surface 旋钮。

### 2. 进程形态

**执行器**（`run_executor`）：

- 命令：`pi --mode json --no-skills [--skill <path>]... [--provider <name>]
  [--model <pattern>[:<effort>]]`；prompt 走 stdin（任务简报较长，不上 argv；
  待核实项 2 确认无位置参数时 stdin 的消费行为）。
- stdout 直落 `logs/events.jsonl`，stderr 落 `logs/stderr.log`（与姊妹适配器同形）。
- 环境：`ctx.base_env` 之上叠加 `PI_CODING_AGENT_DIR=<agent_home>/pi_executor`、
  `PI_OFFLINE=1`、`PI_SKIP_VERSION_CHECK=1`。会话、trust 决定、遥测全部
  落在 run 目录内的隔离 home，绝不触碰操作者的 `~/.pi`。
- 技能：`--no-skills` 关闭全部自动发现，再对每个已安装的 executor skill 追加显式
  `--skill <workspace/.starbench/executor_skills/<skill-id>>`。任务包内藏的
  `.pi/skills`、`.agents/skills` 永无自动装载路径（trust 默认忽略 + `--no-skills`
  双保险）。skill 安装位置沿用基类 workspace-local 默认。
- auth mode：仅接受 `env`；`global` / `copy-auth` 以带原因的 ValueError 拒绝。

**评审**（`run_judge`）：

- 同 headless 形态 + `append_json_schema_instruction`；stdout 落 `events_path`，
  产出 `judge_final_path`。
- 隔离 home 挂在 `judge_home_base` 下（`<judge_home_base>_pi` 命名沿姊妹惯例），
  与执行器隔离 home 互不相通。
- 评审不装载任何 skill（`--no-skills`，不追加 `--skill`）。

### 3. 事件归一化（`execution/parsers.py`）

- 新增 `write_pi_final_output(events_path, final_path, ...)`：`final.md` 取事件流中
  最后一条 assistant `message_end` 的文本内容；若缺失则回退 `agent_end.messages`
  中最后一条 assistant 消息；两者皆缺按后处理失败降级（`finalize_success` 既有语义）。
- 新增 `normalize_pi_events(events_path, ...)`：将 pi 事件归一为统一 trace 形态
  （provider 标注 `"pi"`），字段映射以 pi 源码的 TypeScript 类型定义为准，不猜。
- 评审侧复用同一对函数，带 `output_schema` 校验（与 custom/opencode 同构）。

### 4. GUI 面

- 主径零前端改动：pi 经 `/api/agents` 自动进入所有页面；provider 过滤为数据驱动
  （`providerMatchesFilter` 读 `provider_filter`），无每-runtime 开关可漏。
- 图标：`AgentIcon` fallback（`SquareTerminal`）。
- 思考档位选择器自动获得 pi 的全量档位（读 `thinking_efforts`）。

### 5. 测试面

确定性 fake pi CLI（沿仓库既有 fake-bin 模式），回放真实形状的事件流
（session 首行 + message/turn/agent 事件，形状照抄 docs/json.md 示例）。断言：

1. 命令构造：`--mode json`、`--no-skills` 常在；`--skill` 逐技能追加且路径在
   workspace 内；`--provider`/`--model` 按旋钮与模型注入；思考档后缀仅在非
   `default` 时出现。
2. 环境隔离：`PI_CODING_AGENT_DIR` 落在 run 目录内；`PI_OFFLINE`、
   `PI_SKIP_VERSION_CHECK` 置位；执行器与评审的隔离 home 不同路。
3. 凭证：所选 provider 的 key 环境变量经 `pi_gateway` 注入执行器 env；
   评审 env 不含参赛者注入的 provider 变量（既有 env_scope 语义的 pi 实例化断言）。
4. auth-mode 拒绝路径：`global` / `copy-auth` 报错信息可读。
5. 产物：`events.jsonl` 原样落盘、`final.md` 提取正确（含 message_end 缺失的
   回退与双缺失的降级）。
6. `gui/injection.py` 的 `pi_gateway` 分支：四种 kind 各一条映射断言。
7. 注册表守卫：现有"内置清单"类守卫测试随 `_BUILTIN_ORDER` 追加自动覆盖。

真机冒烟（可选跟进，非验收项）：安装 pi CLI 后以指定 provider key 跑一个最小任务，
验证 CLI 行为假设与真实世界一致。安装动作发生前先获操作者确认。

## 待核实项（计划阶段消解，全部读 pi 源码或本仓源码，不装 CLI）

1. `RuntimeInfo.protocol` 字段在本仓的全部消费点——pi 是多协议运行时，取值
   （候选 `"multi"`）须先枚举消费面再定，避免撞上按协议特判的旧路径。
2. pi 无位置参数时对 stdin 的消费行为（`-p` 与 `--mode json` 组合下 stdin 是否
   作为完整 prompt）——读 pi CLI 入口源码确认；若必须给位置参数，改为短位置
   参数 + stdin 正文的组合并在 fake 测试中钉住。
3. pi 是否存在可由运行器强制的 web-search 开关（决定 `enforces_web_search`）。
4. `--model` 的 `:<effort>` 后缀与 `--provider` 分列旗标的组合语义（后缀挂在
   pattern 上时 provider 前缀是否可省）。
5. R2 前置：`models.json` 的 `apiKey` 是否支持环境变量引用。

## 触达面

| 文件 | 改动 |
| --- | --- |
| `src/starbench/adapters/pi.py` | 新增（档案 + 两角色进程构造） |
| `src/starbench/adapters/registry.py` | `_BUILTIN_ORDER` 追加一行 |
| `src/starbench/gui/injection.py` | `pi_gateway` 分支 |
| `src/starbench/execution/parsers.py` | 归一化 + final 提取两函数 |
| `tests/` | fake pi CLI + 上述断言面 |
| `docs/runner_reference.md` 等 | 运行时清单处各一行（随实施计划定） |

四个生产文件。对照 B 轮重构前"新增运行时触碰约 9 个文件"的实测，本轮是注册表
架构承诺的验收：超出"2-3 文件"的部分（parsers、injection）是 pi 真实的新行为，
不是重复登记。

## 红线

- 基准执行器流量绝不使用操作者个人订阅身份：`~/.pi/agent/auth.json`（OAuth）
  不进入任何执行路径；auth mode 仅 `env`。与 AGENTS.md 中 Claude Code 的
  同类规则完全同构。
- 密钥不落盘：任何形态的 key 不写入 run 目录内文件（这条红线同时是
  openai-compatible 推 R2 的原因）。
- 测试不触真实 `~/.pi` 与真实 `~/.starbench`；一律显式 `environ=` 注入。
