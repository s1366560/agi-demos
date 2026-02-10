# 反腐调查分析 API 参考

## 核心类

### MessageParser

消息解析器，支持多种聊天记录格式。

#### 方法

##### `parse_jsonl(file_path: str) -> List[Dict]`
解析 JSONL 格式的聊天记录。

```python
messages = MessageParser.parse_jsonl("chat.jsonl")
# 返回: [{"timestamp": "...", "sender": "...", "receiver": "...", "content": "..."}, ...]
```

##### `parse_txt(file_path: str) -> List[Dict]`
解析 TXT 格式的聊天记录。

格式要求：
```
[2024-01-01 10:00:00] 张三 -> 李四: 消息内容
```

```python
messages = MessageParser.parse_txt("chat.txt")
```

---

### PatternMatcher

腐败模式匹配器，使用正则和语义模式识别可疑内容。

#### 类属性

##### `DIRECT_PATTERNS: Dict[str, List[str]]`
直接匹配模式（正则表达式）。

```python
{
    'financial_corruption': [r'转账|汇款|...', ...],
    'power_abuse': [r'特殊照顾|...', ...],
    'secret_meeting': [r'老地方|...', ...],
    'collusion': [r'统一口径|...', ...]
}
```

##### `SEMANTIC_PATTERNS: Dict[str, List[str]]`
语义匹配模式（关键词）。

```python
{
    'financial_corruption': ['东西准备好了吗', '那个东西', ...],
    'power_abuse': ['帮忙看看', '关照一下', ...],
    ...
}
```

##### `ROLE_PATTERNS: Dict[str, List[str]]`
角色识别模式。

```python
{
    'official': [r'局长|处长|...', ...],
    'business': [r'老板|经理|...', ...],
    'intermediary': [r'中介|代理|...', ...],
    'family': [r'老婆|丈夫|...', ...]
}
```

#### 类方法

##### `match_patterns(content: str) -> List[str]`
匹配内容中的腐败模式。

```python
patterns = PatternMatcher.match_patterns("转账的事情已经办好了")
# 返回: ['financial_corruption']
```

##### `detect_roles(content: str) -> List[str]`
检测内容中提到的角色类型。

```python
roles = PatternMatcher.detect_roles("王局长说可以通融一下")
# 返回: ['official']
```

---

### TimeAnalyzer

时间异常分析器。

#### 类方法

##### `is_late_night(timestamp: str) -> bool`
检查是否为深夜时间（22:00-06:00）。

```python
is_late = TimeAnalyzer.is_late_night("2024-01-01 23:30:00")
# 返回: True
```

##### `is_weekend(timestamp: str) -> bool`
检查是否为周末。

```python
is_weekend = TimeAnalyzer.is_weekend("2024-01-06 10:00:00")  # 周六
# 返回: True
```

##### `parse_timestamp(timestamp: str) -> datetime`
解析时间戳字符串为 datetime 对象。

```python
dt = TimeAnalyzer.parse_timestamp("2024-01-01T10:00:00Z")
# 返回: datetime 对象
```

---

### ChatAnalyzer

聊天记录分析器，执行腐败模式检测和风险评估。

#### 构造函数

##### `__init__(messages: List[Dict[str, Any]])`

```python
analyzer = ChatAnalyzer(messages)
```

#### 方法

##### `analyze() -> Dict[str, Any]`
执行完整分析。

```python
results = analyzer.analyze()
```

返回结果结构：
```python
{
    "total_messages": 10000,          # 总消息数
    "suspicious_count": 150,          # 可疑消息数
    "suspicious_rate": 0.015,         # 可疑率
    "pattern_counts": {               # 各类模式数量
        "financial_corruption": 45,
        "power_abuse": 32,
        "secret_meeting": 28,
        "collusion": 45
    },
    "time_anomalies": {               # 时间异常统计
        "late_night": 20,
        "weekend": 15
    },
    "risk_score": 6.5,                # 风险评分 (0-10)
    "risk_level": "🔴 高风险 (6.5/10)", # 风险等级
    "suspicious_messages": [...],     # 可疑消息列表
    "key_players": [...]              # 关键人物列表
}
```

---

### RelationshipAnalyzer

关系分析器，分析人员之间的关系网络。

#### 构造函数

##### `__init__(messages: List[Dict[str, Any]])`

```python
analyzer = RelationshipAnalyzer(messages)
```

#### 方法

##### `analyze() -> Dict[str, Any]`
执行关系分析。

```python
results = analyzer.analyze()
```

返回结果结构：
```python
{
    "total_relationships": 120,       # 总关系数
    "top_relationships": [            # 主要关系列表
        {
            "person_a": "张三",
            "person_b": "李四",
            "message_count": 200,       # 消息数量
            "patterns": ["financial_corruption", "secret_meeting"],
            "relationship_type": ["资金往来", "秘密会面"],
            "strength": 0.85,           # 关系强度 (0-1)
            "risk_level": "🔴 高风险 - 需要重点关注 (8/10)",
            "evidence": [...]           # 证据列表
        }
    ],
    "statistics": {                   # 统计信息
        "avg_message_count": 50.5,
        "max_message_count": 200,
        "high_risk_count": 15,
        "medium_risk_count": 30,
        "low_risk_count": 75
    }
}
```

---

### SocialNetworkAnalyzer

社会关系网络分析器，深度分析人物社会关系。

#### 构造函数

##### `__init__(messages: List[Dict[str, Any]])`

```python
analyzer = SocialNetworkAnalyzer(messages)
```

#### 方法

##### `analyze() -> Dict[str, Any]`
执行完整的社会关系分析。

```python
results = analyzer.analyze()
```

返回结果结构：
```python
{
    "person_profiles": {              # 人物画像
        "张三": {
            "name": "张三",
            "message_count": 500,
            "contact_count": 15,
            "contacts": ["李四", "王五", ...],
            "primary_role": "business",
            "detected_roles": ["business", "intermediary"],
            "suspicious_message_count": 25,
            "corruption_patterns": {
                "financial_corruption": 12,
                "power_abuse": 8,
                "secret_meeting": 5
            },
            "risk_score": 7.2,
            "risk_level": "🔴 高风险",
            "activity_anomaly": {...},
            "first_seen": "2024-01-01T10:00:00",
            "last_seen": "2024-06-01T15:00:00",
            "active_period_days": 152
        }
    },
    "network_statistics": {...},      # 网络统计
    "intermediaries": [...],          # 中间人列表
    "communities": [...],             # 群体/圈子列表
    "influence_ranking": [...],       # 影响力排名
    "connection_paths": [...],        # 关系路径分析
    "key_relationships": [...]        # 关键关系
}
```

---

## 命令行接口

### 基础分析

```bash
python anti_corruption.py analyze <input_file> <output_file> [options]
```

选项：
- `--format`: 输入格式 (jsonl, txt, csv)
- `--min-risk`: 最小风险等级 (low, medium, high)

### 关系分析

```bash
python anti_corruption.py relationships <input_file> <output_file> [options]
```

### 社会关系网络分析

```bash
python anti_corruption.py social-network <input_file> <output_file> [options]
```

### 完整分析

```bash
python anti_corruption.py full <input_file> <output_dir> [options]
```

选项：
- `--batch-size`: 批处理大小 (默认: 10000)
- `--workers`: 并行工作线程数 (默认: 4)
- `--memory-limit`: 内存限制 (默认: 2G)

---

## 数据格式规范

### 输入消息格式

```json
{
    "timestamp": "2024-01-01T10:00:00Z",  // ISO 8601 格式
    "sender": "张三",                      // 发送者名称
    "receiver": "李四",                    // 接收者名称 (可选)
    "content": "消息内容",                  // 消息内容
    "group": "项目组A"                     // 群组名称 (可选)
}
```

### TXT 格式

```
[2024-01-01 10:00:00] 张三 -> 李四: 消息内容
[2024-01-01 10:05:00] 李四 -> 张三: 回复内容
```

---

## 错误处理

### 常见错误

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| JSONDecodeError | JSON格式错误 | 检查输入文件格式 |
| KeyError | 缺少必需字段 | 确保消息包含 timestamp, sender, content |
| UnicodeDecodeError | 编码问题 | 确保文件使用 UTF-8 编码 |
| MemoryError | 内存不足 | 减小 batch-size 或使用流式处理 |

### 异常类

```python
class AnalysisError(Exception):
    """分析过程中的错误"""
    pass

class ParseError(Exception):
    """解析错误"""
    pass

class ValidationError(Exception):
    """数据验证错误"""
    pass
```

---

## 性能优化建议

### 大规模数据处理

1. **使用批处理**
```python
# 分批加载和处理
batch_size = 10000
for batch in read_batches(file_path, batch_size):
    analyzer = ChatAnalyzer(batch)
    results = analyzer.analyze()
```

2. **并行处理**
```python
from multiprocessing import Pool

with Pool(processes=8) as pool:
    results = pool.map(analyze_batch, batches)
```

3. **内存优化**
- 使用生成器而非列表
- 及时删除不需要的数据
- 使用 `gc.collect()` 手动回收

### 性能指标

| 数据规模 | 处理时间 | 内存使用 |
|----------|----------|----------|
| 1万条 | ~2秒 | ~100MB |
| 10万条 | ~15秒 | ~500MB |
| 100万条 | ~3分钟 | ~2GB |
| 1000万条 | ~30分钟 | ~8GB |

---

## 扩展开发

### 自定义模式

```python
# 添加新的直接模式
PatternMatcher.DIRECT_PATTERNS['new_category'] = [
    r'新模式1',
    r'新模式2'
]

# 添加新的语义模式
PatternMatcher.SEMANTIC_PATTERNS['new_category'] = [
    '新语义1',
    '新语义2'
]
```

### 自定义分析器

```python
class CustomAnalyzer(ChatAnalyzer):
    def _calculate_risk(self, suspicious, patterns, times):
        # 自定义风险计算逻辑
        score = super()._calculate_risk(suspicious, patterns, times)
        # 添加自定义评分
        score += self.custom_factor
        return min(score, 10.0)
```

### 插件系统

```python
# 注册分析插件
class AnalysisPlugin:
    def analyze(self, messages):
        # 自定义分析逻辑
        pass

# 使用插件
analyzer = ChatAnalyzer(messages)
analyzer.register_plugin(AnalysisPlugin())
```
