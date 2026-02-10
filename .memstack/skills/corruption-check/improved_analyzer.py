#!/usr/bin/env python3
"""
改进版反腐败调查分析器 - 社会关系网络分析
"""

import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path


class ImprovedCorruptionAnalyzer:
    """改进版腐败线索分析器 - 重点优化社会关系识别"""

    # 腐败关键词模式
    CORRUPTION_PATTERNS = {
        'fund_transfer': {
            'keywords': ['回扣', '转账', '好处费', '佣金', '打点', '感谢费', '辛苦费',
                        '返点', '提成', '好处', '意思', '表示', '心意'],
            'weight': 3
        },
        'power_abuse': {
            'keywords': ['照顾', '帮忙', '操作', '搞定', '疏通', '安排', '打招呼',
                        '特殊', '内部', '关系', '人脉', '路子'],
            'weight': 2
        },
        'secret_meeting': {
            'keywords': ['见面', '面谈', '私聊', '单独', '老地方', '私下', ' discreet',
                        ' discreetly', '避人耳目'],
            'weight': 2
        },
        'collusion': {
            'keywords': ['统一口径', '串供', '隐瞒', '销毁', '证据', '保密', '别留',
                        '删掉', '清除', '不要留', '别让人'],
            'weight': 4
        },
        'information_leak': {
            'keywords': ['底价', '标底', '预算', '内部价', '竞争对手', '报价',
                        '标书', '评分', '评委', '内幕', '消息'],
            'weight': 3
        }
    }

    # 角色识别关键词
    ROLE_INDICATORS = {
        'official': ['局长', '处长', '科长', '主任', '经理', '领导', '干部', '书记'],
        'business': ['老板', '总', '经理', '负责人', '供应商', '厂家', '公司'],
        'intermediary': ['介绍', '牵线', '搭桥', '中间', '帮忙', '表哥', '亲戚', '朋友'],
        'family': ['老婆', '孩子', '儿子', '女儿', '家', '家里', '家人']
    }

    def __init__(self, messages):
        self.messages = messages
        self.persons = {}  # 人物信息
        self.relationships = defaultdict(lambda: {
            'interactions': [],
            'suspicious_count': 0,
            'fund_transfers': [],
            'info_leaks': [],
            'meetings': []
        })
        self.groups = []  # 群体/圈子
        self.timeline = []  # 时间线

    def parse_messages(self):
        """解析消息，提取结构化信息"""
        parsed = []
        for msg in self.messages:
            content = msg.get('content', '')

            # 解析格式: [时间] 发送人 -> 接收人: 内容
            match = re.match(r'\[(.*?)\]\s*(.+?)\s*->\s*(.+?)\s*:\s*(.+)', content)
            if match:
                time_str, sender, receiver, message = match.groups()
                parsed.append({
                    'time': time_str.strip(),
                    'sender': sender.strip(),
                    'receiver': receiver.strip(),
                    'content': message.strip(),
                    'raw': content
                })
            else:
                # 尝试其他格式
                parsed.append({
                    'time': msg.get('timestamp', ''),
                    'sender': msg.get('sender', 'Unknown'),
                    'receiver': msg.get('receiver', 'Unknown'),
                    'content': content,
                    'raw': content
                })

        return parsed

    def identify_roles(self, parsed_messages):
        """识别人物角色"""
        for msg in parsed_messages:
            for person in [msg['sender'], msg['receiver']]:
                if person not in self.persons:
                    self.persons[person] = {
                        'name': person,
                        'roles': set(),
                        'messages_sent': 0,
                        'messages_received': 0,
                        'suspicious_score': 0,
                        'connections': set(),
                        'behavior_patterns': defaultdict(int),
                        'financial_flows': {'in': 0, 'out': 0}
                    }

                self.persons[person]['connections'].add(
                    msg['receiver'] if msg['sender'] == person else msg['sender']
                )

                if msg['sender'] == person:
                    self.persons[person]['messages_sent'] += 1
                else:
                    self.persons[person]['messages_received'] += 1

                # 识别角色
                content = msg['content']
                for role_type, indicators in self.ROLE_INDICATORS.items():
                    for indicator in indicators:
                        if indicator in content:
                            # 检查是否是描述此人
                            if person in content[:50] or person == msg['sender']:
                                self.persons[person]['roles'].add(role_type)

    def detect_corruption_patterns(self, parsed_messages):
        """检测腐败模式并构建关系"""
        for msg in parsed_messages:
            sender = msg['sender']
            receiver = msg['receiver']
            content = msg['content']

            # 构建关系键（有序，避免 A->B 和 B->A 重复）
            rel_key = tuple(sorted([sender, receiver]))

            interaction = {
                'time': msg['time'],
                'sender': sender,
                'receiver': receiver,
                'content': content,
                'patterns': []
            }

            # 检测各种腐败模式
            for pattern_name, pattern_info in self.CORRUPTION_PATTERNS.items():
                for keyword in pattern_info['keywords']:
                    if keyword in content:
                        interaction['patterns'].append({
                            'type': pattern_name,
                            'keyword': keyword,
                            'weight': pattern_info['weight']
                        })

                        # 更新人物可疑分数
                        self.persons[sender]['suspicious_score'] += pattern_info['weight']
                        if pattern_name == 'fund_transfer':
                            self.persons[sender]['behavior_patterns']['fund_out'] += 1
                            self.persons[receiver]['behavior_patterns']['fund_in'] += 1
                        elif pattern_name == 'information_leak':
                            self.persons[sender]['behavior_patterns']['info_leak'] += 1

                        break

            # 提取金额信息
            amounts = self.extract_amounts(content)
            if amounts:
                interaction['amounts'] = amounts
                for amt in amounts:
                    if '回扣' in content or '好处' in content or '转账' in content:
                        self.relationships[rel_key]['fund_transfers'].append({
                            'amount': amt,
                            'from': sender if '转' in content or '给' in content else receiver,
                            'to': receiver if '转' in content or '给' in content else sender,
                            'time': msg['time'],
                            'context': content
                        })

            # 检测信息泄露方向
            if any(p['type'] == 'information_leak' for p in interaction['patterns']):
                self.relationships[rel_key]['info_leaks'].append({
                    'leaker': sender,
                    'receiver': receiver,
                    'time': msg['time'],
                    'content': content
                })

            if interaction['patterns']:
                self.relationships[rel_key]['interactions'].append(interaction)
                self.relationships[rel_key]['suspicious_count'] += 1

            self.timeline.append(interaction)

    def extract_amounts(self, text):
        """提取金额数字"""
        amounts = []

        # 匹配 "X万"、"X万元"、"X元" 等格式
        patterns = [
            r'(\d+\.?\d*)\s*万\s*(?:元|块)?',
            r'(\d+\.?\d*)\s*千\s*(?:元|块)?',
            r'(\d{4,})\s*(?:元|块)',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                try:
                    val = float(match)
                    if '万' in text[text.find(match):text.find(match)+10]:
                        val *= 10000
                    elif '千' in text[text.find(match):text.find(match)+10]:
                        val *= 1000
                    amounts.append(val)
                except:
                    pass

        return amounts

    def identify_intermediaries(self):
        """识别中间人角色"""
        intermediaries = []

        for person, info in self.persons.items():
            # 中间人特征：
            # 1. 连接多个不直接相连的人
            # 2. 在多方对话中出现
            # 3. 提及"介绍"、"帮忙"等词

            connections = info['connections']
            if len(connections) >= 3:
                # 检查是否连接了原本不相连的群体
                intermediary_score = len(connections) * 10

                # 检查行为模式
                if info['behavior_patterns'].get('info_leak', 0) > 0:
                    intermediary_score += 20

                if intermediary_score > 30:
                    info['roles'].add('intermediary')
                    intermediaries.append({
                        'name': person,
                        'score': intermediary_score,
                        'connections': list(connections)
                    })

        return intermediaries

    def detect_groups(self):
        """检测群体/圈子（社区发现简化版）"""
        # 基于共同联系人和共同活动检测群体
        groups = []

        # 找出有共同联系人的群体
        for person1, info1 in self.persons.items():
            for person2, info2 in self.persons.items():
                if person1 >= person2:
                    continue

                common_connections = info1['connections'] & info2['connections']
                if len(common_connections) >= 2:
                    # 检查是否有共同的腐败活动
                    common_suspicious = False
                    for conn in common_connections:
                        rel1 = tuple(sorted([person1, conn]))
                        rel2 = tuple(sorted([person2, conn]))
                        if (rel1 in self.relationships and
                            rel2 in self.relationships and
                            self.relationships[rel1]['suspicious_count'] > 0 and
                            self.relationships[rel2]['suspicious_count'] > 0):
                            common_suspicious = True
                            break

                    if common_suspicious:
                        group_members = {person1, person2} | common_connections
                        groups.append({
                            'members': list(group_members),
                            'type': 'corruption_network',
                            'common_target': list(common_connections)[0] if common_connections else None
                        })

        # 去重
        unique_groups = []
        for g in groups:
            if not any(set(g['members']) == set(ug['members']) for ug in unique_groups):
                unique_groups.append(g)

        self.groups = unique_groups
        return unique_groups

    def analyze_directionality(self):
        """分析关系方向性（行贿 vs 受贿）"""
        directed_relationships = {}

        for rel_key, rel_info in self.relationships.items():
            if rel_info['suspicious_count'] == 0:
                continue

            person1, person2 = rel_key

            # 分析资金流向
            fund_direction = {'p1_to_p2': 0, 'p2_to_p1': 0}
            for transfer in rel_info['fund_transfers']:
                if transfer['from'] == person1:
                    fund_direction['p1_to_p2'] += transfer['amount']
                else:
                    fund_direction['p2_to_p1'] += transfer['amount']

            # 分析信息流向
            info_direction = {'p1_to_p2': 0, 'p2_to_p1': 0}
            for leak in rel_info['info_leaks']:
                if leak['leaker'] == person1:
                    info_direction['p1_to_p2'] += 1
                else:
                    info_direction['p2_to_p1'] += 1

            # 确定主导方向
            dominant_direction = None
            if fund_direction['p1_to_p2'] > fund_direction['p2_to_p1']:
                dominant_direction = (person1, person2, 'bribery')
            elif fund_direction['p2_to_p1'] > fund_direction['p1_to_p2']:
                dominant_direction = (person2, person1, 'bribery')
            elif info_direction['p1_to_p2'] > info_direction['p2_to_p1']:
                dominant_direction = (person1, person2, 'info_leak')
            elif info_direction['p2_to_p1'] > info_direction['p1_to_p2']:
                dominant_direction = (person2, person1, 'info_leak')

            directed_relationships[rel_key] = {
                'fund_flow': fund_direction,
                'info_flow': info_direction,
                'dominant_direction': dominant_direction,
                'total_interactions': len(rel_info['interactions'])
            }

        return directed_relationships

    def calculate_relationship_risk(self, rel_key, directed_info):
        """计算关系风险分数"""
        rel_info = self.relationships[rel_key]
        base_score = min(rel_info['suspicious_count'] * 2, 30)

        # 资金流动加分
        fund_score = 0
        for transfer in rel_info['fund_transfers']:
            amt = transfer['amount']
            if amt >= 100000:
                fund_score += 15
            elif amt >= 50000:
                fund_score += 10
            elif amt >= 10000:
                fund_score += 5

        # 信息泄露加分
        info_score = len(rel_info['info_leaks']) * 8

        # 互动频率加分
        frequency_score = min(len(rel_info['interactions']) * 2, 20)

        total_score = min(base_score + fund_score + info_score + frequency_score, 100)

        return {
            'score': total_score,
            'level': 'high' if total_score >= 70 else 'medium' if total_score >= 40 else 'low',
            'breakdown': {
                'suspicious_activity': base_score,
                'fund_transfer': fund_score,
                'info_leak': info_score,
                'frequency': frequency_score
            }
        }

    def generate_report(self):
        """生成分析报告"""
        parsed = self.parse_messages()
        self.identify_roles(parsed)
        self.detect_corruption_patterns(parsed)
        intermediaries = self.identify_intermediaries()
        groups = self.detect_groups()
        directed = self.analyze_directionality()

        # 计算关系风险
        relationship_risks = {}
        for rel_key, dir_info in directed.items():
            relationship_risks[rel_key] = self.calculate_relationship_risk(rel_key, dir_info)
            relationship_risks[rel_key]['direction'] = dir_info['dominant_direction']
            relationship_risks[rel_key]['fund_transfers'] = self.relationships[rel_key]['fund_transfers']
            relationship_risks[rel_key]['info_leaks'] = self.relationships[rel_key]['info_leaks']

        # 识别人物风险
        person_risks = {}
        for person, info in self.persons.items():
            # 基于可疑分数、连接数、资金流动计算
            risk_score = info['suspicious_score']
            risk_score += len(info['connections']) * 3
            risk_score += info['behavior_patterns'].get('fund_in', 0) * 10
            risk_score += info['behavior_patterns'].get('fund_out', 0) * 10
            risk_score += info['behavior_patterns'].get('info_leak', 0) * 8

            person_risks[person] = {
                'score': min(risk_score, 100),
                'level': 'high' if risk_score >= 60 else 'medium' if risk_score >= 30 else 'low',
                'roles': list(info['roles']),
                'connections': list(info['connections']),
                'behavior_summary': dict(info['behavior_patterns'])
            }

        # 构建时间线
        timeline_events = []
        for msg in self.timeline:
            if msg['patterns']:
                timeline_events.append({
                    'time': msg['time'],
                    'participants': [msg['sender'], msg['receiver']],
                    'type': msg['patterns'][0]['type'],
                    'content': msg['content'][:100] + '...' if len(msg['content']) > 100 else msg['content']
                })

        return {
            'summary': {
                'total_messages': len(parsed),
                'suspicious_messages': len([t for t in self.timeline if t['patterns']]),
                'total_persons': len(self.persons),
                'high_risk_relationships': len([r for r in relationship_risks.values() if r['level'] == 'high']),
                'corruption_networks': len(groups)
            },
            'persons': person_risks,
            'relationships': relationship_risks,
            'intermediaries': intermediaries,
            'groups': groups,
            'timeline': sorted(timeline_events, key=lambda x: x['time'])
        }


def main():
    """主函数"""
    # 读取数据
    input_file = "/workspace/input/chat_records.jsonl"

    messages = []
    with open(input_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    messages.append(json.loads(line))
                except:
                    messages.append({'content': line})

    # 分析
    analyzer = ImprovedCorruptionAnalyzer(messages)
    report = analyzer.generate_report()

    # 输出报告
    print("=" * 80)
    print("🔍 改进版反腐败社会关系分析报告")
    print("=" * 80)

    print(f"\n📊 总体统计")
    print(f"  - 总消息数: {report['summary']['total_messages']}")
    print(f"  - 可疑消息: {report['summary']['suspicious_messages']}")
    print(f"  - 涉及人数: {report['summary']['total_persons']}")
    print(f"  - 高风险关系: {report['summary']['high_risk_relationships']}")
    print(f"  - 腐败网络: {report['summary']['corruption_networks']}")

    print(f"\n" + "=" * 80)
    print("👥 人物风险画像")
    print("=" * 80)

    sorted_persons = sorted(report['persons'].items(),
                           key=lambda x: x[1]['score'], reverse=True)

    for person, info in sorted_persons:
        level_emoji = '🔴' if info['level'] == 'high' else '🟠' if info['level'] == 'medium' else '🟢'
        print(f"\n{level_emoji} {person} (风险分: {info['score']})")
        print(f"   角色: {', '.join(info['roles']) if info['roles'] else '未识别'}")
        print(f"   关联人物: {', '.join(info['connections'])}")
        if info['behavior_summary']:
            print(f"   行为特征: {info['behavior_summary']}")

    print(f"\n" + "=" * 80)
    print("🔗 社会关系分析")
    print("=" * 80)

    sorted_rels = sorted(report['relationships'].items(),
                        key=lambda x: x[1]['score'], reverse=True)

    for rel_key, info in sorted_rels:
        if info['level'] == 'low':
            continue

        p1, p2 = rel_key
        level_emoji = '🔴' if info['level'] == 'high' else '🟠'

        print(f"\n{level_emoji} {p1} ↔ {p2} (风险分: {info['score']})")

        if info['direction']:
            src, dst, rel_type = info['direction']
            rel_type_str = '行贿' if rel_type == 'bribery' else '信息泄露'
            print(f"   关系方向: {src} → {dst} ({rel_type_str})")

        if info['fund_transfers']:
            print(f"   资金往来:")
            for ft in info['fund_transfers']:
                print(f"     - {ft['from']} → {ft['to']}: {ft['amount']/10000:.2f}万元")

        if info['info_leaks']:
            print(f"   信息泄露:")
            for il in info['info_leaks']:
                print(f"     - {il['leaker']} 向 {il['receiver']} 泄露信息")

    print(f"\n" + "=" * 80)
    print("🕸️ 腐败网络/圈子")
    print("=" * 80)

    for i, group in enumerate(report['groups'], 1):
        print(f"\n网络 {i}: {', '.join(group['members'])}")
        print(f"   类型: {group['type']}")
        if group['common_target']:
            print(f"   共同目标/中介: {group['common_target']}")

    print(f"\n" + "=" * 80)
    print("🕒 关键时间线")
    print("=" * 80)

    for event in report['timeline'][:20]:  # 显示前20个事件
        type_emoji = {
            'fund_transfer': '💰',
            'information_leak': '📢',
            'collusion': '🤝',
            'power_abuse': '⚡',
            'secret_meeting': '📍'
        }.get(event['type'], '⚠️')

        print(f"\n{type_emoji} [{event['time']}] {', '.join(event['participants'])}")
        print(f"   {event['content']}")

    # 保存详细报告
    output_dir = Path("/workspace/output/corruption_analysis")
    output_dir.mkdir(parents=True, exist_ok=True)

    with open(output_dir / "improved_analysis.json", 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n\n✅ 详细报告已保存至: {output_dir / 'improved_analysis.json'}")


if __name__ == "__main__":
    main()
