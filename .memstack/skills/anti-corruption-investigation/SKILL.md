---
name: anti-corruption-investigation
description: Anti-corruption investigation toolkit for analyzing chat logs and communications to detect suspicious patterns, corruption indicators, and generate investigation reports. Supports Chinese and English chat logs in JSON/TXT formats. Includes automated keyword detection, behavior analysis, risk assessment, social network analysis, person profiling, intermediary detection, and evidence preservation workflows.
---

# Anti-Corruption Investigation v6.0

Advanced anti-corruption investigation system for analyzing chat logs and communications to detect suspicious patterns, corruption indicators, and relationship networks. Supports Chinese and English chat logs in JSON/TXT formats, handles million-scale datasets, and provides human-friendly relationship analysis with evidence-backed conclusions.

## What's New in v6.0

### Social Network Analysis (人物社会关系分析)

- **Person Profile Analysis (人物画像)**: Comprehensive profiling of each individual including role detection, activity patterns, and risk assessment
- **Intermediary Detection (中间人识别)**: Automatically identifies bridge persons who connect different corruption networks
- **Community Detection (群体检测)**: Discovers corruption groups and circles based on communication patterns
- **Influence Analysis (影响力分析)**: Ranks individuals by their network influence and centrality
- **Connection Path Analysis (连接路径分析)**: Finds shortest paths between high-risk individuals and identifies key bridges

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

### Social Network Analysis (NEW in v6.0)

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

# View influence ranking
for person in results['influence_ranking'][:10]:
    print(f"{person['name']}: Influence {person['influence_score']:.2f}")
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

# Social network analysis (NEW)
python anti_corruption.py social-network input.jsonl social_network.json --text-report social_report.txt

# Full analysis with all features
python anti_corruption.py full input.jsonl output_dir/
```

**Commands:**
- `analyze`: Basic corruption pattern detection
- `relationships`: Relationship network analysis
- `social-network`: Social network and person profile analysis (v6.0)
- `full`: Run all analyses

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

### Social Network Analysis Output (v6.0)

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
      },
      "first_seen": "2024-01-01T00:00:00",
      "last_seen": "2024-12-31T23:59:59",
      "active_period_days": 365
    }
  },
  "network_statistics": {
    "total_persons": 50,
    "total_relationships": 120,
    "network_density": 0.098,
    "avg_contacts_per_person": 4.8,
    "risk_distribution": {
      "high": 12,
      "medium": 18,
      "low": 20
    },
    "role_distribution": {
      "official": 15,
      "business": 20,
      "intermediary": 8,
      "family": 7
    }
  },
  "intermediaries": [
    {
      "name": "王五",
      "brokerage_score": 8,
      "contact_count": 15,
      "primary_role": "intermediary",
      "risk_level": "🔴 高风险",
      "evidence": [...]
    }
  ],
  "communities": [
    {
      "id": 0,
      "members": ["张三", "李四", "王五"],
      "member_count": 3,
      "average_risk_score": 7.2,
      "risk_level": "🔴 高风险",
      "dominant_patterns": {
        "financial_corruption": 45
      },
      "internal_connections": 6
    }
  ],
  "influence_ranking": [
    {
      "name": "张三",
      "influence_score": 8.5,
      "centrality": 0.85,
      "activity_score": 0.92,
      "contact_count": 12,
      "message_count": 300
    }
  ],
  "connection_paths": {
    "shortest_paths": [...],
    "key_bridges": [...],
    "isolated_persons": [...]
  },
  "key_relationships": [...]
}
```

## Version History

- **v6.0**: Added social network analysis, person profiling, intermediary detection, community detection, influence analysis
- **v5.0**: Refactored for clarity, human-friendly output, improved performance
- **v4.0**: Added relationship network analysis
- **v3.0**: Large-scale processing support
- **v2.0**: Semantic pattern matching
- **v1.0**: Initial release with keyword-based detection