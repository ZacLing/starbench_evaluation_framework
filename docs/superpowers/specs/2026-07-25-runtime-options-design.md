# Runtime Options（专属旋钮收编）设计

> C 轮设计文档。B 轮（registry 收编，commits bd79017..7a734ae）之后，公共结构中仅剩的
> runtime 实名残留就是本文要消除的：`claude_max_turns` 与 `opencode_provider/base_url/api_key_env`
> 及其角色变体。实施计划由本文派生；与本文冲突时以本文为准。

## 背景与问题

runtime 专属配置目前以**实名字段**焊穿每一层公共结构：

- CLI：10 个专属旗标（`--claude-max-turns`、`--opencode-provider/base-url/api-key-env` × 共享/executor/evaluator 三组）
- 启动契约：`run_plan.schema.json` 10 个扁平键；`profile_snapshot.schema.json` 1 个（`execution.claude_max_turns`）
- 共享上下文：`ExecutorContext` 4 个实名字段、`JudgeContext` 3 个
- GUI：`contracts.py` 7 处、`planning.py` 16 处、`launcher.py` 10 处引用；前端手写 max-turns 输入框

后果：每新增一个专属参数 ≈ 改 10 个文件；GUI 控件只能手工焊接（"参数可视化完成度低"的结构性根源）；
填错旋钮名被静默忽略。

## 目标

1. 公共结构（CLI/契约/上下文/GUI 框架）不再认识任何具体 runtime 的名字
2. adapter 声明旋钮 → GUI 自动渲染控件；新增旋钮只改一个 adapter 文件
3. 未知/错型旋钮在启动前报出具体、可行动的错误

## 非目标

- 不改评测语义（verdict、聚合、种子、公平性）
- 不改 Provider 资源模块与注入通道语义（网关决策点唯一：执行侧选 Provider）
- 不为 custom runtime 增加旋钮声明能力（未来扩展，见文末）
- `thinking_effort` / `web_search` 保持跨 runtime 通用设置，不入盒

## 术语

| 术语 | 含义 |
|---|---|
| 旋钮（knob） | 只对某一个 runtime 有意义的专属配置项 |
| user 旋钮 | 用户在 GUI 主动填的值（今天仅 `claude.max_turns`） |
| wiring（接线） | 后端从 Provider 登记换算出的传输值，用户不可见（`opencode` 三件套） |
| 盒子（options box） | 启动契约中按角色命名空间化的旋钮容器 |

## 已确认的关键决策

| # | 决策 | 拍板 |
|---|---|---|
| D1 | 范围：user 旋钮 + wiring 全部入盒 | 用户（2026-07-24） |
| D2 | 契约演进：硬切 v2 + profiles.json 一次性迁移（带备份）；旧 CLI 旗标删除 | 用户（2026-07-24） |
| D3 | 盒子维度：按角色分盒 `executor_options` / `evaluator_options`（表达力与双层嵌套等价、无重复信息；agent 名分盒无法表达同 runtime 双角色异构配置） | 工程决策 |
| D4 | `surface: user/wiring` 只约束 GUI 渲染，不约束 CLI/plan 输入合法性（CLI 独立使用必须能手填 wiring） | 工程决策 |

## 数据形状

### run_plan v2（示例）

```json
{
  "schema_version": 2,
  "executor_agent": "claude",
  "evaluator_agent": "opencode",
  "executor_options": { "max_turns": 50 },
  "evaluator_options": {
    "provider": "yunwu",
    "base_url": "https://yunwu.ai/v1",
    "api_key_env": "OPENAI_API_KEY"
  }
}
```

规则：

- `schema_version` enum 收紧为 `[2]`；v1 文档拒绝，报错列出待改键与新写法
- 删除 10 个扁平键
- 两个盒子均可选；schema 层约束：键名 `^[a-z][a-z0-9_]*$`，值类型 `string|integer|boolean|null`，
  字符串 `maxLength: 512`，盒子 `maxProperties: 32`
- **additionalProperties 纪律的唯一豁免点**：盒内键无法在 schema 静态枚举（按 runtime 动态），
  故 schema 只约束形状，**解析期强校验补足**（盒内每键必须是该角色 agent 声明过的旋钮，否则拒绝）。
  防泄密线不退：值仅限标量、凭证只允许出现环境变量**名**（wiring 的 `api_key_env` 语义即此）

### profile_snapshot v2

- `execution.claude_max_turns` 删除
- 每个 contender 条目新增可选 `options` 对象（形状约束同上）；judge 侧新增 `execution.evaluator_options`
- 语义迁移：旧 `execution.claude_max_turns: N` → 每个 `agent == "claude"` 的 contender 得 `options: {"max_turns": N}`
- 双树同步走 `make sync-schemas`，相等性测试守护

## 组件设计

### 1. 旋钮声明（adapters/base.py）

```python
@dataclass(frozen=True)
class RuntimeOption:
    name: str            # ^[a-z][a-z0-9_]*$
    type: str            # "integer" | "string" | "boolean" | "enum"
    role: str = "executor"   # "executor" | "evaluator" | "both"
    surface: str = "user"    # "user"（GUI 渲染） | "wiring"（GUI 永不渲染）
    label: str = ""      # user 旋钮的界面标题
    help: str = ""       # user 旋钮的一句说明
    default: object = None   # None = 未设置（沿用 CLI/adapter 自身默认行为）
    choices: tuple = ()  # 仅 enum
```

`RuntimeInfo` 新增 `options: Tuple[RuntimeOption, ...] = ()`。

各 adapter 声明：

| adapter | 声明 |
|---|---|
| claude | `max_turns`（integer, executor, user, label "Max turns"） |
| opencode | `provider` / `base_url` / `api_key_env`（string, both, wiring） |
| codex / gemini / grok | 无 |

### 2. 上下文（adapters/base.py）

`ExecutorContext` 删除 `claude_max_turns`、`opencode_provider/base_url/api_key_env`，
新增 `options: Mapping[str, object]`（默认空 map）；`JudgeContext` 同理删 3 增 1。
adapter 消费改为 `ctx.options.get("max_turns")` 等。

### 3. 解析期校验（runner 侧，单一实现，两入口共用）

对每个角色：resolve 该角色 agent → 取其声明中 `role` 匹配的旋钮集 →

1. 盒内未知键 → 错误：`{agent} 没有名为 "{key}" 的旋钮；它声明的{角色}侧旋钮：{列表或"（无）"}`
2. 类型不符 → 错误：`{agent} 的旋钮 {key} 要求{类型}，收到 {value!r}`（integer 接受十进制字符串并转换）
3. 未填 → 取声明 `default`；`None` 表示不传递（保持该 CLI 自身默认，与今天行为一致）

校验发生在任何任务执行**之前**（与 thinking_effort 拒绝路径同位置）。

### 4. CLI（runner/cli.py）

- 删除 10 个专属旗标
- 新增 `--executor-option NAME=VALUE`、`--evaluator-option NAME=VALUE`（repeatable，`action="append"`；
  无 `=` 或空 NAME 即报错）
- plan→argv 展开表新增规则：`executor_options`/`evaluator_options` 对象展开为对应重复旗标
  （与 `PLAN_LIST_FLAGS` 同一张共享映射表，GUI 与 CLI 两入口结构性不漂移）

### 5. GUI 后端

- `/api/agents` 各 runtime 行新增 `options` 声明数组（name/type/role/surface/label/help/default/choices）；
  `contracts.py` 增 TypedDict + `make gen-types`
- `planning.py`：wiring 换算结果写入对应盒子，停止产出扁平键；contender 卡片收集的 user 旋钮值写入
  该 contender 的 `executor_options`
- `launcher.py`：argv 渲染走新展开规则
- `run_config.json` 记录两个盒子（该文件无 schema；历史 run 文件不动，详情页通用键值渲染，如实展示新旧形状）

### 6. GUI 前端

- 通用控件 `RuntimeOptionFields`：按 `/api/agents` 声明渲染 `surface == "user"` 且角色匹配的旋钮
  （integer→数字框，boolean→开关，enum→下拉，string→文本框；label/help 来自声明）
- 参赛者卡片（AgentsStep）渲染 executor 侧 user 旋钮——每个参赛者独立取值（行为升级：不同 Claude
  参赛者可填不同 max_turns）；裁判区（SharedConfigStep）渲染 evaluator 侧 user 旋钮
- 删除手写的 Claude max-turns 输入框；wiring 旋钮任何情况下不渲染

### 7. profiles.json 一次性迁移

- 加载器识别旧形状（存在 `execution.claude_max_turns` 或缺新版标记）→ 先写 `profiles.json.v1.bak`
  → 按语义迁移规则原地改写 → 打新版标记
- 幂等：新形状直接通过；中途失败下次从备份重来，不产生半新半旧文件

## 错误处理（示例文案）

```
$ starbench-run --executor-agent gemini --executor-option max_turns=50 ...
error: gemini has no option named "max_turns" (it declares no executor-side options).

$ starbench-run --executor-agent claude --executor-option max_turns=abc ...
error: claude option max_turns expects an integer, got "abc".

$ starbench-run --plan old-v1-plan.json
error: run plan schema_version 1 is no longer accepted. Move "claude_max_turns"
into "executor_options": {"max_turns": ...} and re-emit with schema_version 2.
```

对比现状：未知旋钮名今天被静默忽略——该状态从此不存在（数据诚实原则在配置层的延伸）。

## 不变量

1. 评测语义零变化；对同一配置，executor/judge 收到的最终命令行与今天逐字节等价
2. Provider 模块、注入通道语义不变；网关决策点唯一
3. wiring 值永不出现在 GUI；凭证**值**永不落盘（延续 `api_key_env` 名字纪律）
4. runner 独立可用：不依赖控制台文件；启动单自包含
5. 公共层（CLI/契约/上下文/前端框架）零 runtime 实名引用（B 轮不变量的收尾）

## 测试策略

| 层 | 内容 |
|---|---|
| 声明守卫 | 每个 adapter 的 options 合法：名字唯一且合模式、enum 必有 choices、wiring 均为标量 string |
| 校验单测 | 未知键 / 类型错 / 默认值 / 十进制字符串转换 四条路径 |
| 迁移单测 | 真实旧样本：迁移正确、幂等、备份生成、半途失败可重入 |
| 契约测试 | v2 通过、v1 拒绝且文案指向改法；schema 双树相等性 |
| 等价性 | GUI plan 与 CLI argv 两入口产出同一盒内容；`--executor-option` 与盒展开一致 |
| 端到端 | fake CLI：max_turns 落入 claude argv；三件套落入 opencode 生成配置 |
| 收尾 | 全量 unittest 绿 + `npm run build` / `make gui-build` 绿 |

## 未来扩展（本轮不做）

- custom runtime 在 `runtimes/<id>.json` 中声明自己的旋钮（`SpecAdapter` 转译为 `RuntimeOption`）
- 更多内建 user 旋钮（如 Codex sandbox 级别）——改动面从此仅为该 adapter 的声明一行 + 消费一处
