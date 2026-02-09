---
name: anti-corruption-investigation
description: Anti-corruption investigation toolkit for analyzing chat logs and communications to detect suspicious patterns, corruption indicators, and generate investigation reports. Supports Chinese and English chat logs in JSON/TXT formats. Includes automated keyword detection, behavior analysis, risk assessment, and evidence preservation workflows.
---

# Anti-Corruption Investigation v5.0

Advanced anti-corruption investigation system for analyzing chat logs and communications to detect suspicious patterns, corruption indicators, and relationship networks. Supports Chinese and English chat logs in JSON/TXT formats, handles million-scale datasets, and provides human-friendly relationship analysis with evidence-backed conclusions.

## When to Use This Skill

Use when analyzing chat logs, messages, or communications for:
- **Corruption detection**: Financial corruption, power abuse, secret meetings, collusion
- **Relationship analysis**: Identifying key players, corruption networks, intermediaries
- **Large-scale analysis**: Processing 100K+ messages efficiently
- **Evidence gathering**: Extracting specific evidence for relationships
- **Risk assessment**: Evaluating corruption risk levels

## Quick Start

### Basic Analysis

```python
from anti_corruption_v5 import ChatAnalyzer

# Analyze chat data
analyzer = ChatAnalyzer()
results = analyzer.analyze('data/messages.jsonl')

# View results
print(f"Risk Level: {results['risk_level']}")
print(f"Suspicious Messages: {len(results['suspicious_messages'])}")
```

### Relationship Analysis

```python
from anti_corruption_v5 import RelationshipAnalyzer

# Analyze relationships
analyzer = RelationshipAnalyzer()
relationships = analyzer.analyze_relationships('data/messages.jsonl')

# View top relationships
for rel in relationships['top_relationships'][:10]:
    print(f"{rel['person_a']} ↔ {rel['person_b']}")
    print(f"  Type: {rel['relationship_type']}")
    print(f"  Evidence: {len(rel['evidence'])} items")
    print(f"  Risk: {rel['risk_level']}")
```

## Core Scripts

### `analyze_chat.py`

Main analysis engine for detecting corruption patterns.

**Usage:**
```bash
python scripts/analyze_chat.py <input_file> <output_file>
```

**Features:**
- Semantic pattern matching (not just keywords)
- Time-based analysis (late night, weekends)
- Behavioral anomaly detection
- Evidence preservation

**Output:**
- Suspicious messages with evidence
- Risk assessment (0-10 scale)
- Key player identification
- Analysis statistics

### `relationship_analyzer.py`

Build relationship networks from chat data.

**Usage:**
```bash
python scripts/relationship_analyzer.py <input_file> <output_file>
```

**Features:**
- Relationship strength calculation
- Evidence extraction per relationship
- Risk level assessment
- Human-friendly output format

**Output:**
```json
{
  "relationships": [
    {
      "person_a": "张三",
      "person_b": "李四",
      "relationship_type": ["频繁联系", "资金往来"],
      "strength": 0.85,
      "evidence": [
        {
          "timestamp": "2024-01-15T14:30:00",
          "sender": "张三",
          "content": "那笔钱准备好了吗？"
        }
      ],
      "risk_level": "高风险"
    }
  ]
}
```

### `scalable_analyzer.py`

Process large-scale datasets (100K+ messages).

**Usage:**
```bash
python scripts/scalable_analyzer.py <input_file> <output_file> [--batch-size 10000] [--workers 8]
```

**Features:**
- Stream processing (low memory)
- Parallel computation (fast)
- Incremental analysis
- Progress tracking

**Performance:**
- Speed: 60K+ messages/second
- Memory: <2GB for 1M messages
- Scalability: Tested up to 10M messages

## Data Format

### Input Format (JSONL)

```json
{"timestamp": "2024-01-15T14:30:00", "sender": "张三", "receiver": "李四", "content": "那笔钱准备好了吗？"}
{"timestamp": "2024-01-15T14:31:00", "sender": "李四", "receiver": "张三", "content": "已经准备好了"}
```

### Input Format (TXT)

```
[2024-01-15 14:30:00] 张三 -> 李四: 那笔钱准备好了吗？
[2024-01-15 14:31:00] 李四 -> 张三: 已经准备好了
```

## Output Format

### Human-Friendly Relationship Report

```
=== 关系分析报告 ===

Top 关键关系:

1. 冯供应商 ↔ 陈总
   关系类型: 频繁联系, 资金往来, 权力滥用
   关系强度: 🔴 非常强 (1.00)
   联系次数: 390次 | 异常时间: 3次
   风险等级: 🔴 高风险 - 需要重点关注
   
   关键证据:
   • [2024-01-01 00:00:00] 冯供应商 -> 陈总: 不留痕迹...
   • [2024-01-02 08:15:00] 陈总 -> 冯供应商: 大家统一一下口径...
   • [2024-01-03 22:30:00] 冯供应商 -> 陈总: 见面细说...
```

## Advanced Features

### Semantic Pattern Matching

Uses embedding-based similarity to detect隐晦表达:

- "老地方" → 秘密会面
- "那个东西" → 资金/贿赂
- "按老规矩" → 权力滥用
- "统一口径" → 串通勾结

### Time-Based Analysis

Detects anomalies in communication patterns:

- Late night messages (22:00-06:00)
- Weekend/holiday activity
- Burst communication patterns
- Timeline correlations

### Relationship Network Analysis

Calculates network metrics:

- **Degree Centrality**: Who has most connections
- **Betweenness Centrality**: Who are key intermediaries
- **PageRank**: Who are most influential
- **Community Detection**: Identifies corruption groups

### Evidence Preservation

Maintains chain of custody for investigations:

- Original message content
- Timestamps and metadata
- Sender/receiver information
- Pattern classification

## Best Practices

### 1. Data Preparation

- Ensure consistent timestamp format
- Normalize sender/receiver names
- Handle missing fields gracefully
- Remove duplicates before analysis

### 2. Analysis Workflow

```bash
# Step 1: Basic analysis
python scripts/analyze_chat.py input.jsonl basic_report.json

# Step 2: Relationship analysis
python scripts/relationship_analyzer.py input.jsonl relationships.json

# Step 3: Large-scale processing (if needed)
python scripts/scalable_analyzer.py input.jsonl full_report.json --batch-size 10000
```

### 3. Result Interpretation

- **High risk (6-10)**: Prioritize for investigation
- **Medium risk (3-5)**: Monitor closely
- **Low risk (0-2)**: Normal surveillance
- **Whistleblower detection**: Cross-reference with context

### 4. Validation

- Cross-check with other evidence sources
- Verify relationship context
- Consider legitimate explanations
- Human review required for final decisions

## Performance Optimization

### For Large Datasets (1M+ messages)

```bash
# Use batch processing
python scripts/scalable_analyzer.py large_data.jsonl report.json \
    --batch-size 10000 \
    --workers 8 \
    --enable-cache
```

### Memory Optimization

- Use JSONL format (not JSON array)
- Process in batches
- Enable caching for repeated analysis
- Use incremental mode for new data

### Speed Optimization

- Increase workers for CPU-bound tasks
- Use SSD for I/O operations
- Disable unused features (e.g., visualization)
- Pre-filter data by date range

## Limitations and Considerations

### False Positives

- Legitimate business relationships may be flagged
- Context matters for interpretation
- Cultural differences in communication
- Industry-specific patterns

### False Negatives

- Highly coded language may be missed
- External communication channels not covered
- Deleted messages not analyzed
- Voice/video messages not supported

### Ethical Considerations

- Ensure legal authorization for analysis
- Protect privacy of innocent parties
- Follow data protection regulations
- Maintain chain of custody for evidence

## Troubleshooting

### Common Issues

**Issue**: "Memory error with large files"
- **Solution**: Use `scalable_analyzer.py` with smaller batch size

**Issue**: "No suspicious patterns detected"
- **Solution**: Check data quality, adjust sensitivity thresholds

**Issue**: "Too many false positives"
- **Solution**: Increase evidence threshold, add whitelist

**Issue**: "Relationship strength seems wrong"
- **Solution**: Verify time period, check for multiple channels

## Dependencies

```
networkx>=3.0
numpy>=1.21.0
pandas>=1.3.0
plotly>=5.0.0
python-louvain>=0.16
scipy>=1.7.0
```

Install with:
```bash
pip install -r requirements.txt
```

## Version History

- **v5.0**: Refactored for clarity, human-friendly output, improved performance
- **v4.0**: Added relationship network analysis
- **v3.0**: Large-scale processing support
- **v2.0**: Semantic pattern matching
- **v1.0**: Initial release with keyword-based detection

## Support

For issues or questions:
- Check examples in `examples/` directory
- Review error messages carefully
- Validate data format matches specifications
- Ensure sufficient system resources for large datasets
