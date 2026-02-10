---
name: anti-corruption-investigation
description: Advanced anti-corruption investigation system for analyzing chat logs and communications to detect suspicious patterns, corruption indicators, and relationship networks. Supports Chinese and English chat logs in JSON/TXT formats, handles million-scale datasets, and provides human-friendly relationship analysis with evidence-backed conclusions.
version: "7.0"
author: Claude Code
---

# Anti-Corruption Investigation v7.0

## What's New in v7.0

### Multi-Language Pattern Detection

- **Chinese Patterns**: Financial corruption, power abuse, secret meetings, collusion
- **English Patterns**: Evidence destruction, insider trading, pressure manipulation, enterprise fraud
- **Universal Enterprise Fraud Detection**: SPE, accounting manipulation, financial metrics manipulation
- **Semantic Pattern Matching**: Detects implicit expressions and euphemisms

### Social Network Analysis

- **Person Profile Analysis**: Comprehensive profiling including role detection, activity patterns, and risk assessment
- **Intermediary Detection**: Automatically identifies bridge persons connecting corruption networks
- **Community Detection**: Discovers corruption groups based on communication patterns
- **Influence Analysis**: Ranks individuals by network influence and centrality
- **Connection Path Analysis**: Finds shortest paths between high-risk individuals

### Validation Framework

- **Pattern Validation**: Validates detection accuracy against known corruption patterns
- **Report Validation**: Ensures report completeness and quality
- **False Positive Control**: Estimates and controls false positive rates
- **Continuous Improvement**: Generates recommendations for pattern enhancement

## When to Use This Skill

Use when analyzing chat logs, messages, or communications for:
- **Corruption detection**: Financial corruption, power abuse, secret meetings, collusion
- **Relationship analysis**: Identifying key players, corruption networks, intermediaries
- **Social network analysis**: Understanding person profiles, influence, and group structures
- **Large-scale analysis**: Processing 100K+ messages efficiently
- **Evidence gathering**: Extracting specific evidence for relationships
- **Risk assessment**: Evaluating corruption risk levels

## Quick Start

### Basic Analysis

```python
from anti_corruption import ChatAnalyzer

# Analyze chat data
messages = [...]  # Load your messages
analyzer = ChatAnalyzer(messages)
results = analyzer.analyze()

# View results
print(f"Risk Level: {results['risk_level']}")
print(f"Suspicious Messages: {len(results['suspicious_messages'])}")
```

### Multi-Language Pattern Detection

```python
from multi_lang_patterns import analyze_text, analyze_email

# Analyze text in any language
result = analyze_text("We need to delete these documents before audit")
print(f"Risk Score: {result['risk_score']}")
print(f"Categories: {result['categories']}")

# Analyze email with enterprise fraud detection
email_data = {
    'sender': 'john@company.com',
    'receiver': 'jane@company.com',
    'subject': 'Q4 Results',
    'content': 'We need to hit the target number.',
    'title': 'CFO'
}
result = analyze_email(email_data)
print(f"Risk Level: {result['risk_level']}")
```

### Relationship Analysis

```python
from anti_corruption import RelationshipAnalyzer

# Analyze relationships
analyzer = RelationshipAnalyzer(messages)
relationships = analyzer.analyze()

# View top relationships
for rel in relationships['top_relationships'][:10]:
    print(f"{rel['person_a']} ↔ {rel['person_b']}")
    print(f"  Type: {rel['relationship_type']}")
    print(f"  Evidence: {len(rel['evidence'])} items")
    print(f"  Risk: {rel['risk_level']}")
```

### Social Network Analysis

```python
from anti_corruption import SocialNetworkAnalyzer

# Analyze social network
analyzer = SocialNetworkAnalyzer(messages)
results = analyzer.analyze()

# View person profiles
for name, profile in results['person_profiles'].items():
    print(f"{name}: {profile['primary_role']} - {profile['risk_level']}")

# View intermediaries
for inter in results['intermediaries'][:5]:
    print(f"Intermediary: {inter['name']} (Score: {inter['brokerage_score']})")

# View communities
for comm in results['communities']:
    print(f"Community: {', '.join(comm['members'][:5])}")
```

### Validation

```python
from case_validator import validate_analysis, generate_validation_report

# Validate analysis results
validation = validate_analysis(analysis_results)
print(f"Detection Accuracy: {validation.detection_accuracy:.1%}")
print(f"False Positive Rate: {validation.false_positive_rate:.1%}")

# Generate validation report
report = generate_validation_report(validation, 'validation_report.txt')
```

## Core Scripts

### anti_corruption.py

Unified analysis tool with all features.

**Usage:**
```bash
# Basic corruption analysis
python anti_corruption.py analyze input.jsonl report.json

# Relationship analysis
python anti_corruption.py relationships input.jsonl relationships.json --text-report report.txt

# Social network analysis
python anti_corruption.py social-network input.jsonl social_network.json --text-report social_report.txt

# Full analysis with all features
python anti_corruption.py full input.jsonl output_dir/
```

**Commands:**
- `analyze`: Basic corruption pattern detection
- `relationships`: Relationship network analysis
- `social-network`: Social network and person profile analysis
- `full`: Run all analyses

### multi_lang_patterns.py

Multi-language pattern detection module.

**Features:**
- Automatic language detection (Chinese, English, Mixed)
- Direct pattern matching for corruption indicators
- Semantic pattern matching for implicit expressions
- Enterprise fraud specific patterns (SPE, accounting manipulation)
- Risk scoring based on pattern matches

**Usage:**
```python
from multi_lang_patterns import MultiLangPatternMatcher, EnterpriseFraudDetector

# Pattern matching
matcher = MultiLangPatternMatcher()
matches = matcher.match_patterns(text)
summary = matcher.get_summary(matches)

# Enterprise fraud detection
detector = EnterpriseFraudDetector()
result = detector.analyze_email(email_data)
```

### case_validator.py

Validation framework for analysis results.

**Features:**
- Pattern detection validation
- False positive rate estimation
- Report completeness checking
- Improvement recommendations

**Usage:**
```python
from case_validator import PatternValidator, ReportValidator

# Validate analysis
validation = PatternValidator.validate_analysis(results)

# Validate report
report_check = ReportValidator.validate_report(report)
```

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

### Social Network Analysis Output

```json
{
  "person_profiles": {
    "张三": {
      "name": "张三",
      "message_count": 150,
      "contact_count": 8,
      "contacts": ["李四", "王五", ...],
      "primary_role": "official",
      "detected_roles": ["official", "business"],
      "suspicious_message_count": 25,
      "corruption_patterns": {
        "financial_corruption": 15,
        "power_abuse": 10
      },
      "risk_score": 7.5,
      "risk_level": "🔴 高风险",
      "activity_anomaly": {
        "anomaly_score": 6.2,
        "late_night_ratio": 0.31,
        "peak_hours": [22, 23, 0]
      }
    }
  },
  "intermediaries": [
    {
      "name": "王五",
      "brokerage_score": 8,
      "contact_count": 15,
      "primary_role": "intermediary",
      "risk_level": "🔴 高风险"
    }
  ],
  "communities": [
    {
      "id": 0,
      "members": ["张三", "李四", "王五"],
      "member_count": 3,
      "average_risk_score": 7.2,
      "risk_level": "🔴 高风险"
    }
  ]
}
```

## Pattern Categories

### Financial Corruption
- Chinese: 转账, 汇款, 回扣, 贿赂, 好处费
- English: kickback, bribe, hidden payment, secret fee

### Evidence Destruction
- Chinese: 删除, 销毁, 清理, 不留痕迹
- English: delete, destroy, shred, clean up, off the record

### Insider Trading
- English: stock option, insider information, before announcement

### Enterprise Fraud
- SPE, off-balance sheet, mark-to-market
- Aggressive accounting, earnings management
- EBITDA manipulation, pro forma adjustments

### Pressure Manipulation
- English: pressure, hit the target, make it happen
- Adjust numbers, bridge the gap, find a way

## Version History

- **v7.0**: Added multi-language pattern detection, enterprise fraud patterns, validation framework
- **v6.0**: Added social network analysis, person profiling, intermediary detection
- **v5.0**: Refactored for clarity, human-friendly output, improved performance
- **v4.0**: Added relationship network analysis
- **v3.0**: Large-scale processing support
- **v2.0**: Semantic pattern matching
- **v1.0**: Initial release with keyword-based detection
