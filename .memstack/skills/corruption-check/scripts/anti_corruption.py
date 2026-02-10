#!/usr/bin/env python3
"""
Anti-Corruption Investigation Tool v6.0

A unified tool for analyzing chat logs to detect corruption patterns,
build relationship networks, and generate human-friendly reports.

New in v6.0:
- Social relationship analysis (人物社会关系分析)
- Person profile analysis (人物画像)
- Intermediary detection (中间人识别)
- Community detection (群体检测)
- Influence analysis (影响力分析)

Usage:
    python anti_corruption.py analyze <input_file> <output_file> [options]
    python anti_corruption.py relationships <input_file> <output_file> [options]
    python anti_corruption.py social-network <input_file> <output_file> [options]
    python anti_corruption.py full <input_file> <output_dir> [options]

Examples:
    # Basic analysis
    python anti_corruption.py analyze data.jsonl report.json

    # Relationship analysis
    python anti_corruption.py relationships data.jsonl relationships.json

    # Social network analysis (NEW)
    python anti_corruption.py social-network data.jsonl social_network.json

    # Full analysis with all features
    python anti_corruption.py full data.jsonl output/ --batch-size 10000 --workers 8
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Tuple, Set
from collections import defaultdict
import re


class MessageParser:
    """Parse chat messages from various formats."""

    @staticmethod
    def parse_jsonl(file_path: str) -> List[Dict[str, Any]]:
        """Parse JSONL format."""
        messages = []
        with open(file_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                try:
                    msg = json.loads(line.strip())
                    if MessageParser._validate_message(msg):
                        messages.append(msg)
                except json.JSONDecodeError as e:
                    print(f"Warning: Invalid JSON at line {line_num}: {e}")
        return messages

    @staticmethod
    def parse_txt(file_path: str) -> List[Dict[str, Any]]:
        """Parse TXT format: [timestamp] sender -> receiver: content"""
        messages = []
        pattern = r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*(.+?)\s*->\s*(.+?):\s*(.+)'

        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                match = re.match(pattern, line.strip())
                if match:
                    timestamp, sender, receiver, content = match.groups()
                    messages.append({
                        'timestamp': timestamp,
                        'sender': sender.strip(),
                        'receiver': receiver.strip(),
                        'content': content.strip()
                    })
        return messages

    @staticmethod
    def _validate_message(msg: Dict[str, Any]) -> bool:
        """Validate message has required fields."""
        required = ['timestamp', 'content']
        if not all(field in msg for field in required):
            return False

        # Need either sender, or both sender and receiver
        if 'sender' not in msg:
            return False

        return True


class PatternMatcher:
    """Match corruption patterns using semantic similarity."""

    # Direct patterns (exact matches)
    DIRECT_PATTERNS = {
        'financial_corruption': [
            r'转账|汇款|账户|资金|钱款|回扣|贿赂|好处费|手续费',
            r'那笔钱|这笔钱|款项|费用|分成|提成|佣金'
        ],
        'power_abuse': [
            r'特殊照顾|通融一下|按老规矩|开绿灯|走后门',
            r'违规操作|暗箱操作|内部协调|打招呼|批条子'
        ],
        'secret_meeting': [
            r'老地方|私下见面|秘密会面|单独聊聊|当面说',
            r'不要告诉别人|保密|私事|私下|只有我们'
        ],
        'collusion': [
            r'统一口径|对好供词|串通|勾结|联手|合作',
            r'删除记录|清理聊天|销毁证据|不留痕迹'
        ]
    }

    # Semantic patterns (隐晦表达)
    SEMANTIC_PATTERNS = {
        'financial_corruption': [
            '东西准备好了吗', '那个东西', '事情办得怎么样了',
            '表示一下', '心意', '意思一下', '感谢费'
        ],
        'power_abuse': [
            '帮忙看看', '关照一下', '照顾一下', '帮忙处理',
            '特事特办', '按惯例', '老规矩', '都知道的'
        ],
        'secret_meeting': [
            '见面聊', '当面谈', '出来坐坐', '一起吃饭',
            '老地方见', '私下说', '不方便在这里说'
        ],
        'collusion': [
            '保持一致', '这么说', '统一说法', '口径一致',
            '删除吧', '清理一下', '别留记录', '撤回消息'
        ]
    }

    # Role patterns for person profiling
    ROLE_PATTERNS = {
        'official': [
            r'局长|处长|科长|主任|书记|市长|县长|区长|镇长',
            r'领导|干部|公务员|行政|审批|监管|执法'
        ],
        'business': [
            r'老板|经理|董事长|总经理|法人|股东|投资人',
            r'公司|企业|集团|供应商|承包商|经销商'
        ],
        'intermediary': [
            r'中介|代理|介绍人|牵线|搭桥|中间人|掮客',
            r'有关系|有门路|能搞定|能疏通'
        ],
        'family': [
            r'老婆|丈夫|妻子|老公|父亲|母亲|爸爸|妈妈',
            r'儿子|女儿|兄弟|姐妹|亲戚|家人|家属'
        ]
    }

    @classmethod
    def match_patterns(cls, content: str) -> List[str]:
        """Match content against corruption patterns."""
        matched = []

        # Direct pattern matching
        for category, patterns in cls.DIRECT_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, content):
                    matched.append(category)
                    break

        # Semantic pattern matching
        for category, patterns in cls.SEMANTIC_PATTERNS.items():
            if category in matched:
                continue  # Already matched by direct pattern
            for pattern in patterns:
                if pattern in content:
                    matched.append(category)
                    break

        return matched

    @classmethod
    def detect_roles(cls, content: str) -> List[str]:
        """Detect potential roles from content."""
        roles = []
        for role_type, patterns in cls.ROLE_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, content):
                    roles.append(role_type)
                    break
        return roles


class TimeAnalyzer:
    """Analyze time-based patterns."""

    @staticmethod
    def is_late_night(timestamp: str) -> bool:
        """Check if message is sent during late night (22:00-06:00)."""
        try:
            # Parse timestamp
            if 'T' in timestamp:
                time_part = timestamp.split('T')[1][:5]
            else:
                time_part = timestamp.split()[1][:5]

            hour = int(time_part.split(':')[0])
            return hour >= 22 or hour < 6
        except (ValueError, IndexError):
            return False

    @staticmethod
    def is_weekend(timestamp: str) -> bool:
        """Check if message is sent during weekend."""
        try:
            if 'T' in timestamp:
                date_part = timestamp.split('T')[0]
            else:
                date_part = timestamp.split()[0]

            dt = datetime.strptime(date_part, '%Y-%m-%d')
            return dt.weekday() >= 5  # 5=Saturday, 6=Sunday
        except (ValueError, IndexError):
            return False

    @staticmethod
    def parse_timestamp(timestamp: str) -> datetime:
        """Parse timestamp string to datetime object."""
        try:
            if 'T' in timestamp:
                return datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            else:
                return datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
            return None


class ChatAnalyzer:
    """Analyze chat messages for corruption patterns."""

    def __init__(self, messages: List[Dict[str, Any]]):
        self.messages = messages

    def analyze(self) -> Dict[str, Any]:
        """Perform comprehensive analysis."""
        suspicious_messages = []
        pattern_counts = {key: 0 for key in PatternMatcher.DIRECT_PATTERNS.keys()}
        time_anomalies = {'late_night': 0, 'weekend': 0}

        for msg in self.messages:
            content = msg.get('content', '')
            timestamp = msg.get('timestamp', '')

            # Match patterns
            matched = PatternMatcher.match_patterns(content)
            if matched:
                suspicious_msg = {
                    'timestamp': timestamp,
                    'sender': msg.get('sender', 'Unknown'),
                    'receiver': msg.get('receiver', 'Unknown'),
                    'content': content,
                    'patterns': matched
                }

                # Add time anomalies
                if TimeAnalyzer.is_late_night(timestamp):
                    suspicious_msg['time_anomaly'] = 'late_night'
                    time_anomalies['late_night'] += 1
                elif TimeAnalyzer.is_weekend(timestamp):
                    suspicious_msg['time_anomaly'] = 'weekend'
                    time_anomalies['weekend'] += 1

                suspicious_messages.append(suspicious_msg)

                # Count patterns
                for pattern in matched:
                    if pattern in pattern_counts:
                        pattern_counts[pattern] += 1

        # Calculate risk score
        risk_score = self._calculate_risk(suspicious_messages, pattern_counts, time_anomalies)

        # Identify key players
        key_players = self._identify_key_players(suspicious_messages)

        return {
            'total_messages': len(self.messages),
            'suspicious_count': len(suspicious_messages),
            'suspicious_rate': len(suspicious_messages) / len(self.messages) if self.messages else 0,
            'pattern_counts': pattern_counts,
            'time_anomalies': time_anomalies,
            'risk_score': risk_score,
            'risk_level': self._get_risk_level(risk_score),
            'suspicious_messages': suspicious_messages[:100],  # Limit output
            'key_players': key_players
        }

    def _calculate_risk(self, suspicious: List[Dict], patterns: Dict, times: Dict) -> float:
        """Calculate overall risk score (0-10)."""
        if not self.messages:
            return 0.0

        # Base score from suspicious rate
        suspicious_rate = len(suspicious) / len(self.messages)
        score = suspicious_rate * 10

        # Bonus for pattern diversity
        pattern_types = sum(1 for v in patterns.values() if v > 0)
        score += pattern_types * 0.5

        # Bonus for time anomalies
        time_score = (times['late_night'] + times['weekend']) / len(self.messages) * 10
        score += time_score * 0.3

        return min(score, 10.0)

    def _get_risk_level(self, score: float) -> str:
        """Convert risk score to level."""
        if score >= 6:
            return f"🔴 高风险 ({score:.1f}/10)"
        elif score >= 3:
            return f"🟠 中风险 ({score:.1f}/10)"
        else:
            return f"🟢 低风险 ({score:.1f}/10)"

    def _identify_key_players(self, suspicious: List[Dict]) -> List[Dict]:
        """Identify key players based on involvement."""
        player_counts = {}

        for msg in suspicious:
            sender = msg['sender']
            player_counts[sender] = player_counts.get(sender, 0) + 1

        # Sort by count
        sorted_players = sorted(player_counts.items(), key=lambda x: x[1], reverse=True)

        return [
            {'name': name, 'suspicious_count': count}
            for name, count in sorted_players[:10]
        ]


class RelationshipAnalyzer:
    """Analyze relationships between individuals."""

    def __init__(self, messages: List[Dict[str, Any]]):
        self.messages = messages

    def analyze(self) -> Dict[str, Any]:
        """Analyze relationships and build network."""
        relationships = {}
        message_counts = {}

        # Build relationships
        for msg in self.messages:
            sender = msg.get('sender', 'Unknown')
            receiver = msg.get('receiver', 'Unknown')

            if sender == 'Unknown' or receiver == 'Unknown':
                continue

            # Create unique key
            key = tuple(sorted([sender, receiver]))

            if key not in relationships:
                relationships[key] = {
                    'person_a': sender,
                    'person_b': receiver,
                    'message_count': 0,
                    'patterns': set(),
                    'evidence': []
                }

            relationships[key]['message_count'] += 1
            message_counts[key] = message_counts.get(key, 0) + 1

            # Check for patterns
            content = msg.get('content', '')
            matched = PatternMatcher.match_patterns(content)

            for pattern in matched:
                relationships[key]['patterns'].add(pattern)

            # Add evidence
            if matched:
                relationships[key]['evidence'].append({
                    'timestamp': msg.get('timestamp', ''),
                    'sender': sender,
                    'receiver': receiver,
                    'content': content,
                    'patterns': matched
                })

        # Convert to list and calculate strength
        relationship_list = []
        for rel in relationships.values():
            rel['patterns'] = list(rel['patterns'])

            # Calculate relationship strength
            max_count = max(message_counts.values()) if message_counts else 1
            rel['strength'] = rel['message_count'] / max_count

            # Determine relationship type
            rel['relationship_type'] = self._get_relationship_type(rel['patterns'])

            # Assess risk
            rel['risk_level'] = self._assess_risk(rel)

            relationship_list.append(rel)

        # Sort by message count
        relationship_list.sort(key=lambda x: x['message_count'], reverse=True)

        return {
            'total_relationships': len(relationship_list),
            'top_relationships': relationship_list[:50],  # Top 50
            'statistics': self._calculate_statistics(relationship_list)
        }

    def _get_relationship_type(self, patterns: List[str]) -> List[str]:
        """Map patterns to relationship types."""
        type_map = {
            'financial_corruption': '资金往来',
            'power_abuse': '权力滥用',
            'secret_meeting': '秘密会面',
            'collusion': '串通勾结'
        }

        types = []
        for pattern in patterns:
            if pattern in type_map:
                types.append(type_map[pattern])

        # Add frequent contact if high message count
        if not types:
            types.append('频繁联系')

        return types

    def _assess_risk(self, rel: Dict) -> str:
        """Assess risk level of relationship."""
        score = 0

        # Pattern-based score
        pattern_score = len(rel['patterns']) * 2
        score += pattern_score

        # Strength-based score
        if rel['strength'] > 0.8:
            score += 3
        elif rel['strength'] > 0.5:
            score += 2
        elif rel['strength'] > 0.3:
            score += 1

        # Evidence count
        if len(rel['evidence']) > 10:
            score += 2
        elif len(rel['evidence']) > 5:
            score += 1

        if score >= 7:
            return f"🔴 高风险 - 需要重点关注 ({score}/10)"
        elif score >= 4:
            return f"🟠 中风险 - 需要关注 ({score}/10)"
        else:
            return f"🟢 低风险 - 正常监控 ({score}/10)"

    def _calculate_statistics(self, relationships: List[Dict]) -> Dict:
        """Calculate network statistics."""
        if not relationships:
            return {}

        return {
            'avg_message_count': sum(r['message_count'] for r in relationships) / len(relationships),
            'max_message_count': max(r['message_count'] for r in relationships),
            'high_risk_count': sum(1 for r in relationships if '高风险' in r['risk_level']),
            'medium_risk_count': sum(1 for r in relationships if '中风险' in r['risk_level']),
            'low_risk_count': sum(1 for r in relationships if '低风险' in r['risk_level'])
        }


class SocialNetworkAnalyzer:
    """
    人物社会关系分析器

    分析人物的社会关系网络，包括：
    - 人物画像分析 (Person Profile Analysis)
    - 社会关系图谱 (Social Relationship Graph)
    - 中间人识别 (Intermediary Detection)
    - 群体检测 (Community Detection)
    - 影响力分析 (Influence Analysis)
    """

    def __init__(self, messages: List[Dict[str, Any]]):
        self.messages = messages
        self.person_profiles = {}
        self.relationship_graph = defaultdict(lambda: defaultdict(int))
        self.suspicious_edges = defaultdict(list)

    def analyze(self) -> Dict[str, Any]:
        """执行完整的社会关系网络分析。"""
        # Step 1: 构建人物画像
        self._build_person_profiles()

        # Step 2: 构建关系图谱
        self._build_relationship_graph()

        # Step 3: 识别中间人
        intermediaries = self._detect_intermediaries()

        # Step 4: 检测群体/圈子
        communities = self._detect_communities()

        # Step 5: 分析影响力
        influence = self._analyze_influence()

        # Step 6: 分析关系路径
        paths = self._analyze_connection_paths()

        return {
            'person_profiles': self.person_profiles,
            'network_statistics': self._calculate_network_stats(),
            'intermediaries': intermediaries,
            'communities': communities,
            'influence_ranking': influence,
            'connection_paths': paths,
            'key_relationships': self._extract_key_relationships()
        }

    def _build_person_profiles(self):
        """构建人物画像。"""
        person_data = defaultdict(lambda: {
            'message_count': 0,
            'contacts': set(),
            'suspicious_messages': [],
            'roles': set(),
            'activity_hours': defaultdict(int),
            'corruption_patterns': defaultdict(int),
            'first_seen': None,
            'last_seen': None
        })

        for msg in self.messages:
            sender = msg.get('sender', 'Unknown')
            receiver = msg.get('receiver', 'Unknown')
            content = msg.get('content', '')
            timestamp = msg.get('timestamp', '')

            if sender == 'Unknown':
                continue

            # Update sender data
            person_data[sender]['message_count'] += 1
            if receiver != 'Unknown':
                person_data[sender]['contacts'].add(receiver)

            # Parse timestamp
            dt = TimeAnalyzer.parse_timestamp(timestamp)
            if dt:
                hour = dt.hour
                person_data[sender]['activity_hours'][hour] += 1

                if not person_data[sender]['first_seen']:
                    person_data[sender]['first_seen'] = timestamp
                person_data[sender]['last_seen'] = timestamp

            # Check for corruption patterns
            patterns = PatternMatcher.match_patterns(content)
            if patterns:
                person_data[sender]['suspicious_messages'].append({
                    'timestamp': timestamp,
                    'content': content,
                    'patterns': patterns
                })
                for p in patterns:
                    person_data[sender]['corruption_patterns'][p] += 1

            # Detect roles
            roles = PatternMatcher.detect_roles(content)
            person_data[sender]['roles'].update(roles)

        # Convert to final profile format
        for person, data in person_data.items():
            # Calculate risk score
            risk_score = self._calculate_person_risk(data)

            # Determine primary role
            primary_role = self._determine_primary_role(data['roles'])

            # Calculate activity pattern anomaly
            activity_anomaly = self._calculate_activity_anomaly(data['activity_hours'])

            self.person_profiles[person] = {
                'name': person,
                'message_count': data['message_count'],
                'contact_count': len(data['contacts']),
                'contacts': list(data['contacts']),
                'primary_role': primary_role,
                'detected_roles': list(data['roles']),
                'suspicious_message_count': len(data['suspicious_messages']),
                'corruption_patterns': dict(data['corruption_patterns']),
                'risk_score': risk_score,
                'risk_level': self._get_risk_level_text(risk_score),
                'activity_anomaly': activity_anomaly,
                'first_seen': data['first_seen'],
                'last_seen': data['last_seen'],
                'active_period_days': self._calculate_active_days(
                    data['first_seen'], data['last_seen']
                )
            }

    def _build_relationship_graph(self):
        """构建关系图谱。"""
        for msg in self.messages:
            sender = msg.get('sender', 'Unknown')
            receiver = msg.get('receiver', 'Unknown')
            content = msg.get('content', '')

            if sender == 'Unknown' or receiver == 'Unknown':
                continue

            # Update edge weight
            self.relationship_graph[sender][receiver] += 1

            # Track suspicious edges
            patterns = PatternMatcher.match_patterns(content)
            if patterns:
                self.suspicious_edges[(sender, receiver)].append({
                    'timestamp': msg.get('timestamp', ''),
                    'content': content,
                    'patterns': patterns
                })

    def _detect_intermediaries(self) -> List[Dict]:
        """识别中间人（桥梁人物）。"""
        intermediaries = []

        for person, profile in self.person_profiles.items():
            # Calculate brokerage score (桥梁分数)
            brokerage_score = 0

            # 1. 连接不同群体的能力
            contacts = set(profile['contacts'])
            if len(contacts) >= 3:
                # Check if connects different communities
                connected_communities = set()
                for contact in contacts:
                    if contact in self.person_profiles:
                        # Simplified community detection based on shared contacts
                        contact_contacts = set(self.person_profiles[contact]['contacts'])
                        overlap = contacts & contact_contacts
                        if len(overlap) < 2:  # Weak connection between communities
                            connected_communities.add(contact)

                if len(connected_communities) >= 2:
                    brokerage_score += 3

            # 2. 消息转发特征
            if profile['message_count'] > 50:
                # Check for message forwarding patterns
                suspicious_ratio = profile['suspicious_message_count'] / profile['message_count']
                if 0.1 < suspicious_ratio < 0.5:  # Moderate suspicious activity
                    brokerage_score += 2

            # 3. 角色特征
            if 'intermediary' in profile['detected_roles']:
                brokerage_score += 3

            # 4. 联系人数与消息数比例
            if profile['contact_count'] > 5:
                ratio = profile['contact_count'] / (profile['message_count'] / 10)
                if ratio > 0.5:  # High contact diversity
                    brokerage_score += 1

            if brokerage_score >= 3:
                intermediaries.append({
                    'name': person,
                    'brokerage_score': brokerage_score,
                    'contact_count': profile['contact_count'],
                    'primary_role': profile['primary_role'],
                    'risk_level': profile['risk_level'],
                    'evidence': self._get_intermediary_evidence(person)
                })

        # Sort by brokerage score
        intermediaries.sort(key=lambda x: x['brokerage_score'], reverse=True)
        return intermediaries[:20]

    def _detect_communities(self) -> List[Dict]:
        """检测群体/圈子。"""
        communities = []

        # Simple community detection based on shared contacts
        person_communities = {}
        community_id = 0

        for person, profile in self.person_profiles.items():
            if person in person_communities:
                continue

            # Find community members
            community_members = {person}
            contacts = set(profile['contacts'])

            for contact in contacts:
                if contact in self.person_profiles:
                    contact_contacts = set(self.person_profiles[contact]['contacts'])
                    # If shares significant contacts, same community
                    overlap = contacts & contact_contacts
                    if len(overlap) >= 2 or contact_contacts & community_members:
                        community_members.add(contact)

            # Only consider groups of 3 or more
            if len(community_members) >= 3:
                for member in community_members:
                    person_communities[member] = community_id

                # Calculate community risk
                community_risk = sum(
                    self.person_profiles[m]['risk_score']
                    for m in community_members if m in self.person_profiles
                ) / len(community_members)

                # Find suspicious patterns in community
                community_patterns = defaultdict(int)
                for member in community_members:
                    if member in self.person_profiles:
                        for pattern, count in self.person_profiles[member]['corruption_patterns'].items():
                            community_patterns[pattern] += count

                communities.append({
                    'id': community_id,
                    'members': list(community_members),
                    'member_count': len(community_members),
                    'average_risk_score': round(community_risk, 2),
                    'risk_level': self._get_risk_level_text(community_risk),
                    'dominant_patterns': dict(community_patterns.most_common(5)) if hasattr(community_patterns, 'most_common') else dict(sorted(community_patterns.items(), key=lambda x: x[1], reverse=True)[:5]),
                    'internal_connections': self._count_internal_connections(community_members)
                })

                community_id += 1

        # Sort by risk score
        communities.sort(key=lambda x: x['average_risk_score'], reverse=True)
        return communities[:10]

    def _analyze_influence(self) -> List[Dict]:
        """分析人物影响力。"""
        influence_scores = []

        for person, profile in self.person_profiles.items():
            # Calculate influence score
            influence_score = 0

            # 1. 中心性 (Degree centrality)
            contact_count = profile['contact_count']
            max_contacts = max(p['contact_count'] for p in self.person_profiles.values()) or 1
            centrality = contact_count / max_contacts
            influence_score += centrality * 3

            # 2. 活跃度
            message_count = profile['message_count']
            max_messages = max(p['message_count'] for p in self.person_profiles.values()) or 1
            activity = message_count / max_messages
            influence_score += activity * 2

            # 3. 风险关联度
            risk_score = profile['risk_score'] / 10
            influence_score += risk_score * 2

            # 4. 桥梁作用
            if profile['contact_count'] >= 3:
                # Check connections between otherwise disconnected groups
                bridge_potential = 0
                contacts = set(profile['contacts'])
                for c1 in contacts:
                    for c2 in contacts:
                        if c1 != c2 and c1 in self.person_profiles and c2 in self.person_profiles:
                            c1_contacts = set(self.person_profiles[c1]['contacts'])
                            c2_contacts = set(self.person_profiles[c2]['contacts'])
                            if c1 not in c2_contacts and c2 not in c1_contacts:
                                bridge_potential += 1
                influence_score += min(bridge_potential / 10, 2)

            influence_scores.append({
                'name': person,
                'influence_score': round(influence_score, 2),
                'centrality': round(centrality, 2),
                'activity_score': round(activity, 2),
                'contact_count': contact_count,
                'message_count': message_count,
                'primary_role': profile['primary_role'],
                'risk_level': profile['risk_level']
            })

        # Sort by influence score
        influence_scores.sort(key=lambda x: x['influence_score'], reverse=True)
        return influence_scores[:30]

    def _analyze_connection_paths(self) -> Dict[str, Any]:
        """分析关键人物之间的连接路径。"""
        paths = {
            'shortest_paths': [],
            'key_bridges': [],
            'isolated_persons': []
        }

        # Find high-risk persons
        high_risk_persons = [
            name for name, profile in self.person_profiles.items()
            if profile['risk_score'] >= 6
        ]

        # Find shortest paths between high-risk persons
        for i, p1 in enumerate(high_risk_persons):
            for p2 in high_risk_persons[i+1:]:
                path = self._find_shortest_path(p1, p2)
                if path and len(path) > 2:
                    paths['shortest_paths'].append({
                        'from': p1,
                        'to': p2,
                        'path': path,
                        'length': len(path) - 1,
                        'intermediaries': path[1:-1]
                    })

        # Identify key bridges (people connecting high-risk groups)
        for person, profile in self.person_profiles.items():
            if profile['risk_score'] < 4:  # Not high risk themselves
                high_risk_connections = [
                    c for c in profile['contacts']
                    if c in self.person_profiles and self.person_profiles[c]['risk_score'] >= 6
                ]
                if len(high_risk_connections) >= 2:
                    paths['key_bridges'].append({
                        'name': person,
                        'connects': high_risk_connections,
                        'connection_count': len(high_risk_connections)
                    })

        # Find isolated persons (low connectivity, but some suspicious activity)
        for person, profile in self.person_profiles.items():
            if profile['contact_count'] <= 2 and profile['suspicious_message_count'] > 0:
                paths['isolated_persons'].append({
                    'name': person,
                    'contact_count': profile['contact_count'],
                    'suspicious_messages': profile['suspicious_message_count']
                })

        # Sort key bridges by connection count
        paths['key_bridges'].sort(key=lambda x: x['connection_count'], reverse=True)

        return paths

    def _find_shortest_path(self, start: str, end: str) -> List[str]:
        """使用BFS找到两个人之间的最短路径。"""
        if start == end:
            return [start]

        visited = {start}
        queue = [(start, [start])]

        while queue:
            current, path = queue.pop(0)

            if current in self.relationship_graph:
                for neighbor in self.relationship_graph[current]:
                    if neighbor == end:
                        return path + [neighbor]
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append((neighbor, path + [neighbor]))

        return None

    def _extract_key_relationships(self) -> List[Dict]:
        """提取关键关系（高风险或高强度）。"""
        key_relationships = []

        for (p1, p2), evidence in self.suspicious_edges.items():
            if evidence:
                risk_score = len(evidence) * 2
                if risk_score > 5:
                    key_relationships.append({
                        'person_a': p1,
                        'person_b': p2,
                        'suspicious_interactions': len(evidence),
                        'risk_score': min(risk_score, 10),
                        'evidence_sample': evidence[:3]
                    })

        # Sort by risk score
        key_relationships.sort(key=lambda x: x['risk_score'], reverse=True)
        return key_relationships[:20]

    def _calculate_network_stats(self) -> Dict[str, Any]:
        """计算网络统计信息。"""
        total_persons = len(self.person_profiles)
        total_edges = sum(
            len(contacts) for contacts in self.relationship_graph.values()
        ) // 2  # Undirected

        # Calculate density
        density = 0
        if total_persons > 1:
            max_edges = total_persons * (total_persons - 1) / 2
            density = total_edges / max_edges if max_edges > 0 else 0

        # Risk distribution
        risk_distribution = {'high': 0, 'medium': 0, 'low': 0}
        for profile in self.person_profiles.values():
            if profile['risk_score'] >= 6:
                risk_distribution['high'] += 1
            elif profile['risk_score'] >= 3:
                risk_distribution['medium'] += 1
            else:
                risk_distribution['low'] += 1

        # Role distribution
        role_distribution = defaultdict(int)
        for profile in self.person_profiles.values():
            role_distribution[profile['primary_role']] += 1

        return {
            'total_persons': total_persons,
            'total_relationships': total_edges,
            'network_density': round(density, 4),
            'avg_contacts_per_person': sum(
                p['contact_count'] for p in self.person_profiles.values()
            ) / total_persons if total_persons > 0 else 0,
            'risk_distribution': risk_distribution,
            'role_distribution': dict(role_distribution)
        }

    def _calculate_person_risk(self, data: Dict) -> float:
        """计算个人风险分数。"""
        score = 0

        # Suspicious message ratio
        if data['message_count'] > 0:
            suspicious_ratio = len(data['suspicious_messages']) / data['message_count']
            score += suspicious_ratio * 5

        # Pattern diversity
        pattern_types = len(data['corruption_patterns'])
        score += pattern_types * 0.5

        # Late night activity
        late_night_count = sum(
            count for hour, count in data['activity_hours'].items()
            if hour >= 22 or hour < 6
        )
        if data['message_count'] > 0:
            late_night_ratio = late_night_count / data['message_count']
            score += late_night_ratio * 2

        # Role-based risk
        if 'official' in data['roles'] and 'business' in data['roles']:
            score += 2  # Government-business connection

        return min(score, 10)

    def _determine_primary_role(self, roles: Set[str]) -> str:
        """确定主要角色。"""
        role_priority = ['official', 'intermediary', 'business', 'family']
        for role in role_priority:
            if role in roles:
                return role
        return 'unknown'

    def _calculate_activity_anomaly(self, activity_hours: Dict[int, int]) -> Dict[str, Any]:
        """计算活动模式异常。"""
        total = sum(activity_hours.values())
        if total == 0:
            return {'anomaly_score': 0, 'peak_hours': []}

        # Late night ratio
        late_night = sum(count for hour, count in activity_hours.items() if hour >= 22 or hour < 6)
        late_night_ratio = late_night / total

        # Find peak hours
        sorted_hours = sorted(activity_hours.items(), key=lambda x: x[1], reverse=True)
        peak_hours = [h for h, c in sorted_hours[:3]]

        # Anomaly score based on late night activity
        anomaly_score = late_night_ratio * 10

        return {
            'anomaly_score': round(anomaly_score, 2),
            'late_night_ratio': round(late_night_ratio, 2),
            'peak_hours': peak_hours
        }

    def _calculate_active_days(self, first_seen: str, last_seen: str) -> int:
        """计算活跃天数。"""
        if not first_seen or not last_seen:
            return 0

        try:
            dt1 = TimeAnalyzer.parse_timestamp(first_seen)
            dt2 = TimeAnalyzer.parse_timestamp(last_seen)
            if dt1 and dt2:
                return (dt2 - dt1).days + 1
        except:
            pass
        return 0

    def _get_risk_level_text(self, score: float) -> str:
        """获取风险等级文本。"""
        if score >= 6:
            return '🔴 高风险'
        elif score >= 3:
            return '🟠 中风险'
        else:
            return '🟢 低风险'

    def _get_intermediary_evidence(self, person: str) -> List[Dict]:
        """获取中间人的证据。"""
        evidence = []

        # Find messages where person connects two others
        for msg in self.messages:
            if msg.get('sender') == person:
                content = msg.get('content', '')
                # Look for connecting language
                if any(word in content for word in ['介绍', '牵线', '搭桥', '联系', '安排', '帮忙']):
                    evidence.append({
                        'timestamp': msg.get('timestamp', ''),
                        'content': content,
                        'receiver': msg.get('receiver', 'Unknown')
                    })

        return evidence[:5]

    def _count_internal_connections(self, members: Set[str]) -> int:
        """计算群体内连接数。"""
        count = 0
        for m1 in members:
            if m1 in self.relationship_graph:
                for m2 in self.relationship_graph[m1]:
                    if m2 in members:
                        count += 1
        return count // 2  # Undirected


class ReportGenerator:
    """Generate human-friendly reports."""

    @staticmethod
    def generate_relationship_report(relationships: Dict[str, Any]) -> str:
        """Generate human-readable relationship report."""
        lines = []
        lines.append("=" * 80)
        lines.append("反腐败调查 - 关系网络分析报告")
        lines.append("=" * 80)
        lines.append("")

        # Summary
        stats = relationships.get('statistics', {})
        lines.append("📊 统计摘要:")
        lines.append(f"  • 总关系数: {relationships['total_relationships']}")
        if stats:
            lines.append(f"  • 平均消息数: {stats['avg_message_count']:.1f}")
            lines.append(f"  • 最大消息数: {stats['max_message_count']}")
            lines.append(f"  • 高风险关系: {stats['high_risk_count']}")
            lines.append(f"  • 中风险关系: {stats['medium_risk_count']}")
            lines.append(f"  • 低风险关系: {stats['low_risk_count']}")
        lines.append("")

        # Top relationships
        lines.append("🎯 Top 关键关系:")
        lines.append("")

        for i, rel in enumerate(relationships['top_relationships'][:20], 1):
            lines.append(f"{i}. {rel['person_a']} ↔ {rel['person_b']}")
            lines.append(f"   关系类型: {', '.join(rel['relationship_type'])}")
            lines.append(f"   关系强度: {ReportGenerator._get_strength_emoji(rel['strength'])} {rel['strength']:.2f}")
            lines.append(f"   联系次数: {rel['message_count']}次")
            lines.append(f"   风险等级: {rel['risk_level']}")

            # Show evidence
            if rel['evidence']:
                lines.append(f"   关键证据:")
                for evidence in rel['evidence'][:3]:
                    lines.append(f"   • [{evidence['timestamp']}] {evidence['sender']} -> {evidence['receiver']}")
                    lines.append(f"     {evidence['content'][:80]}...")

            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def generate_social_network_report(analysis: Dict[str, Any]) -> str:
        """Generate human-readable social network analysis report."""
        lines = []
        lines.append("=" * 80)
        lines.append("反腐败调查 - 人物社会关系分析报告 (v6.0)")
        lines.append("=" * 80)
        lines.append("")

        # Network Statistics
        stats = analysis.get('network_statistics', {})
        lines.append("📊 网络统计概览:")
        lines.append(f"  • 涉及人员总数: {stats.get('total_persons', 0)}")
        lines.append(f"  • 关系连接总数: {stats.get('total_relationships', 0)}")
        lines.append(f"  • 网络密度: {stats.get('network_density', 0):.4f}")
        lines.append(f"  • 人均联系数: {stats.get('avg_contacts_per_person', 0):.1f}")
        lines.append("")

        # Risk Distribution
        risk_dist = stats.get('risk_distribution', {})
        lines.append("🎯 风险分布:")
        lines.append(f"  • 🔴 高风险: {risk_dist.get('high', 0)} 人")
        lines.append(f"  • 🟠 中风险: {risk_dist.get('medium', 0)} 人")
        lines.append(f"  • 🟢 低风险: {risk_dist.get('low', 0)} 人")
        lines.append("")

        # Role Distribution
        role_dist = stats.get('role_distribution', {})
        if role_dist:
            lines.append("👔 角色分布:")
            role_names = {
                'official': '官员/公务员',
                'business': '商人/企业主',
                'intermediary': '中介/掮客',
                'family': '家属/亲戚',
                'unknown': '未知'
            }
            for role, count in sorted(role_dist.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"  • {role_names.get(role, role)}: {count} 人")
            lines.append("")

        # Person Profiles
        lines.append("=" * 80)
        lines.append("👤 重点人员画像:")
        lines.append("=" * 80)
        lines.append("")

        # Sort by risk score
        profiles = analysis.get('person_profiles', {})
        sorted_profiles = sorted(
            profiles.items(),
            key=lambda x: x[1]['risk_score'],
            reverse=True
        )

        for i, (name, profile) in enumerate(sorted_profiles[:15], 1):
            lines.append(f"{i}. {name}")
            lines.append(f"   主要角色: {ReportGenerator._get_role_name(profile['primary_role'])}")
            lines.append(f"   风险等级: {profile['risk_level']} ({profile['risk_score']:.1f}/10)")
            lines.append(f"   消息总数: {profile['message_count']} 条")
            lines.append(f"   可疑消息: {profile['suspicious_message_count']} 条")
            lines.append(f"   联系人数: {profile['contact_count']} 人")
            lines.append(f"   活跃天数: {profile['active_period_days']} 天")

            if profile['corruption_patterns']:
                patterns = []
                pattern_names = {
                    'financial_corruption': '资金往来',
                    'power_abuse': '权力滥用',
                    'secret_meeting': '秘密会面',
                    'collusion': '串通勾结'
                }
                for p, c in list(profile['corruption_patterns'].items())[:3]:
                    patterns.append(f"{pattern_names.get(p, p)}({c})")
                lines.append(f"   腐败模式: {', '.join(patterns)}")

            lines.append("")

        # Intermediaries
        intermediaries = analysis.get('intermediaries', [])
        if intermediaries:
            lines.append("=" * 80)
            lines.append("🔗 中间人/桥梁人物识别:")
            lines.append("=" * 80)
            lines.append("")

            for i, inter in enumerate(intermediaries[:10], 1):
                lines.append(f"{i}. {inter['name']}")
                lines.append(f"   桥梁分数: {inter['brokerage_score']}/10")
                lines.append(f"   联系人数: {inter['contact_count']} 人")
                lines.append(f"   主要角色: {ReportGenerator._get_role_name(inter['primary_role'])}")
                lines.append(f"   风险等级: {inter['risk_level']}")

                if inter['evidence']:
                    lines.append(f"   关键证据:")
                    for ev in inter['evidence'][:2]:
                        lines.append(f"   • [{ev['timestamp']}] -> {ev['receiver']}")
                        lines.append(f"     {ev['content'][:60]}...")
                lines.append("")

        # Communities
        communities = analysis.get('communities', [])
        if communities:
            lines.append("=" * 80)
            lines.append("👥 群体/圈子检测:")
            lines.append("=" * 80)
            lines.append("")

            for i, comm in enumerate(communities[:5], 1):
                lines.append(f"群体 {i}:")
                lines.append(f"   成员数量: {comm['member_count']} 人")
                lines.append(f"   平均风险: {comm['average_risk_score']}/10 ({comm['risk_level']})")
                lines.append(f"   内部连接: {comm['internal_connections']} 条")
                lines.append(f"   成员: {', '.join(comm['members'][:8])}")
                if len(comm['members']) > 8:
                    lines.append(f"        ... 等共 {comm['member_count']} 人")

                if comm['dominant_patterns']:
                    lines.append(f"   主要腐败模式:")
                    pattern_names = {
                        'financial_corruption': '资金往来',
                        'power_abuse': '权力滥用',
                        'secret_meeting': '秘密会面',
                        'collusion': '串通勾结'
                    }
                    for p, c in list(comm['dominant_patterns'].items())[:3]:
                        lines.append(f"     - {pattern_names.get(p, p)}: {c} 次")
                lines.append("")

        # Influence Ranking
        influence = analysis.get('influence_ranking', [])
        if influence:
            lines.append("=" * 80)
            lines.append("⭐ 影响力排行榜 (Top 10):")
            lines.append("=" * 80)
            lines.append("")

            for i, person in enumerate(influence[:10], 1):
                lines.append(f"{i}. {person['name']}")
                lines.append(f"   影响力分数: {person['influence_score']:.2f}")
                lines.append(f"   中心性: {person['centrality']:.2f}")
                lines.append(f"   活跃度: {person['activity_score']:.2f}")
                lines.append(f"   联系数: {person['contact_count']} | 消息数: {person['message_count']}")
                lines.append(f"   角色: {ReportGenerator._get_role_name(person['primary_role'])}")
                lines.append("")

        # Connection Paths
        paths = analysis.get('connection_paths', {})
        if paths.get('key_bridges'):
            lines.append("=" * 80)
            lines.append("🌉 关键桥梁人物 (连接高风险群体):")
            lines.append("=" * 80)
            lines.append("")

            for bridge in paths['key_bridges'][:5]:
                lines.append(f"• {bridge['name']}")
                lines.append(f"  连接 {bridge['connection_count']} 个高风险人物:")
                for conn in bridge['connects'][:5]:
                    lines.append(f"    - {conn}")
                lines.append("")

        if paths.get('isolated_persons'):
            lines.append("=" * 80)
            lines.append("⚠️  孤立人员 (低联系但可疑):")
            lines.append("=" * 80)
            lines.append("")

            for person in paths['isolated_persons'][:5]:
                lines.append(f"• {person['name']}: {person['suspicious_messages']} 条可疑消息")
            lines.append("")

        # Key Relationships
        key_rels = analysis.get('key_relationships', [])
        if key_rels:
            lines.append("=" * 80)
            lines.append("🔥 高风险关系 (Top 10):")
            lines.append("=" * 80)
            lines.append("")

            for i, rel in enumerate(key_rels[:10], 1):
                lines.append(f"{i}. {rel['person_a']} ↔ {rel['person_b']}")
                lines.append(f"   可疑互动: {rel['suspicious_interactions']} 次")
                lines.append(f"   风险分数: {rel['risk_score']}/10")

                if rel['evidence_sample']:
                    lines.append(f"   证据示例:")
                    for ev in rel['evidence_sample'][:2]:
                        lines.append(f"   • [{ev['timestamp']}] {ev['content'][:70]}...")
                lines.append("")

        lines.append("=" * 80)
        lines.append("报告生成完成")
        lines.append("=" * 80)

        return "\n".join(lines)

    @staticmethod
    def _get_strength_emoji(strength: float) -> str:
        """Get emoji for relationship strength."""
        if strength >= 0.8:
            return "🔴 非常强"
        elif strength >= 0.5:
            return "🟠 强"
        elif strength >= 0.3:
            return "🟡 中等"
        else:
            return "🟢 弱"

    @staticmethod
    def _get_role_name(role: str) -> str:
        """获取角色中文名称。"""
        role_names = {
            'official': '官员/公务员',
            'business': '商人/企业主',
            'intermediary': '中介/掮客',
            'family': '家属/亲戚',
            'unknown': '未知'
        }
        return role_names.get(role, role)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Anti-Corruption Investigation Tool v6.0',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to execute')

    # Analyze command
    analyze_parser = subparsers.add_parser('analyze', help='Analyze chat messages for corruption patterns')
    analyze_parser.add_argument('input_file', help='Input file (JSONL or TXT)')
    analyze_parser.add_argument('output_file', help='Output JSON file')

    # Relationships command
    rel_parser = subparsers.add_parser('relationships', help='Analyze relationships between individuals')
    rel_parser.add_argument('input_file', help='Input file (JSONL or TXT)')
    rel_parser.add_argument('output_file', help='Output JSON file')
    rel_parser.add_argument('--text-report', help='Also generate text report')

    # Social network command (NEW)
    social_parser = subparsers.add_parser('social-network', help='Analyze social network and person profiles')
    social_parser.add_argument('input_file', help='Input file (JSONL or TXT)')
    social_parser.add_argument('output_file', help='Output JSON file')
    social_parser.add_argument('--text-report', help='Also generate text report')

    # Full command
    full_parser = subparsers.add_parser('full', help='Run full analysis')
    full_parser.add_argument('input_file', help='Input file (JSONL or TXT)')
    full_parser.add_argument('output_dir', help='Output directory')
    full_parser.add_argument('--batch-size', type=int, default=10000, help='Batch size for processing')
    full_parser.add_argument('--workers', type=int, default=4, help='Number of workers')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Load messages
    print(f"🔍 Loading messages from {args.input_file}...")
    input_path = Path(args.input_file)

    if not input_path.exists():
        print(f"❌ Error: File not found: {args.input_file}")
        sys.exit(1)

    # Parse based on extension
    if input_path.suffix == '.jsonl':
        messages = MessageParser.parse_jsonl(str(input_path))
    elif input_path.suffix == '.txt':
        messages = MessageParser.parse_txt(str(input_path))
    else:
        # Try JSONL first
        try:
            messages = MessageParser.parse_jsonl(str(input_path))
        except:
            messages = MessageParser.parse_txt(str(input_path))

    print(f"✅ Loaded {len(messages)} messages")

    # Execute command
    if args.command == 'analyze':
        print("🔬 Analyzing messages...")
        analyzer = ChatAnalyzer(messages)
        results = analyzer.analyze()

        print(f"📊 Found {results['suspicious_count']} suspicious messages")
        print(f"🎯 Risk Level: {results['risk_level']}")

        # Save results
        with open(args.output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        print(f"✅ Results saved to {args.output_file}")

    elif args.command == 'relationships':
        print("🕸️ Analyzing relationships...")
        analyzer = RelationshipAnalyzer(messages)
        results = analyzer.analyze()

        print(f"📊 Found {results['total_relationships']} relationships")

        # Save JSON results
        with open(args.output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        print(f"✅ Results saved to {args.output_file}")

        # Generate text report if requested
        if args.text_report:
            print("📝 Generating text report...")
            report = ReportGenerator.generate_relationship_report(results)

            with open(args.text_report, 'w', encoding='utf-8') as f:
                f.write(report)

            print(f"✅ Text report saved to {args.text_report}")

    elif args.command == 'social-network':
        print("🕸️ Analyzing social network and person relationships...")
        analyzer = SocialNetworkAnalyzer(messages)
        results = analyzer.analyze()

        stats = results.get('network_statistics', {})
        print(f"📊 Network Statistics:")
        print(f"   • Total persons: {stats.get('total_persons', 0)}")
        print(f"   • Total relationships: {stats.get('total_relationships', 0)}")
        print(f"   • Intermediaries detected: {len(results.get('intermediaries', []))}")
        print(f"   • Communities detected: {len(results.get('communities', []))}")

        # Save JSON results
        with open(args.output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        print(f"✅ Results saved to {args.output_file}")

        # Generate text report if requested
        if args.text_report:
            print("📝 Generating social network report...")
            report = ReportGenerator.generate_social_network_report(results)

            with open(args.text_report, 'w', encoding='utf-8') as f:
                f.write(report)

            print(f"✅ Text report saved to {args.text_report}")

    elif args.command == 'full':
        print("🚀 Running full analysis...")
        output_dir = Path(args.output_dir)
        output_dir.mkdir(exist_ok=True)

        # Run chat analysis
        print("🔬 Analyzing messages...")
        chat_analyzer = ChatAnalyzer(messages)
        chat_results = chat_analyzer.analyze()

        chat_output = output_dir / 'chat_analysis.json'
        with open(chat_output, 'w', encoding='utf-8') as f:
            json.dump(chat_results, f, ensure_ascii=False, indent=2)
        print(f"✅ Chat analysis saved to {chat_output}")

        # Run relationship analysis
        print("🕸️ Analyzing relationships...")
        rel_analyzer = RelationshipAnalyzer(messages)
        rel_results = rel_analyzer.analyze()

        rel_output = output_dir / 'relationships.json'
        with open(rel_output, 'w', encoding='utf-8') as f:
            json.dump(rel_results, f, ensure_ascii=False, indent=2)
        print(f"✅ Relationships saved to {rel_output}")

        # Run social network analysis (NEW)
        print("🕸️ Analyzing social network...")
        social_analyzer = SocialNetworkAnalyzer(messages)
        social_results = social_analyzer.analyze()

        social_output = output_dir / 'social_network.json'
        with open(social_output, 'w', encoding='utf-8') as f:
            json.dump(social_results, f, ensure_ascii=False, indent=2)
        print(f"✅ Social network saved to {social_output}")

        # Generate text reports
        print("📝 Generating reports...")

        rel_report = output_dir / 'relationship_report.txt'
        with open(rel_report, 'w', encoding='utf-8') as f:
            f.write(ReportGenerator.generate_relationship_report(rel_results))
        print(f"✅ Relationship report saved to {rel_report}")

        social_report = output_dir / 'social_network_report.txt'
        with open(social_report, 'w', encoding='utf-8') as f:
            f.write(ReportGenerator.generate_social_network_report(social_results))
        print(f"✅ Social network report saved to {social_report}")

    print("\n🎉 Analysis complete!")


if __name__ == '__main__':
    main()