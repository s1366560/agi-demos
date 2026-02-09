---
name: anti-corruption-investigation
description: Anti-corruption investigation toolkit for analyzing chat logs and communications to detect suspicious patterns, corruption indicators, and generate investigation reports. Supports Chinese and English chat logs in JSON/TXT formats. Includes automated keyword detection, behavior analysis, risk assessment, and evidence preservation workflows.
---

# Anti-Corruption Investigation

## Overview

Comprehensive toolkit for analyzing chat logs and communications to detect potential corruption, bribery, embezzlement, and abuse of power. Provides automated analysis of suspicious patterns, risk assessment, and investigation report generation.

## Quick Start

### Basic Workflow

```bash
# 1. Generate test data (optional)
python scripts/generate_test_data.py

# 2. Analyze chat records
python scripts/analyze_chat.py <chat_file> [output_report]

# Example:
python scripts/analyze_chat.py chat_data.json investigation_report.txt
```

### Supported Input Formats

**JSON Format:**
```json
[
  {
    "timestamp": "2024-01-15T14:30:00",
    "sender": "张三",
    "content": "那笔钱准备好了吗？"
  }
]
```

**TXT Format:**
```
[2024-01-15 14:30:00] 张三: 那笔钱准备好了吗？
2024-01-15 14:31:00 李四: 已经准备好了
```

## Core Capabilities

### 1. Suspicious Pattern Detection

Automatically detects multiple categories of suspicious behavior:

**Money-Related Indicators:**
- Large amounts, transfers, cash transactions
- Keywords: 回扣, 佣金, 好处费, 贿赂, 转账, 汇款

**Secret Meeting Patterns:**
- Private meetings, confidentiality requests
- Keywords: 私下, 单独, 密谈, 保密, 不要告诉

**Power Abuse Indicators:**
- Special treatment requests, favoritism
- Keywords: 帮办, 安排, 通融, 破例, 特殊, 关系

**Evidence Concealment:**
- Attempts to destroy evidence
- Keywords: 删除, 销毁, 清除, 不留痕迹

### 2. Communication Pattern Analysis

Analyzes:
- Message frequency by participant
- Active time periods (late night, weekends, work hours)
- Response time patterns
- Suspicious communication intervals

### 3. Risk Assessment

**Risk Scoring (0-8):**
- Suspicious keyword frequency: 0-3 points
- High-risk users: +2 points
- Evidence destruction attempts: +3 points

**Risk Levels:**
- 🟢 **Low Risk**: 0-2 points
- 🟡 **Medium Risk**: 3-5 points
- 🔴 **High Risk**: 6-8 points

### 4. Automated Report Generation

Generates comprehensive investigation reports including:
- Executive summary with risk level
- Keyword analysis by category
- Communication pattern statistics
- Anomalous behavior detection
- High-risk user identification
- Actionable recommendations

## Investigation Workflow

### Phase 1: Data Collection

1. **Gather chat logs** from messaging platforms
2. **Export in supported format** (JSON/TXT)
3. **Verify data integrity** (check for missing messages)
4. **Backup original data** before analysis

### Phase 2: Automated Analysis

```bash
# Run comprehensive analysis
python scripts/analyze_chat.py chat_data.json report.txt
```

The analysis automatically:
- Extracts all participants
- Detects suspicious keywords across 5 categories
- Analyzes communication patterns
- Identifies high-risk individuals
- Calculates risk scores

### Phase 3: Manual Review

Review the generated report to:
1. **Verify false positives** (legitimate business discussions)
2. **Context analysis** (consider industry-specific terminology)
3. **Cross-reference** with other evidence sources
4. **Identify patterns** not caught by automated analysis

### Phase 4: Evidence Preservation

For high-risk cases:
- **Screenshot** key messages with metadata
- **Export** complete chat logs in original format
- **Document** analysis methodology
- **Chain of custody** maintenance
- **Witness statements** if applicable

### Phase 5: Report Generation

Use the included template:
```bash
# Reference the template
cat assets/report_template.md
```

Customize with:
- Case-specific information
- Investigation findings
- Evidence descriptions
- Recommended actions
- Legal references

## Detailed Analysis Features

### Keyword Detection System

The analyzer uses regex patterns to detect:

**Financial Corruption:**
```python
patterns = [
    r'\d+[万千百]*[元美金块]',  # Amounts
    r'转账|汇款|现金|红包',      # Transfers
    r'回扣|佣金|好处费',          # Kickbacks
    r'贿赂|贪|腐败'              # Direct terms
]
```

**Behavioral Red Flags:**
```python
patterns = [
    r'私下|单独|密谈|保密',      # Secret meetings
    r'不要告诉|别让.*知道',      # Confidentiality
    r'删除记录|清空聊天',        # Destroy evidence
    r'加密|暗号'                  # Encryption
]
```

### Risk Calculation Algorithm

```python
risk_score = 0

# Keyword frequency
if suspicious_matches > 50: risk_score += 3
elif suspicious_matches > 20: risk_score += 2
elif suspicious_matches > 5: risk_score += 1

# High-risk users
if high_risk_users_detected: risk_score += 2

# Evidence destruction
if destruction_attempts: risk_score += 3
```

### Anomaly Detection

Identifies:
- **Unusual timing**: Late-night/early-morning messages
- **High-frequency users**: Disproportionate message volume
- **Evidence tampering**: Explicit deletion requests
- **Code words**: Repeated use of unusual phrases

## Usage Examples

### Example 1: Quick Risk Screening

```bash
# Analyze a single chat file
python scripts/analyze_chat.py suspect_chat.json screening_report.txt
```

**Output**: Quick risk assessment with:
- Overall risk level
- Top suspicious messages
- High-risk participants
- Recommended next steps

### Example 2: Comprehensive Investigation

```bash
# Analyze multiple chat files
for file in chats/*.json; do
    python scripts/analyze_chat.py "$file" "reports/$(basename $file .json)_report.txt"
done
```

**Output**: Individual reports for each conversation thread

### Example 3: Test and Validation

```bash
# Generate test data with known patterns
python scripts/generate_test_data.py

# Analyze to verify detection accuracy
python scripts/analyze_chat.py test_chat.json validation_report.txt
```

## Resources

### scripts/

**analyze_chat.py** (Main Tool)
- Core analysis engine
- Multi-format input support
- Automated risk scoring
- Report generation

**generate_test_data.py** (Testing)
- Creates sample chat data
- Tests detection patterns
- Validates analysis accuracy

### references/

**investigation_guide.md**
- Complete investigation workflow
- Legal references and standards
- Risk assessment criteria
- Best practices and guidelines

### assets/

**report_template.md**
- Professional report template
- Standardized format
- Section-by-section guidance
- Customizable placeholders

## Best Practices

### Data Privacy
- ✅ Comply with data protection laws
- ✅ Obtain proper authorization before analysis
- ✅ Store data securely
- ✅ Limit access to authorized personnel
- ❌ Never share sensitive data publicly

### Evidence Integrity
- ✅ Maintain original data unchanged
- ✅ Document all analysis steps
- ✅ Use hash verification for integrity
- ✅ Preserve metadata and timestamps
- ❌ Never modify source data

### Analysis Accuracy
- ✅ Cross-reference with other evidence
- ✅ Consider context and industry norms
- ✅ Verify automated findings manually
- ✅ Document false positives
- ❌ Don't rely solely on automated analysis

### Legal Compliance
- ✅ Follow local investigation procedures
- ✅ Consult legal counsel when needed
- ✅ Respect due process rights
- ✅ Maintain chain of custody
- ❌ Don't exceed authorized scope

## Limitations

1. **Language Support**: Optimized for Chinese; English detection is basic
2. **Context Understanding**: Cannot distinguish legitimate business discussions from actual corruption
3. **Encryption**: Cannot analyze encrypted messages
4. **Deleted Messages**: Cannot recover deleted content
5. **Voice/Video**: Only analyzes text-based communications

## Integration with Other Tools

### Complementary Analysis
- **Financial forensics**: Cross-reference with transaction records
- **Network analysis**: Map relationship networks
- **Timeline tools**: Reconstruct event sequences
- **Document analysis**: Correlate with emails, contracts

### Export Formats
Analysis results can be exported as:
- Plain text reports (.txt)
- JSON data for further processing
- CSV for spreadsheet analysis
- PDF for formal documentation

## Troubleshooting

### Common Issues

**Issue**: "File not found" error
```bash
# Solution: Check file path and extension
ls -la chat_data.json
python scripts/analyze_chat.py ./chat_data.json
```

**Issue**: "No messages loaded"
```bash
# Solution: Verify file format
cat chat_data.json | head -20  # Check JSON structure
# or
head -10 chat_data.txt         # Check TXT format
```

**Issue**: Low detection accuracy
```bash
# Solution: Customize patterns in analyze_chat.py
# Edit suspicious_patterns dictionary
```

## Advanced Usage

### Custom Pattern Detection

Edit `analyze_chat.py` to add industry-specific patterns:

```python
def _load_patterns(self):
    return {
        'custom_category': [
            r'your_custom_regex_pattern',
            r'another_pattern'
        ],
        # ... existing patterns
    }
```

### Batch Processing

```bash
#!/bin/bash
# Process multiple files
for file in data/*.json; do
    output="reports/$(basename $file .json)_report.txt"
    python scripts/analyze_chat.py "$file" "$output"
done
```

### Integration with Python Scripts

```python
from scripts.analyze_chat import ChatAnalyzer

# Create analyzer
analyzer = ChatAnalyzer("chat_data.json")

# Load and analyze
if analyzer.load_chat_data():
    suspicious = analyzer.analyze_suspicious_keywords()
    anomalies = analyzer.detect_anomalous_behavior()
    
    # Custom processing
    print(f"Found {suspicious['total_matches']} suspicious matches")
```

## Support and Contributing

For issues or improvements:
1. Document the specific use case
2. Provide sample data (sanitized)
3. Describe expected vs actual behavior
4. Suggest enhancement ideas
