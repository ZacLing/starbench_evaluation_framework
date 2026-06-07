# Task-specific Specialization Examples

- Define Success, Downgrade, Pause, And Exit Criteria: `rsj_intraday_factor_platform` shows this through rsj, realized variance, 日内, bar, tick, sem: # 任务：日内高频 RSJ 因子研究与生产化验证平台技术方案 ## 角色与受众 你需要撰写一份技术方案，面向以下五类角色： - 量化研究负责人（关注因子有效性、方法论严谨性、是否值得投入） - 量化研究员（关注平台易用性、可复现性、实验灵活性） - 数据工程团队（关注高频数据的接入、清洗、存储、版本管理） - 平台工程团队（关注系统架构、可扩展性、维护成本） - 风险管理团队（关注数据质量风险、过拟合风险、生产化准入条件） 方案应对不...
- Define Success, Downgrade, Pause, And Exit Criteria: `rsj_intraday_factor_platform` shows this through 日内: 为日内数据与日频官方价格、成交量 reconciliation 给出价格差异和成交量差异的阻断阈值或可执行的校准规则（例如基于历史分布的分位数或固定百分比差异），并规定超阈值时阻断因子计算或触发人工复核
