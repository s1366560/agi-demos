---
name: anti-corruption-v2
description: |
  Advanced anti-corruption investigation system for analyzing chat logs and communications to detect suspicious patterns, corruption indicators, and relationship networks. Version 2 adds enhanced person relationship analysis capabilities including multi-hop relationship detection, relationship evolution tracking, power structure analysis, collusion ring detection, timeline analysis, and money flow tracing.
triggers:
  - 反腐调查
  - 反腐败分析
  - 人物关系分析
  - corruption investigation
  - analyze chat logs
  - relationship network
  - social network analysis
  - 多跳关系
  - 权力结构
  - 资金流向
category: investigation
tags:
  - anti-corruption
  - investigation
  - relationship-analysis
  - network-analysis
  - chinese
version: "2.0.0"
author: MemStack
---

# Anti-Corruption Investigation v2 (Enhanced)

## Overview

This enhanced version of the anti-corruption investigation tool provides comprehensive analysis of chat logs and communications to detect corruption patterns and build detailed relationship networks.

## Features

### Core Analysis (from v1)
- Pattern matching for corruption indicators
- Financial corruption detection
- Power abuse identification
- Secret meeting detection
- Collusion pattern recognition

### New in v2 - Enhanced Relationship Analysis

#### 1. Multi-hop Relationship Detection (多跳关系检测)
Find indirect connections between persons through 2-3 hops, revealing hidden relationships that are not directly visible.

#### 2. Relationship Evolution Tracking (关系演变追踪)
Track how relationships develop over time, identifying escalation patterns and changes in communication intensity.

#### 3. Power Structure Analysis (权力结构分析)
Identify hierarchy and power centers within the network, mapping official-business relationships and influence patterns.

#### 4. Collusion Ring Detection (串通团伙检测)
Find closed groups (triangles) of colluding individuals with high mutual suspicious activity.

#### 5. Timeline Analysis (时间线分析)
Analyze temporal patterns of suspicious activities, identifying peak activity periods and suspicious time patterns.

#### 6. Money Flow Tracing (资金流向追踪)
Track financial transaction patterns mentioned in communications, identifying key money handlers and transaction flows.

#### 7. Enhanced Person Profiles
Include network metrics:
- Centrality score (中心性分数)
- Betweenness score (桥梁性分数)
- Influence score (影响力分数)
- Risk score with multi-factor calculation

## Usage

### Command Line Interface

```bash
# Basic corruption pattern analysis
python anti_corruption_v2.py analyze data.jsonl report.json

# Enhanced social network analysis
python anti_corruption_v2.py social-network data.jsonl social_network.json --text-report report.txt

# Timeline analysis
python anti_corruption_v2.py timeline data.jsonl timeline.json --text-report timeline_report.txt

# Money flow analysis
python anti_corruption_v2.py money-flow data.jsonl money_flows.json --text-report money_report.txt

# Full comprehensive analysis
python anti_corruption_v2.py full data.jsonl output/
```

### Python API

```python
from anti_corruption_v2 import EnhancedSocialNetworkAnalyzer, TimelineAnalyzer, MoneyFlowAnalyzer

# Load messages
messages = [...]  # List of message dictionaries

# Social network analysis
analyzer = EnhancedSocialNetworkAnalyzer(messages)
results = analyzer.analyze()

# Access results
profiles = results['person_profiles']
intermediaries = results['intermediaries']
communities = results['communities']
collusion_rings = results['collusion_rings']
money_flows = results['money_flows']
```

## Input Format

### JSONL Format
```json
{"timestamp": "2024-01-15 14:30:00", "sender": "张三", "receiver": "李四", "content": "那笔钱已经准备好了"}
{"timestamp": "2024-01-15 14:32:00", "sender": "李四", "receiver": "张三", "content": "好的，老地方见"}
```

### TXT Format
```
[2024-01-15 14:30:00] 张三 -> 李四: 那笔钱已经准备好了
[2024-01-15 14:32:00] 李四 -> 张三: 好的，老地方见
```

## Output Structure

### Social Network Analysis

```json
{
  "person_profiles": {
    "张三": {
      "name": "张三",
      "message_count": 150,
      "contact_count": 8,
      "risk_score": 7.5,
      "risk_level": "🔴 高风险",
      "influence_score": 8.2,
      "centrality_score": 0.75,
      "betweenness_score": 0.45,
      "primary_role": "official",
      "corruption_patterns": {
        "financial_corruption": 12,
        "power_abuse": 8
      }
    }
  },
  "network_statistics": {
    "total_persons": 25,
    "total_relationships": 68,
    "network_density": 0.23,
    "risk_distribution": {"high": 5, "medium": 8, "low": 12}
  },
  "intermediaries": [...],
  "communities": [...],
  "influence_ranking": [...],
  "multi_hop_relationships": [...],
  "relationship_evolution": [...],
  "power_structure": {...},
  "collusion_rings": [...],
  "timeline_events": [...],
  "money_flows": [...]
}
```

## Detection Patterns

### Financial Corruption (资金往来)
- Direct: 转账、汇款、账户、资金、钱款、回扣、贿赂、好处费
- Semantic: 东西准备好了、表示一下、心意、感谢费

### Power Abuse (权力滥用)
- Direct: 特殊照顾、通融一下、开绿灯、违规操作、打招呼
- Semantic: 帮忙看看、关照一下、特事特办、按惯例

### Secret Meetings (秘密会面)
- Direct: 老地方、私下见面、秘密会面、不要告诉别人
- Semantic: 见面聊、当面谈、出来坐坐、不方便在这里说

### Collusion (串通勾结)
- Direct: 统一口径、对好供词、串通、删除记录、销毁证据
- Semantic: 保持一致、统一说法、删除吧、别留记录

### Money Laundering (洗钱)
- Direct: 洗白、过账、走账、开票、公户、私户

## Role Detection

- **official** (官员/公务员): 局长、处长、科长、领导、干部、审批
- **business** (商人/企业主): 老板、经理、董事长、公司、企业、项目
- **intermediary** (中介/掮客): 中介、介绍人、牵线、搭桥、有关系
- **family** (家属/亲戚): 老婆、丈夫、父亲、母亲、亲戚

## Risk Scoring

### Risk Levels
- **🔴 High Risk (高风险)**: Score >= 6
- **🟠 Medium Risk (中风险)**: Score >= 3
- **🟢 Low Risk (低风险)**: Score < 3

### Risk Factors
1. Suspicious message ratio (30%)
2. Pattern diversity (15%)
3. Late night activity (15%)
4. Network position - centrality (10%)
5. Network position - betweenness (15%)
6. Role combinations - official + business (15%)

## Example Workflow

```bash
# 1. Run full analysis
python anti_corruption_v2.py full example_data.jsonl ./output/

# 2. Check generated reports
cat output/social_network_report.txt
cat output/timeline_report.txt
cat output/money_flow_report.txt

# 3. Analyze specific aspects
python anti_corruption_v2.py social-network example_data.jsonl network.json --text-report network.txt
```

## Requirements

- Python 3.8+
- Standard library only (no external dependencies)

## Files

- `anti_corruption_v2.py` - Main analysis tool
- `SKILL.md` - This documentation
- `example_data.jsonl` - Sample data for testing

## Version History

- **v2.0.0** (Current): Enhanced relationship analysis with multi-hop detection, evolution tracking, power structure analysis, collusion ring detection, timeline analysis, money flow tracing
- **v1.0.0**: Basic corruption pattern detection
