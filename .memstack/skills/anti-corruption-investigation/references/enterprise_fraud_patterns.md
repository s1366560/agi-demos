# 企业欺诈检测模式参考

## 概述

本文档提供企业欺诈案件的通用检测模式，用于增强反腐败调查工具在企业环境中的应用。

## 财务欺诈模式 (Financial Fraud)

### 特殊目的实体 (SPE)
- **英文关键词**: `SPE`, `special purpose entity`, `off-balance sheet`, `off balance sheet`
- **中文对应**: `特殊目的实体`, `表外`, `特殊目的公司`

### 会计操纵
- **英文**: `mark to market`, `MTM`, `aggressive accounting`, `creative accounting`
- **英文**: `revenue recognition`, `earnings management`, `cook the books`
- **中文**: `按市值计价`, `激进会计`, `创造性会计`, `收入确认`

### 财务指标操纵
- **英文**: `EBITDA`, `cash flow`, `pro forma`, `adjusted earnings`
- **英文**: `meet target`, `hit number`, `make the number`, `Wall Street expectation`
- **中文**: `达到目标`, `完成数字`, `华尔街预期`

## 内幕交易模式 (Insider Trading)

### 股票交易相关
- **英文**: `stock option`, `exercise option`, `vest`, `sell stock`, `dump shares`
- **英文**: `before announcement`, `prior to public`, `insider information`
- **中文**: `股票期权`, `行权`, `出售股票`, `内幕信息`

### 时机相关
- **英文**: `timing`, `window`, `blackout period`, `trading window`
- **中文**: `时间窗口`, `禁售期`, `交易窗口`

## 证据销毁模式 (Evidence Destruction)

### 删除/销毁
- **英文**: `delete`, `destroy`, `shred`, `clean up`, `remove`, `erase`
- **英文**: `document retention`, `record keeping`, `file destruction`
- **中文**: `删除`, `销毁`, `粉碎`, `清理`, `移除`

### 保密/隐瞒
- **英文**: `off the record`, `not for publication`, `confidential`, `secret`
- **英文**: `don't tell`, `keep quiet`, `between us`, `need to know`
- **中文**: `不要记录`, `不要发表`, `保密`, `不要告诉`

## 压力与操纵模式 (Pressure & Manipulation)

### 施压
- **英文**: `pressure`, `push`, `force`, `make it happen`, `fix it`
- **英文**: `do whatever it takes`, `get it done`, `no excuses`
- **中文**: `施压`, `推动`, `必须完成`, `解决它`

### 数字操纵
- **英文**: `adjust`, `massage`, `tweak`, `restate`, `correct`
- **英文**: `close the gap`, `bridge the difference`, `find a way`
- **中文**: `调整`, `修改`, `重新表述`, `弥补差距`

## 关键人员识别 (Key Personnel)

### 高风险职位
- **高管层**: `CEO`, `CFO`, `COO`, `President`, `Chairman`, `Director`
- **财务/审计**: `Chief Accounting Officer`, `Controller`, `Auditor`
- **法务/合规**: `General Counsel`, `Compliance Officer`, `Legal`

### 识别模式
- 职位关键词匹配
- 部门关键词匹配
- 签名档分析

## 通信模式分析

### 异常时间模式
- **深夜通信**: 22:00-06:00 的邮件
- **周末通信**: 周六周日的频繁邮件
- **假期通信**: 节假日的紧急通信

### 通信频率异常
- **突然增加**: 特定时间段内通信量激增
- **单向密集**: 一方发送大量邮件给另一方
- **群组通信**: 涉及多人的敏感话题讨论

## 关系网络指标

### 高风险关系特征
1. **高频通信** + **可疑关键词** = 高风险
2. **跨部门** + **非正式渠道** = 需关注
3. **上下级** + **保密要求** = 权力滥用可能

### 中间人识别
- 连接不同部门/层级的人员
- 频繁转发敏感信息的人员
- 在关键交易中起桥梁作用的人员

## 验证与校准

### 检测准确性评估
- 与已知腐败案件模式对比
- 人工抽样验证
- 误报率统计

### 误报控制
- 区分正常业务讨论与可疑通信
- 考虑上下文和行业惯例
- 结合多种指标综合判断

## 使用建议

1. **多语言支持**: 同时配置中英文关键词
2. **上下文分析**: 不仅检测关键词，还要分析通信模式
3. **时间序列**: 关注特定时间段内的异常行为
4. **关系网络**: 结合社交网络分析识别关键节点
5. **持续优化**: 根据验证结果调整检测模式
