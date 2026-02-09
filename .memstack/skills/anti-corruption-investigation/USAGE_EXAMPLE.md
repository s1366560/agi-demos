# 反腐调查技能使用示例

## 技能概述

✅ **技能名称**: anti-corruption-investigation
✅ **技能文件**: `/workspace/.skills/anti-corruption-investigation.skill`
✅ **功能**: 根据聊天记录执行反腐调查分析

## 核心功能

### 1. 自动化可疑模式检测
- 资金相关词汇（转账、回扣、贿赂等）
- 秘密会面约定（私下、保密、密谈等）
- 权力滥用行为（特殊照顾、违规办事等）
- 证据销毁尝试（删除、清除记录等）

### 2. 通信模式分析
- 消息频率统计
- 活跃时间段分析
- 响应时间模式
- 异常间隔检测

### 3. 风险评估系统
- 综合风险评分（0-8分）
- 三级风险等级（低/中/高）
- 高风险用户识别
- 处理建议生成

### 4. 自动报告生成
- 完整调查报告
- 证据清单
- 法律依据引用
- 处理建议

## 使用方法

### 快速开始

```bash
# 1. 加载技能
# （技能已在系统中注册）

# 2. 准备聊天记录
# 支持JSON或TXT格式

# 3. 运行分析
cd /workspace/.skills/anti-corruption-investigation
python scripts/analyze_chat.py your_chat.json report.txt

# 4. 查看报告
cat report.txt
```

### 测试示例

```bash
# 生成测试数据
python scripts/generate_test_data.py

# 分析测试数据
python scripts/analyze_chat.py test_chat.json investigation_report.txt

# 查看结果
cat investigation_report.txt
```

## 输入格式

### JSON格式（推荐）
```json
[
  {
    "timestamp": "2024-01-15T14:30:00",
    "sender": "张三",
    "content": "那笔钱准备好了吗？"
  },
  {
    "timestamp": "2024-01-15T14:31:00",
    "sender": "李四",
    "content": "已经准备好了"
  }
]
```

### TXT格式
```
[2024-01-15 14:30:00] 张三: 那笔钱准备好了吗？
[2024-01-15 14:31:00] 李四: 已经准备好了
```

## 输出示例

### 风险评估
```
🎯 综合风险等级: 🟡 中风险
📈 风险评分: 4/8
```

### 可疑内容分析
```
📈 可疑内容匹配总数: 17

📋 分类统计:
  【money_keywords】
    - 李四: 4 次
    - 王五: 2 次
  【evidence_concealment】
    - 李四: 3 次
```

### 异常行为检测
```
🗑️ 销毁证据尝试 (3 次):
  - [2026-01-13T13:00:31] 李四
    记得删除聊天记录...
```

## 技能文件结构

```
anti-corruption-investigation/
├── SKILL.md                              # 技能主文档
├── scripts/
│   ├── analyze_chat.py                   # 核心分析工具
│   └── generate_test_data.py             # 测试数据生成
├── references/
│   └── investigation_guide.md            # 调查流程指南
└── assets/
    └── report_template.md                # 报告模板
```

## 实际应用场景

### 1. 企业内部调查
- 员工违规行为调查
- 商业贿赂检测
- 利益冲突识别

### 2. 合规审计
- 反洗钱监测
- 内控合规检查
- 风险预警

### 3. 法律取证
- 证据收集整理
- 模式分析报告
- 专家证言支持

## 注意事项

⚠️ **法律合规**: 使用前确保获得合法授权
⚠️ **数据隐私**: 严格遵守数据保护法规
⚠️ **证据保全**: 保持原始数据完整性
⚠️ **结果验证**: 自动分析需人工复核

## 技能特点

✨ **全自动化**: 一键生成完整报告
✨ **多语言支持**: 优化中文，支持英文
✨ **灵活输入**: 支持多种聊天记录格式
✨ **专业输出**: 符合调查报告标准
✨ **可扩展性**: 可自定义检测模式

## 技能打包文件

技能已打包为: `/workspace/.skills/anti-corruption-investigation.skill` (15KB)

可以分发和安装到其他系统使用。
