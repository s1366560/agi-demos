#!/usr/bin/env python3
"""
Anti-Corruption Investigation Tool v7.0 (Enhanced Relationship Analysis)

A unified tool for analyzing chat logs to detect corruption patterns,
build relationship networks, and generate human-friendly reports.

New in v7.0:
- Enhanced social relationship analysis (增强人物社会关系分析)
- Advanced person profile analysis (高级人物画像)
- Multi-hop relationship detection (多跳关系检测)
- Relationship evolution tracking (关系演变追踪)
- Power structure analysis (权力结构分析)
- Collusion ring detection (串通团伙检测)
- Timeline analysis (时间线分析)
- Money flow tracing (资金流向追踪)

Usage:
    python anti_corruption_v2.py analyze <input_file> <output_file> [options]
    python anti_corruption_v2.py relationships <input_file> <output_file> [options]
    python anti_corruption_v2.py social-network <input_file> <output_file> [options]
    python anti_corruption_v2.py timeline <input_file> <output_file> [options]
    python anti_corruption_v2.py money-flow <input_file> <output_file> [options]
    python anti_corruption_v2.py full <input_file> <output_dir> [options]
"""

import argparse
import json
import importlib.util
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Tuple, Set, Optional
from collections import defaultdict, Counter
import re
from dataclasses import dataclass, field, asdict


@dataclass
class PersonProfile:
    """Enhanced person profile data class."""
    name: str
    message_count: int = 0
    contacts: Set[str] = field(default_factory=set)
    suspicious_messages: List[Dict] = field(default_factory=list)
    roles: Set[str] = field(default_factory=set)
    activity_hours: Dict[int, int] = field(default_factory=lambda: defaultdict(int))
    corruption_patterns: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    risk_score: float = 0.0
    influence_score: float = 0.0
    centrality_score: float = 0.0
    betweenness_score: float = 0.0


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
        if 'sender' not in msg:
            return False
        return True


class PatternMatcher:
    """Match corruption patterns using semantic similarity."""

    DIRECT_PATTERNS = {
        'financial_corruption': [
            r'转账|汇款|账户|资金|钱款|回扣|贿赂|好处费|手续费',
            r'那笔钱|这笔钱|款项|费用|分成|提成|佣金|现金',
            r'红包|礼金|打点|疏通|好处|意思|心意',
            r'银行|支付宝|微信|转账|收款|付款|打钱'
        ],
        'power_abuse': [
            r'特殊照顾|通融一下|按老规矩|开绿灯|走后门',
            r'违规操作|暗箱操作|内部协调|打招呼|批条子',
            r'审批|盖章|签字|特批|加急|优先|照顾',
            r'政策|规定|制度|程序|流程|手续|资质'
        ],
        'secret_meeting': [
            r'老地方|私下见面|秘密会面|单独聊聊|当面说',
            r'不要告诉别人|保密|私事|私下|只有我们',
            r'外面说|出去说|找个地方|见面聊|当面谈',
            r'不方便|别留记录|删除|撤回|清理'
        ],
        'collusion': [
            r'统一口径|对好供词|串通|勾结|联手|合作',
            r'删除记录|清理聊天|销毁证据|不留痕迹',
            r'一致|统一|商量好|说好了|约定|协议',
            r'配合|协作|分工|各自|负责|搞定'
        ],
        'money_laundering': [
            r'洗白|过账|走账|开票|发票|报销|做账',
            r'公司|账户|公户|私户|对公|对私|转账',
            r'合同|协议|票据|凭证|单据|流水|记录'
        ]
    }

    SEMANTIC_PATTERNS = {
        'financial_corruption': [
            '东西准备好了吗', '那个东西', '事情办得怎么样了',
            '表示一下', '心意', '意思一下', '感谢费',
            '辛苦费', '茶水费', '咨询费', '顾问费',
            '准备好了', '带来了', '拿到了', '收到了'
        ],
        'power_abuse': [
            '帮忙看看', '关照一下', '照顾一下', '帮忙处理',
            '特事特办', '按惯例', '老规矩', '都知道的',
            '通融', '行个方便', '给个面子', '帮个忙'
        ],
        'secret_meeting': [
            '见面聊', '当面谈', '出来坐坐', '一起吃饭',
            '老地方见', '私下说', '不方便在这里说',
            '外面见', '找个地方', '单独谈', '约个时间'
        ],
        'collusion': [
            '保持一致', '这么说', '统一说法', '口径一致',
            '删除吧', '清理一下', '别留记录', '撤回消息',
            '对好', '商量好', '说一致', '统一'
        ]
    }

    ROLE_PATTERNS = {
        'official': [
            r'局长|处长|科长|主任|书记|市长|县长|区长|镇长|所长',
            r'领导|干部|公务员|行政|审批|监管|执法|纪委|监察',
            r'常委|委员|代表|人大|政协|党委|政府|机关'
        ],
        'business': [
            r'老板|经理|董事长|总经理|法人|股东|投资人|老总',
            r'公司|企业|集团|供应商|承包商|经销商|项目|工程',
            r'业务|合作|项目|投标|招标|中标|合同|订单'
        ],
        'intermediary': [
            r'中介|代理|介绍人|牵线|搭桥|中间人|掮客|经纪人',
            r'有关系|有门路|能搞定|能疏通|认识人|熟悉',
            r'帮忙联系|帮忙介绍|可以安排|可以搞定'
        ],
        'family': [
            r'老婆|丈夫|妻子|老公|父亲|母亲|爸爸|妈妈|爸妈',
            r'儿子|女儿|兄弟|姐妹|亲戚|家人|家属|亲属|姐夫|妹夫',
            r'舅舅|姑姑|叔叔|阿姨|堂兄|表兄|侄子|外甥'
        ]
    }

    @classmethod
    def match_patterns(cls, content: str) -> List[str]:
        """Match content against corruption patterns."""
        matched = []
        for category, patterns in cls.DIRECT_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, content):
                    matched.append(category)
                    break
        for category, patterns in cls.SEMANTIC_PATTERNS.items():
            if category in matched:
                continue
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
    def parse_timestamp(timestamp: str) -> Optional[datetime]:
        """Parse timestamp string to datetime object."""
        try:
            if 'T' in timestamp:
                return datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            else:
                return datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
            return None


class EnhancedSocialNetworkAnalyzer:
    """增强版人物社会关系分析器"""

    def __init__(self, messages: List[Dict[str, Any]]):
        self.messages = messages
        self.person_profiles: Dict[str, PersonProfile] = {}
        self.relationship_graph: Dict[str, Dict[str, Dict]] = defaultdict(lambda: defaultdict(dict))
        self.suspicious_edges: Dict[Tuple[str, str], List[Dict]] = defaultdict(list)
        self.timeline_events: List[Dict] = []
        self.money_flows: List[Dict] = []

    def analyze(self) -> Dict[str, Any]:
        """执行完整的增强社会关系网络分析。"""
        self._build_person_profiles()
        self._build_relationship_graph()
        self._calculate_network_metrics()
        intermediaries = self._detect_intermediaries()
        communities = self._detect_communities()
        influence = self._analyze_influence()
        paths = self._analyze_connection_paths()
        multi_hop = self._detect_multi_hop_relationships()
        evolution = self._track_relationship_evolution()
        power_structure = self._analyze_power_structure()
        collusion_rings = self._detect_collusion_rings()
        self._build_timeline()
        self._trace_money_flows()

        return {
            'person_profiles': self._profiles_to_dict(),
            'network_statistics': self._calculate_network_stats(),
            'intermediaries': intermediaries,
            'communities': communities,
            'influence_ranking': influence,
            'connection_paths': paths,
            'multi_hop_relationships': multi_hop,
            'relationship_evolution': evolution,
            'power_structure': power_structure,
            'collusion_rings': collusion_rings,
            'timeline_events': self.timeline_events,
            'money_flows': self.money_flows,
            'key_relationships': self._extract_key_relationships()
        }

    def _build_person_profiles(self):
        """构建增强版人物画像。"""
        for msg in self.messages:
            sender = msg.get('sender', 'Unknown')
            receiver = msg.get('receiver', 'Unknown')
            content = msg.get('content', '')
            timestamp = msg.get('timestamp', '')

            if sender == 'Unknown':
                continue

            if sender not in self.person_profiles:
                self.person_profiles[sender] = PersonProfile(name=sender)

            profile = self.person_profiles[sender]
            profile.message_count += 1
            if receiver != 'Unknown':
                profile.contacts.add(receiver)

            dt = TimeAnalyzer.parse_timestamp(timestamp)
            if dt:
                profile.activity_hours[dt.hour] += 1
                if not profile.first_seen:
                    profile.first_seen = timestamp
                profile.last_seen = timestamp

            patterns = PatternMatcher.match_patterns(content)
            if patterns:
                profile.suspicious_messages.append({
                    'timestamp': timestamp,
                    'content': content,
                    'patterns': patterns
                })
                for p in patterns:
                    profile.corruption_patterns[p] += 1

            roles = PatternMatcher.detect_roles(content)
            profile.roles.update(roles)

    def _build_relationship_graph(self):
        """构建增强版关系图谱。"""
        for msg in self.messages:
            sender = msg.get('sender', 'Unknown')
            receiver = msg.get('receiver', 'Unknown')
            content = msg.get('content', '')
            timestamp = msg.get('timestamp', '')

            if sender == 'Unknown' or receiver == 'Unknown':
                continue

            if not self.relationship_graph[sender][receiver]:
                self.relationship_graph[sender][receiver] = {
                    'message_count': 0,
                    'first_contact': timestamp,
                    'last_contact': timestamp,
                    'patterns': defaultdict(int),
                    'suspicious_count': 0
                }

            edge = self.relationship_graph[sender][receiver]
            edge['message_count'] += 1
            edge['last_contact'] = timestamp

            patterns = PatternMatcher.match_patterns(content)
            if patterns:
                edge['suspicious_count'] += 1
                for p in patterns:
                    edge['patterns'][p] += 1
                self.suspicious_edges[(sender, receiver)].append({
                    'timestamp': timestamp,
                    'content': content,
                    'patterns': patterns
                })

    def _calculate_network_metrics(self):
        """计算网络中心性指标。"""
        if not self.person_profiles:
            return

        max_contacts = max(len(p.contacts) for p in self.person_profiles.values()) or 1
        for profile in self.person_profiles.values():
            profile.centrality_score = len(profile.contacts) / max_contacts

        for person, profile in self.person_profiles.items():
            betweenness = 0
            contacts = profile.contacts
            for other in self.person_profiles:
                if other == person:
                    continue
                for target in self.person_profiles:
                    if target == person or target == other:
                        continue
                    if self._is_bridge(person, other, target):
                        betweenness += 1
            profile.betweenness_score = betweenness / (len(self.person_profiles) ** 2) if len(self.person_profiles) > 2 else 0

        for profile in self.person_profiles.values():
            profile.risk_score = self._calculate_person_risk(profile)

    def _is_bridge(self, person: str, source: str, target: str) -> bool:
        """Check if person is a bridge between source and target."""
        if person not in self.relationship_graph:
            return False
        source_contacts = set(self.relationship_graph[source].keys()) if source in self.relationship_graph else set()
        target_contacts = set(self.relationship_graph[target].keys()) if target in self.relationship_graph else set()
        return person in source_contacts and person in target_contacts and source not in target_contacts

    def _calculate_person_risk(self, profile: PersonProfile) -> float:
        """计算个人风险分数。"""
        score = 0
        if profile.message_count > 0:
            suspicious_ratio = len(profile.suspicious_messages) / profile.message_count
            score += suspicious_ratio * 5
        pattern_types = len(profile.corruption_patterns)
        score += pattern_types * 0.5
        late_night_count = sum(
            count for hour, count in profile.activity_hours.items()
            if hour >= 22 or hour < 6
        )
        if profile.message_count > 0:
            late_night_ratio = late_night_count / profile.message_count
            score += late_night_ratio * 2
        if 'official' in profile.roles and 'business' in profile.roles:
            score += 2
        score += profile.betweenness_score * 2
        return min(score, 10)

    def _detect_intermediaries(self) -> List[Dict]:
        """识别中间人（桥梁人物）。"""
        intermediaries = []
        for person, profile in self.person_profiles.items():
            brokerage_score = 0
            contacts = profile.contacts
            if len(contacts) >= 3:
                connected_communities = set()
                for contact in contacts:
                    if contact in self.person_profiles:
                        contact_contacts = self.person_profiles[contact].contacts
                        overlap = contacts & contact_contacts
                        if len(overlap) < 2:
                            connected_communities.add(contact)
                if len(connected_communities) >= 2:
                    brokerage_score += 3
            if profile.message_count > 50:
                suspicious_ratio = len(profile.suspicious_messages) / profile.message_count
                if 0.1 < suspicious_ratio < 0.5:
                    brokerage_score += 2
            if 'intermediary' in profile.roles:
                brokerage_score += 3
            brokerage_score += profile.betweenness_score * 3
            if brokerage_score >= 3:
                intermediaries.append({
                    'name': person,
                    'brokerage_score': round(brokerage_score, 2),
                    'contact_count': len(contacts),
                    'primary_role': self._get_primary_role(profile.roles),
                    'risk_level': self._get_risk_level_text(profile.risk_score),
                    'betweenness_score': round(profile.betweenness_score, 2),
                    'evidence': self._get_intermediary_evidence(person)
                })
        intermediaries.sort(key=lambda x: x['brokerage_score'], reverse=True)
        return intermediaries[:20]

    def _detect_communities(self) -> List[Dict]:
        """检测群体/圈子。"""
        communities = []
        person_communities = {}
        community_id = 0

        for person, profile in self.person_profiles.items():
            if person in person_communities:
                continue
            community_members = {person}
            contacts = profile.contacts
            for contact in contacts:
                if contact in self.person_profiles:
                    contact_contacts = self.person_profiles[contact].contacts
                    overlap = contacts & contact_contacts
                    if len(overlap) >= 2 or contact_contacts & community_members:
                        community_members.add(contact)
            if len(community_members) >= 3:
                for member in community_members:
                    person_communities[member] = community_id
                community_risk = sum(
                    self.person_profiles[m].risk_score
                    for m in community_members if m in self.person_profiles
                ) / len(community_members)
                community_patterns = defaultdict(int)
                for member in community_members:
                    if member in self.person_profiles:
                        for pattern, count in self.person_profiles[member].corruption_patterns.items():
                            community_patterns[pattern] += count
                communities.append({
                    'id': community_id,
                    'members': list(community_members),
                    'member_count': len(community_members),
                    'average_risk_score': round(community_risk, 2),
                    'risk_level': self._get_risk_level_text(community_risk),
                    'dominant_patterns': dict(sorted(community_patterns.items(), key=lambda x: x[1], reverse=True)[:5]),
                    'internal_connections': self._count_internal_connections(community_members)
                })
                community_id += 1
        communities.sort(key=lambda x: x['average_risk_score'], reverse=True)
        return communities[:10]

    def _analyze_influence(self) -> List[Dict]:
        """分析人物影响力。"""
        influence_scores = []
        for person, profile in self.person_profiles.items():
            influence_score = 0
            max_contacts = max(len(p.contacts) for p in self.person_profiles.values()) or 1
            centrality = len(profile.contacts) / max_contacts
            influence_score += centrality * 3
            max_messages = max(p.message_count for p in self.person_profiles.values()) or 1
            activity = profile.message_count / max_messages
            influence_score += activity * 2
            risk_score = profile.risk_score / 10
            influence_score += risk_score * 2
            influence_score += profile.betweenness_score * 2
            profile.influence_score = influence_score
            influence_scores.append({
                'name': person,
                'influence_score': round(influence_score, 2),
                'centrality': round(centrality, 2),
                'activity_score': round(activity, 2),
                'betweenness': round(profile.betweenness_score, 2),
                'contact_count': len(profile.contacts),
                'message_count': profile.message_count,
                'primary_role': self._get_primary_role(profile.roles),
                'risk_level': self._get_risk_level_text(profile.risk_score)
            })
        influence_scores.sort(key=lambda x: x['influence_score'], reverse=True)
        return influence_scores[:30]

    def _analyze_connection_paths(self) -> Dict[str, Any]:
        """分析关键人物之间的连接路径。"""
        paths = {'shortest_paths': [], 'key_bridges': [], 'isolated_persons': []}
        high_risk_persons = [
            name for name, profile in self.person_profiles.items()
            if profile.risk_score >= 6
        ]
        for i, p1 in enumerate(high_risk_persons):
            for p2 in high_risk_persons[i+1:]:
                path = self._find_shortest_path(p1, p2)
                if path and len(path) > 2:
                    paths['shortest_paths'].append({
                        'from': p1, 'to': p2, 'path': path,
                        'length': len(path) - 1, 'intermediaries': path[1:-1]
                    })
        for person, profile in self.person_profiles.items():
            if profile.risk_score < 4:
                high_risk_connections = [
                    c for c in profile.contacts
                    if c in self.person_profiles and self.person_profiles[c].risk_score >= 6
                ]
                if len(high_risk_connections) >= 2:
                    paths['key_bridges'].append({
                        'name': person, 'connects': high_risk_connections,
                        'connection_count': len(high_risk_connections)
                    })
        for person, profile in self.person_profiles.items():
            if len(profile.contacts) <= 2 and len(profile.suspicious_messages) > 0:
                paths['isolated_persons'].append({
                    'name': person, 'contact_count': len(profile.contacts),
                    'suspicious_messages': len(profile.suspicious_messages)
                })
        paths['key_bridges'].sort(key=lambda x: x['connection_count'], reverse=True)
        return paths

    def _detect_multi_hop_relationships(self) -> List[Dict]:
        """检测多跳关系（2-3跳）。"""
        multi_hop = []
        high_risk_persons = [
            name for name, profile in self.person_profiles.items()
            if profile.risk_score >= 5
        ]
        for i, p1 in enumerate(high_risk_persons):
            for p2 in high_risk_persons[i+1:]:
                path_2 = self._find_path_with_length(p1, p2, 2)
                if path_2:
                    multi_hop.append({
                        'from': p1, 'to': p2, 'hops': 2, 'path': path_2,
                        'type': 'indirect_connection'
                    })
                path_3 = self._find_path_with_length(p1, p2, 3)
                if path_3:
                    multi_hop.append({
                        'from': p1, 'to': p2, 'hops': 3, 'path': path_3,
                        'type': 'extended_network'
                    })
        return multi_hop[:30]

    def _find_path_with_length(self, start: str, end: str, length: int) -> Optional[List[str]]:
        """Find path with specific length using BFS."""
        if start == end:
            return [start]
        visited = {start}
        queue = [(start, [start])]
        while queue:
            current, path = queue.pop(0)
            if len(path) > length + 1:
                continue
            if current in self.relationship_graph:
                for neighbor in self.relationship_graph[current]:
                    if neighbor == end and len(path) == length:
                        return path + [neighbor]
                    if neighbor not in visited and len(path) < length:
                        visited.add(neighbor)
                        queue.append((neighbor, path + [neighbor]))
        return None

    def _track_relationship_evolution(self) -> List[Dict]:
        """追踪关系演变。"""
        evolution = []
        for (p1, p2), messages in self.suspicious_edges.items():
            if len(messages) < 3:
                continue
            messages.sort(key=lambda x: x['timestamp'])
            early_patterns = set()
            late_patterns = set()
            mid = len(messages) // 2
            for msg in messages[:mid]:
                early_patterns.update(msg['patterns'])
            for msg in messages[mid:]:
                late_patterns.update(msg['patterns'])
            escalation = late_patterns - early_patterns
            if escalation:
                evolution.append({
                    'person_a': p1, 'person_b': p2,
                    'total_interactions': len(messages),
                    'first_interaction': messages[0]['timestamp'],
                    'last_interaction': messages[-1]['timestamp'],
                    'evolution_type': 'escalation' if escalation else 'stable',
                    'new_patterns': list(escalation),
                    'intensity_trend': self._calculate_intensity_trend(messages)
                })
        return evolution[:20]

    def _calculate_intensity_trend(self, messages: List[Dict]) -> str:
        """Calculate intensity trend of relationship."""
        if len(messages) < 4:
            return 'insufficient_data'
        q_size = len(messages) // 4
        quarters = [len(messages[i*q_size:(i+1)*q_size]) for i in range(4)]
        if quarters[-1] > quarters[0] * 1.5:
            return 'increasing'
        elif quarters[-1] < quarters[0] * 0.5:
            return 'decreasing'
        return 'stable'

    def _analyze_power_structure(self) -> Dict[str, Any]:
        """分析权力结构。"""
        structure = {'hierarchy_levels': [], 'power_centers': [], 'subordinates': defaultdict(list), 'power_dynamics': []}
        for person, profile in self.person_profiles.items():
            if profile.influence_score > 5 and 'official' in profile.roles:
                structure['power_centers'].append({
                    'name': person, 'influence_score': round(profile.influence_score, 2),
                    'role': 'official', 'subordinate_count': 0
                })
        for center in structure['power_centers']:
            center_name = center['name']
            if center_name in self.relationship_graph:
                for contact, edge_data in self.relationship_graph[center_name].items():
                    if edge_data.get('message_count', 0) > 10:
                        structure['subordinates'][center_name].append({
                            'name': contact, 'interaction_count': edge_data['message_count'],
                            'suspicious_ratio': edge_data.get('suspicious_count', 0) / edge_data['message_count']
                        })
                        center['subordinate_count'] += 1
        structure['power_centers'].sort(key=lambda x: x['subordinate_count'], reverse=True)
        return structure

    def _detect_collusion_rings(self) -> List[Dict]:
        """检测串通团伙。"""
        rings = []
        for p1 in self.person_profiles:
            for p2 in self.relationship_graph.get(p1, {}):
                for p3 in self.relationship_graph.get(p2, {}):
                    if p3 != p1 and p1 in self.relationship_graph.get(p3, {}):
                        ring_members = [p1, p2, p3]
                        ring_risk = sum(
                            self.person_profiles[m].risk_score
                            for m in ring_members if m in self.person_profiles
                        ) / 3
                        suspicious_count = 0
                        for i, m1 in enumerate(ring_members):
                            for m2 in ring_members[i+1:]:
                                suspicious_count += len(self.suspicious_edges.get((m1, m2), []))
                        if ring_risk > 3 or suspicious_count > 0:
                            rings.append({
                                'members': ring_members, 'type': 'triangle',
                                'risk_score': round(ring_risk, 2),
                                'suspicious_interactions': suspicious_count, 'member_count': 3
                            })
        seen = set()
        unique_rings = []
        for ring in rings:
            key = tuple(sorted(ring['members']))
            if key not in seen:
                seen.add(key)
                unique_rings.append(ring)
        unique_rings.sort(key=lambda x: (x['risk_score'], x['suspicious_interactions']), reverse=True)
        return unique_rings[:15]

    def _build_timeline(self):
        """构建事件时间线。"""
        events = []
        for msg in self.messages:
            patterns = PatternMatcher.match_patterns(msg.get('content', ''))
            if patterns:
                events.append({
                    'timestamp': msg.get('timestamp', ''),
                    'type': 'suspicious_message',
                    'sender': msg.get('sender', 'Unknown'),
                    'receiver': msg.get('receiver', 'Unknown'),
                    'content': msg.get('content', '')[:100],
                    'patterns': patterns
                })
        events.sort(key=lambda x: x['timestamp'])
        self.timeline_events = events[:200]

    def _trace_money_flows(self):
        """追踪资金流向。"""
        flows = []
        money_keywords = ['转账', '汇款', '打款', '付款', '收款', '钱', '现金', '账户']
        for msg in self.messages:
            content = msg.get('content', '')
            if any(kw in content for kw in money_keywords):
                patterns = PatternMatcher.match_patterns(content)
                if 'financial_corruption' in patterns or 'money_laundering' in patterns:
                    flows.append({
                        'timestamp': msg.get('timestamp', ''),
                        'from': msg.get('sender', 'Unknown'),
                        'to': msg.get('receiver', 'Unknown'),
                        'content': content[:150],
                        'patterns': patterns
                    })
        self.money_flows = flows[:50]

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
                        'person_a': p1, 'person_b': p2,
                        'suspicious_interactions': len(evidence),
                        'risk_score': min(risk_score, 10),
                        'evidence_sample': evidence[:3]
                    })
        key_relationships.sort(key=lambda x: x['risk_score'], reverse=True)
        return key_relationships[:20]

    def _calculate_network_stats(self) -> Dict[str, Any]:
        """计算网络统计信息。"""
        total_persons = len(self.person_profiles)
        total_edges = sum(len(contacts) for contacts in self.relationship_graph.values()) // 2
        density = 0
        if total_persons > 1:
            max_edges = total_persons * (total_persons - 1) / 2
            density = total_edges / max_edges if max_edges > 0 else 0
        risk_distribution = {'high': 0, 'medium': 0, 'low': 0}
        for profile in self.person_profiles.values():
            if profile.risk_score >= 6:
                risk_distribution['high'] += 1
            elif profile.risk_score >= 3:
                risk_distribution['medium'] += 1
            else:
                risk_distribution['low'] += 1
        role_distribution = defaultdict(int)
        for profile in self.person_profiles.values():
            role_distribution[self._get_primary_role(profile.roles)] += 1
        return {
            'total_persons': total_persons, 'total_relationships': total_edges,
            'network_density': round(density, 4),
            'avg_contacts_per_person': sum(len(p.contacts) for p in self.person_profiles.values()) / total_persons if total_persons > 0 else 0,
            'risk_distribution': risk_distribution, 'role_distribution': dict(role_distribution),
            'suspicious_edge_count': len(self.suspicious_edges),
            'timeline_event_count': len(self.timeline_events),
            'money_flow_count': len(self.money_flows)
        }

    def _profiles_to_dict(self) -> Dict[str, Dict]:
        """Convert profiles to dictionary."""
        result = {}
        for name, profile in self.person_profiles.items():
            result[name] = {
                'name': profile.name, 'message_count': profile.message_count,
                'contact_count': len(profile.contacts), 'contacts': list(profile.contacts),
                'suspicious_message_count': len(profile.suspicious_messages),
                'corruption_patterns': dict(profile.corruption_patterns),
                'roles': list(profile.roles), 'primary_role': self._get_primary_role(profile.roles),
                'risk_score': round(profile.risk_score, 2),
                'risk_level': self._get_risk_level_text(profile.risk_score),
                'influence_score': round(profile.influence_score, 2),
                'centrality_score': round(profile.centrality_score, 2),
                'betweenness_score': round(profile.betweenness_score, 2),
                'first_seen': profile.first_seen, 'last_seen': profile.last_seen
            }
        return result

    def _get_intermediary_evidence(self, person: str) -> List[Dict]:
        """获取中间人的证据。"""
        evidence = []
        for msg in self.messages:
            if msg.get('sender') == person:
                content = msg.get('content', '')
                if any(word in content for word in ['介绍', '牵线', '搭桥', '联系', '安排', '帮忙']):
                    evidence.append({'timestamp': msg.get('timestamp', ''), 'content': content, 'receiver': msg.get('receiver', 'Unknown')})
        return evidence[:5]

    def _count_internal_connections(self, members: Set[str]) -> int:
        """计算群体内连接数。"""
        count = 0
        for m1 in members:
            if m1 in self.relationship_graph:
                for m2 in self.relationship_graph[m1]:
                    if m2 in members:
                        count += 1
        return count // 2

    @staticmethod
    def _get_primary_role(roles: Set[str]) -> str:
        """确定主要角色。"""
        role_priority = ['official', 'intermediary', 'business', 'family']
        for role in role_priority:
            if role in roles:
                return role
        return 'unknown'

    @staticmethod
    def _get_risk_level_text(score: float) -> str:
        """获取风险等级文本。"""
        if score >= 6:
            return '🔴 高风险'
        elif score >= 3:
            return '🟠 中风险'
        return '🟢 低风险'


class TimelineAnalyzer:
    """时间线分析器"""
    def __init__(self, messages: List[Dict[str, Any]]):
        self.messages = messages

    def analyze(self) -> Dict[str, Any]:
        """分析时间线模式"""
        events = []
        daily_stats = defaultdict(lambda: {'messages': 0, 'suspicious': 0})
        hourly_stats = defaultdict(int)
        for msg in self.messages:
            timestamp = msg.get('timestamp', '')
            content = msg.get('content', '')
            dt = TimeAnalyzer.parse_timestamp(timestamp)
            if dt:
                date_key = dt.strftime('%Y-%m-%d')
                hour_key = dt.hour
                daily_stats[date_key]['messages'] += 1
                hourly_stats[hour_key] += 1
                patterns = PatternMatcher.match_patterns(content)
                if patterns:
                    daily_stats[date_key]['suspicious'] += 1
                    events.append({'timestamp': timestamp, 'sender': msg.get('sender', 'Unknown'), 'receiver': msg.get('receiver', 'Unknown'), 'content': content[:100], 'patterns': patterns})
        peak_days = sorted(daily_stats.items(), key=lambda x: x[1]['suspicious'], reverse=True)[:10]
        peak_hours = sorted(hourly_stats.items(), key=lambda x: x[1], reverse=True)[:5]
        return {'total_events': len(events), 'daily_activity': dict(daily_stats), 'hourly_distribution': dict(hourly_stats), 'peak_suspicious_days': [{'date': d, **s} for d, s in peak_days], 'peak_hours': [{'hour': h, 'count': c} for h, c in peak_hours], 'timeline_events': sorted(events, key=lambda x: x['timestamp'])[:100]}


class MoneyFlowAnalyzer:
    """资金流向分析器"""
    def __init__(self, messages: List[Dict[str, Any]]):
        self.messages = messages

    def analyze(self) -> Dict[str, Any]:
        """分析资金流向"""
        flows = []
        person_money_activity = defaultdict(lambda: {'sent': 0, 'received': 0, 'mentions': 0})
        money_keywords = ['转账', '汇款', '打款', '付款', '收款', '钱', '现金', '账户', '红包']
        amount_pattern = r'(\d+(?:\.\d+)?)\s*(万|千|百|元|块)'
        for msg in self.messages:
            content = msg.get('content', '')
            sender = msg.get('sender', 'Unknown')
            receiver = msg.get('receiver', 'Unknown')
            if any(kw in content for kw in money_keywords):
                patterns = PatternMatcher.match_patterns(content)
                amounts = re.findall(amount_pattern, content)
                flow_entry = {'timestamp': msg.get('timestamp', ''), 'from': sender, 'to': receiver, 'content': content[:150], 'patterns': patterns, 'extracted_amounts': amounts}
                flows.append(flow_entry)
                person_money_activity[sender]['sent'] += 1
                person_money_activity[receiver]['received'] += 1
                person_money_activity[sender]['mentions'] += 1
                person_money_activity[receiver]['mentions'] += 1
        key_handlers = sorted([{'name': name, 'sent': data['sent'], 'received': data['received'], 'total_mentions': data['mentions']} for name, data in person_money_activity.items()], key=lambda x: x['total_mentions'], reverse=True)[:20]
        return {'total_money_mentions': len(flows), 'money_flows': flows[:100], 'key_money_handlers': key_handlers}


class EnhancedReportGenerator:
    """增强版报告生成器"""

    @staticmethod
    def generate_social_network_report(analysis: Dict[str, Any]) -> str:
        """Generate enhanced social network analysis report."""
        lines = []
        lines.append("=" * 80)
        lines.append("反腐败调查 - 人物社会关系深度分析报告 (v7.0)")
        lines.append("=" * 80)
        lines.append("")
        stats = analysis.get('network_statistics', {})
        lines.append("📊 网络统计概览:")
        lines.append(f"  • 涉及人员总数: {stats.get('total_persons', 0)}")
        lines.append(f"  • 关系连接总数: {stats.get('total_relationships', 0)}")
        lines.append(f"  • 网络密度: {stats.get('network_density', 0):.4f}")
        lines.append(f"  • 人均联系数: {stats.get('avg_contacts_per_person', 0):.1f}")
        lines.append(f"  • 可疑互动数: {stats.get('suspicious_edge_count', 0)}")
        lines.append(f"  • 时间线事件: {stats.get('timeline_event_count', 0)}")
        lines.append(f"  • 资金往来记录: {stats.get('money_flow_count', 0)}")
        lines.append("")
        risk_dist = stats.get('risk_distribution', {})
        lines.append("🎯 风险分布:")
        lines.append(f"  • 🔴 高风险: {risk_dist.get('high', 0)} 人")
        lines.append(f"  • 🟠 中风险: {risk_dist.get('medium', 0)} 人")
        lines.append(f"  • 🟢 低风险: {risk_dist.get('low', 0)} 人")
        lines.append("")
        role_dist = stats.get('role_distribution', {})
        if role_dist:
            lines.append("👔 角色分布:")
            role_names = {'official': '官员/公务员', 'business': '商人/企业主', 'intermediary': '中介/掮客', 'family': '家属/亲戚', 'unknown': '未知'}
            for role, count in sorted(role_dist.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"  • {role_names.get(role, role)}: {count} 人")
            lines.append("")
        lines.append("=" * 80)
        lines.append("👤 重点人员画像 (Top 15):")
        lines.append("=" * 80)
        lines.append("")
        profiles = analysis.get('person_profiles', {})
        sorted_profiles = sorted(profiles.items(), key=lambda x: x[1]['risk_score'], reverse=True)
        for i, (name, profile) in enumerate(sorted_profiles[:15], 1):
            lines.append(f"{i}. {name}")
            lines.append(f"   主要角色: {EnhancedReportGenerator._get_role_name(profile['primary_role'])}")
            lines.append(f"   风险等级: {profile['risk_level']} ({profile['risk_score']:.1f}/10)")
            lines.append(f"   影响力分数: {profile.get('influence_score', 0):.2f}")
            lines.append(f"   中心性: {profile.get('centrality_score', 0):.2f} | 桥梁性: {profile.get('betweenness_score', 0):.2f}")
            lines.append(f"   消息总数: {profile['message_count']} 条")
            lines.append(f"   可疑消息: {profile['suspicious_message_count']} 条")
            lines.append(f"   联系人数: {profile['contact_count']} 人")
            if profile['corruption_patterns']:
                patterns = []
                pattern_names = {'financial_corruption': '资金往来', 'power_abuse': '权力滥用', 'secret_meeting': '秘密会面', 'collusion': '串通勾结', 'money_laundering': '洗钱'}
                for p, c in list(profile['corruption_patterns'].items())[:3]:
                    patterns.append(f"{pattern_names.get(p, p)}({c})")
                lines.append(f"   腐败模式: {', '.join(patterns)}")
            lines.append("")
        intermediaries = analysis.get('intermediaries', [])
        if intermediaries:
            lines.append("=" * 80)
            lines.append("🔗 中间人/桥梁人物识别 (Top 10):")
            lines.append("=" * 80)
            lines.append("")
            for i, inter in enumerate(intermediaries[:10], 1):
                lines.append(f"{i}. {inter['name']}")
                lines.append(f"   桥梁分数: {inter['brokerage_score']}/10")
                lines.append(f"   网络桥梁性: {inter.get('betweenness_score', 0):.2f}")
                lines.append(f"   联系人数: {inter['contact_count']} 人")
                lines.append(f"   主要角色: {EnhancedReportGenerator._get_role_name(inter['primary_role'])}")
                lines.append(f"   风险等级: {inter['risk_level']}")
                if inter.get('evidence'):
                    lines.append(f"   关键证据:")
                    for ev in inter['evidence'][:2]:
                        lines.append(f"   • [{ev['timestamp']}] -> {ev['receiver']}")
                        lines.append(f"     {ev['content'][:60]}...")
                lines.append("")
        communities = analysis.get('communities', [])
        if communities:
            lines.append("=" * 80)
            lines.append("👥 群体/圈子检测 (Top 5):")
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
                    pattern_names = {'financial_corruption': '资金往来', 'power_abuse': '权力滥用', 'secret_meeting': '秘密会面', 'collusion': '串通勾结', 'money_laundering': '洗钱'}
                    for p, c in list(comm['dominant_patterns'].items())[:3]:
                        lines.append(f"     - {pattern_names.get(p, p)}: {c} 次")
                lines.append("")
        multi_hop = analysis.get('multi_hop_relationships', [])
        if multi_hop:
            lines.append("=" * 80)
            lines.append("🔄 多跳关系检测 (间接关联):")
            lines.append("=" * 80)
            lines.append("")
            for i, rel in enumerate(multi_hop[:10], 1):
                lines.append(f"{i}. {rel['from']} {' -> '.join(rel['path'])} -> {rel['to']}")
                lines.append(f"   跳数: {rel['hops']} 跳")
                lines.append(f"   类型: {rel['type']}")
                lines.append("")
        evolution = analysis.get('relationship_evolution', [])
        if evolution:
            lines.append("=" * 80)
            lines.append("📈 关系演变追踪:")
            lines.append("=" * 80)
            lines.append("")
            for i, evol in enumerate(evolution[:10], 1):
                lines.append(f"{i}. {evol['person_a']} ↔ {evol['person_b']}")
                lines.append(f"   演变类型: {evol['evolution_type']}")
                lines.append(f"   互动次数: {evol['total_interactions']}")
                lines.append(f"   趋势: {evol['intensity_trend']}")
                if evol.get('new_patterns'):
                    lines.append(f"   新增模式: {', '.join(evol['new_patterns'])}")
                lines.append("")
        rings = analysis.get('collusion_rings', [])
        if rings:
            lines.append("=" * 80)
            lines.append("⚠️  串通团伙检测:")
            lines.append("=" * 80)
            lines.append("")
            for i, ring in enumerate(rings[:10], 1):
                lines.append(f"{i}. 团伙 {ring['type']}")
                lines.append(f"   成员: {', '.join(ring['members'])}")
                lines.append(f"   风险分数: {ring['risk_score']}/10")
                lines.append(f"   可疑互动: {ring['suspicious_interactions']} 次")
                lines.append("")
        power = analysis.get('power_structure', {})
        if power.get('power_centers'):
            lines.append("=" * 80)
            lines.append("👑 权力结构分析:")
            lines.append("=" * 80)
            lines.append("")
            for center in power['power_centers'][:5]:
                lines.append(f"• {center['name']} (影响力: {center['influence_score']})")
                lines.append(f"  下属人数: {center['subordinate_count']}")
                if center['name'] in power.get('subordinates', {}):
                    subs = power['subordinates'][center['name']][:5]
                    lines.append(f"  主要下属: {', '.join(s['name'] for s in subs)}")
                lines.append("")
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
                lines.append(f"   桥梁性: {person.get('betweenness', 0):.2f}")
                lines.append(f"   联系数: {person['contact_count']} | 消息数: {person['message_count']}")
                lines.append(f"   角色: {EnhancedReportGenerator._get_role_name(person['primary_role'])}")
                lines.append("")
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
                if rel.get('evidence_sample'):
                    lines.append(f"   证据示例:")
                    for ev in rel['evidence_sample'][:2]:
                        lines.append(f"   • [{ev['timestamp']}] {ev['content'][:70]}...")
                lines.append("")
        money_flows = analysis.get('money_flows', [])
        if money_flows:
            lines.append("=" * 80)
            lines.append("💰 资金流向追踪 (Top 10):")
            lines.append("=" * 80)
            lines.append("")
            for i, flow in enumerate(money_flows[:10], 1):
                lines.append(f"{i}. [{flow['timestamp']}] {flow['from']} -> {flow['to']}")
                lines.append(f"   内容: {flow['content'][:80]}...")
                if flow.get('extracted_amounts'):
                    amounts = [f"{a[0]}{a[1]}" for a in flow['extracted_amounts']]
                    lines.append(f"   提及金额: {', '.join(amounts)}")
                lines.append("")
        lines.append("=" * 80)
        lines.append("报告生成完成 - 增强版社会关系分析 v7.0")
        lines.append("=" * 80)
        return "\n".join(lines)

    @staticmethod
    def generate_timeline_report(analysis: Dict[str, Any]) -> str:
        """Generate timeline analysis report."""
        lines = []
        lines.append("=" * 80)
        lines.append("反腐败调查 - 时间线分析报告")
        lines.append("=" * 80)
        lines.append("")
        lines.append(f"📊 总事件数: {analysis.get('total_events', 0)}")
        lines.append("")
        peak_days = analysis.get('peak_suspicious_days', [])
        if peak_days:
            lines.append("📅 可疑活动高峰日 (Top 10):")
            for day in peak_days:
                lines.append(f"   {day['date']}: {day['suspicious']} 条可疑 / {day['messages']} 条总计")
            lines.append("")
        peak_hours = analysis.get('peak_hours', [])
        if peak_hours:
            lines.append("⏰ 活跃高峰时段:")
            for hour in peak_hours:
                lines.append(f"   {hour['hour']:02d}:00 - {hour['count']} 条消息")
            lines.append("")
        events = analysis.get('timeline_events', [])
        if events:
            lines.append("📋 关键事件时间线 (Top 50):")
            lines.append("")
            for i, event in enumerate(events[:50], 1):
                lines.append(f"{i}. [{event['timestamp']}]")
                lines.append(f"   发送者: {event['sender']} -> {event['receiver']}")
                lines.append(f"   内容: {event['content']}")
                lines.append(f"   模式: {', '.join(event['patterns'])}")
                lines.append("")
        return "\n".join(lines)

    @staticmethod
    def generate_money_flow_report(analysis: Dict[str, Any]) -> str:
        """Generate money flow analysis report."""
        lines = []
        lines.append("=" * 80)
        lines.append("反腐败调查 - 资金流向分析报告")
        lines.append("=" * 80)
        lines.append("")
        lines.append(f"💰 资金提及总数: {analysis.get('total_money_mentions', 0)}")
        lines.append("")
        handlers = analysis.get('key_money_handlers', [])
        if handlers:
            lines.append("👤 关键资金处理人员 (Top 15):")
            lines.append("")
            for i, handler in enumerate(handlers[:15], 1):
                lines.append(f"{i}. {handler['name']}")
                lines.append(f"   发送提及: {handler['sent']} 次")
                lines.append(f"   接收提及: {handler['received']} 次")
                lines.append(f"   总提及数: {handler['total_mentions']} 次")
                lines.append("")
        flows = analysis.get('money_flows', [])
        if flows:
            lines.append("📋 资金往来记录 (Top 50):")
            lines.append("")
            for i, flow in enumerate(flows[:50], 1):
                lines.append(f"{i}. [{flow['timestamp']}]")
                lines.append(f"   从: {flow['from']} -> 到: {flow['to']}")
                lines.append(f"   内容: {flow['content']}")
                if flow.get('extracted_amounts'):
                    amounts = [f"{a[0]}{a[1]}" for a in flow['extracted_amounts']]
                    lines.append(f"   金额: {', '.join(amounts)}")
                lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _get_role_name(role: str) -> str:
        """获取角色中文名称。"""
        role_names = {'official': '官员/公务员', 'business': '商人/企业主', 'intermediary': '中介/掮客', 'family': '家属/亲戚', 'unknown': '未知'}
        return role_names.get(role, role)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Anti-Corruption Investigation Tool v7.0 (Enhanced)', formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    analyze_parser = subparsers.add_parser('analyze', help='Analyze chat messages for corruption patterns')
    analyze_parser.add_argument('input_file', help='Input file (JSONL or TXT)')
    analyze_parser.add_argument('output_file', help='Output JSON file')
    rel_parser = subparsers.add_parser('relationships', help='Analyze relationships between individuals')
    rel_parser.add_argument('input_file', help='Input file (JSONL or TXT)')
    rel_parser.add_argument('output_file', help='Output JSON file')
    rel_parser.add_argument('--text-report', help='Also generate text report')
    social_parser = subparsers.add_parser('social-network', help='Analyze social network with enhanced features')
    social_parser.add_argument('input_file', help='Input file (JSONL or TXT)')
    social_parser.add_argument('output_file', help='Output JSON file')
    social_parser.add_argument('--text-report', help='Also generate text report')
    timeline_parser = subparsers.add_parser('timeline', help='Analyze timeline patterns')
    timeline_parser.add_argument('input_file', help='Input file (JSONL or TXT)')
    timeline_parser.add_argument('output_file', help='Output JSON file')
    timeline_parser.add_argument('--text-report', help='Also generate text report')
    money_parser = subparsers.add_parser('money-flow', help='Analyze money flows')
    money_parser.add_argument('input_file', help='Input file (JSONL or TXT)')
    money_parser.add_argument('output_file', help='Output JSON file')
    money_parser.add_argument('--text-report', help='Also generate text report')
    full_parser = subparsers.add_parser('full', help='Run full analysis with all features')
    full_parser.add_argument('input_file', help='Input file (JSONL or TXT)')
    full_parser.add_argument('output_dir', help='Output directory')
    full_parser.add_argument('--batch-size', type=int, default=10000, help='Batch size for processing')
    full_parser.add_argument('--workers', type=int, default=4, help='Number of workers')
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    print(f"🔍 Loading messages from {args.input_file}...")
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"❌ Error: File not found: {args.input_file}")
        sys.exit(1)

    if input_path.suffix == '.jsonl':
        messages = MessageParser.parse_jsonl(str(input_path))
    elif input_path.suffix == '.txt':
        messages = MessageParser.parse_txt(str(input_path))
    else:
        try:
            messages = MessageParser.parse_jsonl(str(input_path))
        except:
            messages = MessageParser.parse_txt(str(input_path))

    print(f"✅ Loaded {len(messages)} messages")

    if args.command in {'analyze', 'relationships', 'full'}:
        # Both bundled skills share the basic analyzers and their report format.
        basic_path = (
            Path(__file__).resolve().parents[1]
            / 'anti-corruption-investigation'
            / 'anti_corruption.py'
        )
        if basic_path.is_file():
            spec = importlib.util.spec_from_file_location('anti_corruption', basic_path)
            if spec is None or spec.loader is None:
                raise ImportError(f'Cannot load the investigation skill at {basic_path}')
            basic = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(basic)
        else:
            import anti_corruption as basic

    if args.command == 'analyze':
        print("🔬 Analyzing messages...")
        analyzer = basic.ChatAnalyzer(messages)
        results = analyzer.analyze()
        print(f"📊 Found {results['suspicious_count']} suspicious messages")
        print(f"🎯 Risk Level: {results['risk_level']}")
        with open(args.output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"✅ Results saved to {args.output_file}")

    elif args.command == 'relationships':
        print("🕸️ Analyzing relationships...")
        analyzer = basic.RelationshipAnalyzer(messages)
        results = analyzer.analyze()
        print(f"📊 Found {results['total_relationships']} relationships")
        with open(args.output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"✅ Results saved to {args.output_file}")
        if args.text_report:
            print("📝 Generating text report...")
            report = basic.ReportGenerator.generate_relationship_report(results)
            with open(args.text_report, 'w', encoding='utf-8') as f:
                f.write(report)
            print(f"✅ Text report saved to {args.text_report}")

    elif args.command == 'social-network':
        print("🕸️ Analyzing social network with enhanced features...")
        analyzer = EnhancedSocialNetworkAnalyzer(messages)
        results = analyzer.analyze()
        stats = results.get('network_statistics', {})
        print(f"📊 Network Statistics:")
        print(f"   • Total persons: {stats.get('total_persons', 0)}")
        print(f"   • Total relationships: {stats.get('total_relationships', 0)}")
        print(f"   • Intermediaries detected: {len(results.get('intermediaries', []))}")
        print(f"   • Communities detected: {len(results.get('communities', []))}")
        print(f"   • Collusion rings detected: {len(results.get('collusion_rings', []))}")
        with open(args.output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"✅ Results saved to {args.output_file}")
        if args.text_report:
            print("📝 Generating social network report...")
            report = EnhancedReportGenerator.generate_social_network_report(results)
            with open(args.text_report, 'w', encoding='utf-8') as f:
                f.write(report)
            print(f"✅ Text report saved to {args.text_report}")

    elif args.command == 'timeline':
        print("📅 Analyzing timeline patterns...")
        analyzer = TimelineAnalyzer(messages)
        results = analyzer.analyze()
        print(f"📊 Found {results['total_events']} timeline events")
        with open(args.output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"✅ Results saved to {args.output_file}")
        if args.text_report:
            print("📝 Generating timeline report...")
            report = EnhancedReportGenerator.generate_timeline_report(results)
            with open(args.text_report, 'w', encoding='utf-8') as f:
                f.write(report)
            print(f"✅ Text report saved to {args.text_report}")

    elif args.command == 'money-flow':
        print("💰 Analyzing money flows...")
        analyzer = MoneyFlowAnalyzer(messages)
        results = analyzer.analyze()
        print(f"📊 Found {results['total_money_mentions']} money flow mentions")
        with open(args.output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"✅ Results saved to {args.output_file}")
        if args.text_report:
            print("📝 Generating money flow report...")
            report = EnhancedReportGenerator.generate_money_flow_report(results)
            with open(args.text_report, 'w', encoding='utf-8') as f:
                f.write(report)
            print(f"✅ Text report saved to {args.text_report}")

    elif args.command == 'full':
        print("🚀 Running full enhanced analysis...")
        output_dir = Path(args.output_dir)
        output_dir.mkdir(exist_ok=True)

        print("🔬 Analyzing messages...")
        chat_analyzer = basic.ChatAnalyzer(messages)
        chat_results = chat_analyzer.analyze()
        chat_output = output_dir / 'chat_analysis.json'
        with open(chat_output, 'w', encoding='utf-8') as f:
            json.dump(chat_results, f, ensure_ascii=False, indent=2)
        print(f"✅ Chat analysis saved to {chat_output}")

        print("🕸️ Analyzing relationships...")
        rel_analyzer = basic.RelationshipAnalyzer(messages)
        rel_results = rel_analyzer.analyze()
        rel_output = output_dir / 'relationships.json'
        with open(rel_output, 'w', encoding='utf-8') as f:
            json.dump(rel_results, f, ensure_ascii=False, indent=2)
        print(f"✅ Relationships saved to {rel_output}")

        print("🕸️ Analyzing enhanced social network...")
        social_analyzer = EnhancedSocialNetworkAnalyzer(messages)
        social_results = social_analyzer.analyze()
        social_output = output_dir / 'social_network.json'
        with open(social_output, 'w', encoding='utf-8') as f:
            json.dump(social_results, f, ensure_ascii=False, indent=2)
        print(f"✅ Social network saved to {social_output}")

        print("📅 Analyzing timeline...")
        timeline_analyzer = TimelineAnalyzer(messages)
        timeline_results = timeline_analyzer.analyze()
        timeline_output = output_dir / 'timeline.json'
        with open(timeline_output, 'w', encoding='utf-8') as f:
            json.dump(timeline_results, f, ensure_ascii=False, indent=2)
        print(f"✅ Timeline saved to {timeline_output}")

        print("💰 Analyzing money flows...")
        money_analyzer = MoneyFlowAnalyzer(messages)
        money_results = money_analyzer.analyze()
        money_output = output_dir / 'money_flows.json'
        with open(money_output, 'w', encoding='utf-8') as f:
            json.dump(money_results, f, ensure_ascii=False, indent=2)
        print(f"✅ Money flows saved to {money_output}")

        print("📝 Generating reports...")
        rel_report = output_dir / 'relationship_report.txt'
        with open(rel_report, 'w', encoding='utf-8') as f:
            f.write(basic.ReportGenerator.generate_relationship_report(rel_results))
        print(f"✅ Relationship report saved to {rel_report}")

        social_report = output_dir / 'social_network_report.txt'
        with open(social_report, 'w', encoding='utf-8') as f:
            f.write(EnhancedReportGenerator.generate_social_network_report(social_results))
        print(f"✅ Social network report saved to {social_report}")

        timeline_report = output_dir / 'timeline_report.txt'
        with open(timeline_report, 'w', encoding='utf-8') as f:
            f.write(EnhancedReportGenerator.generate_timeline_report(timeline_results))
        print(f"✅ Timeline report saved to {timeline_report}")

        money_report = output_dir / 'money_flow_report.txt'
        with open(money_report, 'w', encoding='utf-8') as f:
            f.write(EnhancedReportGenerator.generate_money_flow_report(money_results))
        print(f"✅ Money flow report saved to {money_report}")

    print("\n🎉 Analysis complete!")


if __name__ == '__main__':
    main()
