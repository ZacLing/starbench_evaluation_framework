# Human Reference Steps

## H001 任务定位

Instruction: Identify the true task type, decision audience, and controlling objective before designing the response.

Reasoning: 该任务表面上是技术方案写作，但受众同时包括会计研究负责人、实证研究员、金融计量专家、数据工程团队和研究治理负责人。专家判断是：不能只写软件架构，也不能只写方法论；主线应定位为“方法评估与治理”，并围绕为什么需要平台、如何比较方法、如何保证公平、如何落地和如何审计展开。

## H002 核心矛盾识别

Instruction: Determine whether the task asks for a one-off analysis or a reusable evaluation and governance framework.

Reasoning: 团队真正担心的是测量方法选择不当导致研究结论不可靠，而不是要跑一次模拟并宣布某种方法最好。专家因此将平台价值定义为输出条件化结论：在什么条件下某方法更稳健、在什么条件下会失败，并要求所有比较过程可复现、可审计。

## H003 高优先级风险

Instruction: Surface the failure modes that would make the platform amplify bad research practice rather than correct it.

Reasoning: 会计研究中常见 proxy shopping 和显著性导向选择；模拟参数也可能被设计成偏向某一类方法。专家将“模拟偏向”和“结果导向选择”列为最高优先级风险，要求把预注册、全方法披露、多场景矩阵和尾部失败报告写入方案核心，而不是放在附录。

## H004 MVP判断

Instruction: Choose a minimum viable platform scope that can demonstrate value without overcommitting engineering resources.

Reasoning: 专家判断一开始建设完整 Web 平台和数据库接入成本过高，容易拖垮项目。最小可行版本应以模拟数据为主，比较几种基本方法，并交付构念定义、参数配置、运行流程和标准化报告模板；形态可以是可复现脚本集合加报告模板，而非一开始就做完整产品。

## H005 计量评估设计

Instruction: Define quantitative evaluation criteria and simulation dimensions that a statistical expert would accept.

Reasoning: 计量专家需要看到偏误、方差、MSE、尾部失败、小样本表现和极端情形，而不是笼统的优劣判断。专家会设置 true coefficient recovery 偏差、尾部失败率等指标，并要求模拟覆盖 loading 0.4 到 0.9、不同噪声水平、弱相关/负相关/块状相关、样本量 100 到 5000、结构系数 0 到 0.5，以及反映式与形成式两类数据生成过程。

## H006 数据工程约束

Instruction: Specify how empirical data ingestion, variable lineage, missing data, and sample comparability should be governed.

Reasoning: 数据工程团队会关心 Compustat、CRSP 等数据库变量变化、缺失值和不同方法样本不一致。专家要求主比较使用统一样本和统一缺失处理规则；任何方法专属缺失策略必须作为敏感性分析单独报告，并分解样本差异和方法差异。同时要记录变量血缘、软件版本、随机种子和配置快照。

## H007 预注册治理

Instruction: Design an auditable pre-registration mechanism that limits outcome-driven method selection.

Reasoning: 研究治理负责人需要知道研究员是否先看结果再选择方法。专家要求在评估前提交构念定义、候选方法、场景矩阵、主评估指标和样本构造规则，由系统生成时间戳和哈希锁定配置；后续修改必须作为 amendment 记录并披露是否发生在查看结果之后。预注册前探索只能标记为探索性，不得伪装成主报告依据。

## H008 成功与退出标准

Instruction: Make both success and failure criteria measurable so governance decisions do not depend on vague impressions.

Reasoning: 专家认为漂亮方案如果无法判断成败就不可治理。因此需要量化成功指标，例如模拟中系数恢复偏差小于 0.05、经验数据中 proxy 符号一致率大于 80%、复现包能在 1 小时内跑完主要结果；也要定义退出条件，例如年度维护超过 8 人月但服务项目少于 3 个，或连续 3 次评估无法给出可解释结论。

## H009 PLS术语治理

Instruction: Separate PLS-SEM, PCA, and two-stage proxy construction, and require implementation evidence for method labels.

Reasoning: 专家识别到会计研究者常把两阶段 proxy 构造误称为 PLS。正确处理是明确 PLS-SEM 是迭代估计测量模型和结构模型，PCA 是降维，两阶段聚合不是 PLS；平台应通过方法实现校验模块读取运行日志、配置和软件输出，发现标签与实际算法不匹配时阻断或强制标注为 approximation。

## H010 面板稳定性

Instruction: Extend the evaluation design beyond cross-sectional settings when the research context relies on panel data.

Reasoning: 会计研究中的 earnings quality、governance 等构念常跨多年使用，proxy 质量可能随时间漂移。专家要求加入年度 loading 稳定性、滚动窗口估计、构念漂移、within-firm 与 between-firm 变异比例等检查，否则平台只能服务横截面研究，适用范围不足。

## H011 方案组织

Instruction: Map the reasoning into a section structure that serves all audiences while preserving the governance logic.

Reasoning: 专家会将方案组织为执行摘要、问题背景、系统定位与职责边界、总体架构、潜变量建模策略、测量方法比较框架、验证与评估方法、PLS 治理、风险与控制、研究产出与审计、实施路线图、成本资源、成功标准与退出条件、结论。每一章都要回应至少一个关键角色的需求，并保持“方法评估与治理”的主线。

## H012 最终自检

Instruction: Perform a final expert check for overclaiming, unfair comparison, missing construct types, unresolved conflicts, and audit compliance.

Reasoning: 专家最后会检查方案是否暗示某种方法总是最好，是否遗漏形成式构念模拟，预注册是否留下探索期漏洞，指标筛选是否对所有方法公平，多方法冲突是否有终局规则，审计记录是否需要脱敏。只有这些点修正后，方案才不是漂亮空壳，而是经得起实际使用追问的治理基础设施设计。
