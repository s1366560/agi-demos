---
name: corruption-check
description: 通过NLP技术分析聊天记录，识别腐败线索和社会关系网络。支持检测资金往来、信息泄露、权力滥用、串通勾结等腐败模式，构建人物关系图谱。
version: 2.0.0
author: Claude
---

# corruption-check 技能

## 使用方法

### 命令行
```bash
python corruption_analyzer.py <input_file> [output_dir]
```

### Python API
```python
from corruption_analyzer import CorruptionAnalyzerV2

analyzer = CorruptionAnalyzerV2(messages)
report = analyzer.generate_report()
```

## 输入格式

JSON/JSONL 格式，每条消息包含：
- `sender`: 发送人标识
- `receiver`: 接收人标识
- `timestamp`: 时间戳
- `content`: 消息内容

## 输出内容

1. **人物风险画像**: 风险评分、角色识别、行为记录、资金流水
2. **社会关系分析**: 关系风险评分、资金流向、信息泄露方向
3. **腐败网络检测**: 星型网络、共谋网络、中间人识别
4. **时间线分析**: 腐败事件序列、关键节点、证据链

## 腐败检测模式

| 模式 | 关键词 | 权重 |
|------|--------|------|
| 资金往来 | 回扣、转账、好处费 | 3 |
| 信息泄露 | 底价、标底、内幕 | 3 |
| 权力滥用 | 照顾、帮忙、操作 | 2 |
| 秘密会面 | 见面、私下、面谈 | 2 |
| 串通勾结 | 统一口径、串供 | 4 |

## 风险等级

- 🔴 高风险 (70-100分): 核心腐败人员
- 🟠 中风险 (40-69分): 有关联或轻微参与
- 🟢 低风险 (0-39分): 边缘人物
