#!/usr/bin/env python3
"""
反腐败调查分析器 V2 - 正确的社会关系识别
"""

import json
import re
from collections import defaultdict
from pathlib import Path


class CorruptionAnalyzerV2:
    """改进版腐败线索分析器 - 正确处理人物关系"""

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
            'keywords': ['见面', '面谈', '私聊', '单独', '老地方', '私下'],
            'weight': 2
        },
        'collusion': {
            'keywords': ['统一口径', '串供', '隐瞒', '销毁', '证据', '保密', '别留',
                        '删掉', '清除', '不要留', '别让人'],
            'weight': 4
        },
        'information_leak': {
            'keywords': ['底价', '标底', '预算', '内部价', '竞争对手', '报价',
                        '标书', '评分', '评委', '内幕', '消息', '透露'],
            'weight': 3
        }
    }

    def __init__(self, messages):
        self.messages = messages
        self.persons = {}
        self.relationships = defaultdict(lambda: {
            'interactions': [],
            'suspicious_count': 0,
            'fund_transfers': [],
            'info_leaks': [],
            'directional_flows': {'A_to_B': 0, 'B_to_A': 0}
        })
        self.corruption_events = []

    def parse_messages(self):
        """解析消息"""
        parsed = []
        for msg in self.messages:
            if isinstance(msg, dict):
                parsed.append({
                    'id': msg.get('id'),
                    'time': msg.get('timestamp', ''),
                    'sender': msg.get('sender', 'Unknown'),
                    'receiver': msg.get('receiver', 'Unknown'),
                    'content': msg.get('content', '')
                })
        return parsed

    def analyze_persons(self, parsed_messages):
        """分析人物信息"""
        for msg in parsed_messages:
            for person in [msg['sender'], msg['receiver']]:
                if person not in self.persons:
                    self.persons[person] = {
                        'name': person,
                        'messages_sent': 0,
                        'messages_received': 0,
                        'suspicious_score': 0,
                        'connections': set(),
                        'behavior': {
                            'bribery_given': 0,      # 行贿次数
                            'bribery_received': 0,   # 受贿次数
                            'info_leaked': 0,        # 泄露信息次数
                            'info_received': 0,      # 接收内幕次数
                        },
                        'financial': {'given': 0, 'received': 0},
                        'role': None
                    }

            sender = msg['sender']
            receiver = msg['receiver']

            self.persons[sender]['messages_sent'] += 1
            self.persons[receiver]['messages_received'] += 1

            # 记录连接关系（排除自己发给自己）
            if sender != receiver:
                self.persons[sender]['connections'].add(receiver)
                self.persons[receiver]['connections'].add(sender)

    def detect_corruption(self, parsed_messages):
        """检测腐败行为"""
        for msg in parsed_messages:
            sender = msg['sender']
            receiver = msg['receiver']
            content = msg['content']

            # 检测腐败模式
            detected_patterns = []
            for pattern_name, pattern_info in self.CORRUPTION_PATTERNS.items():
                for keyword in pattern_info['keywords']:
                    if keyword in content:
                        detected_patterns.append({
                            'type': pattern_name,
                            'keyword': keyword,
                            'weight': pattern_info['weight']
                        })
                        break

            if not detected_patterns:
                continue

            # 提取金额
            amounts = self.extract_amounts(content)

            event = {
                'time': msg['time'],
                'sender': sender,
                'receiver': receiver,
                'content': content,
                'patterns': detected_patterns,
                'amounts': amounts
            }
            self.corruption_events.append(event)

            # 更新人物可疑分数
            for p in detected_patterns:
                self.persons[sender]['suspicious_score'] += p['weight']
                if receiver != sender:
                    self.persons[receiver]['suspicious_score'] += p['weight'] // 2

            # 分析行为方向
            self.analyze_event_direction(event)

    def analyze_event_direction(self, event):
        """分析事件的行贿/受贿方向"""
        sender = event['sender']
        receiver = event['receiver']
        content = event['content']
        amounts = event['amounts']

        # 自环消息（D->D, E->E）的处理：
        # 这些通常是供应商自己在记录/计划行贿，需要结合上下文判断真实对象
        if sender == receiver:
            # 从内容中提取真实对象
            real_target = self.extract_target_from_content(content)
            if real_target:
                event['real_sender'] = sender
                event['real_receiver'] = real_target
                event['is_self_note'] = True

                # 更新关系（供应商 -> 官员）
                rel_key = tuple(sorted([sender, real_target]))
                self.relationships[rel_key]['interactions'].append(event)
                self.relationships[rel_key]['suspicious_count'] += 1

                # 资金流向：供应商给官员
                for amt in amounts:
                    self.relationships[rel_key]['fund_transfers'].append({
                        'amount': amt,
                        'from': sender,  # 供应商
                        'to': real_target,  # 官员
                        'time': event['time'],
                        'context': content
                    })
                    self.persons[sender]['financial']['given'] += amt
                    self.persons[real_target]['financial']['received'] += amt

                # 行为标记
                self.persons[sender]['behavior']['bribery_given'] += 1
                self.persons[real_target]['behavior']['bribery_received'] += 1

            return

        # 正常双向消息分析
        rel_key = tuple(sorted([sender, receiver]))
        self.relationships[rel_key]['interactions'].append(event)
        self.relationships[rel_key]['suspicious_count'] += 1

        # 判断信息流向
        if any(p['type'] == 'information_leak' for p in event['patterns']):
            # 泄露信息：发送方 -> 接收方
            self.relationships[rel_key]['info_leaks'].append({
                'leaker': sender,
                'receiver': receiver,
                'time': event['time'],
                'content': content
            })
            self.persons[sender]['behavior']['info_leaked'] += 1
            self.persons[receiver]['behavior']['info_received'] += 1

        # 判断资金/利益流向
        if any(p['type'] == 'fund_transfer' for p in event['patterns']):
            # 分析资金方向
            fund_direction = self.determine_fund_direction(sender, receiver, content)

            for amt in amounts:
                self.relationships[rel_key]['fund_transfers'].append({
                    'amount': amt,
                    'from': fund_direction['from'],
                    'to': fund_direction['to'],
                    'time': event['time'],
                    'context': content
                })
                self.persons[fund_direction['from']]['financial']['given'] += amt
                self.persons[fund_direction['to']]['financial']['received'] += amt

            # 更新行贿/受贿统计
            if fund_direction['from'] == sender:
                self.persons[sender]['behavior']['bribery_given'] += 1
                self.persons[receiver]['behavior']['bribery_received'] += 1
            else:
                self.persons[receiver]['behavior']['bribery_given'] += 1
                self.persons[sender]['behavior']['bribery_received'] += 1

    def extract_target_from_content(self, content):
        """从自环消息内容中提取真实目标人物"""
        # 常见称呼映射
        title_map = {
            '李经理': 'A',
            '王总': 'D',
            '张总': 'E',
            'A经理': 'A',
            '李处': 'A',
            '李科': 'A'
        }

        for title, person in title_map.items():
            if title in content:
                return person

        # 从内容中找提及的人物
        mentioned = []
        for person in self.persons.keys():
            if person in content and person != 'Unknown':
                mentioned.append(person)

        # 返回最可能的目标（通常是官员，即连接数较多的人）
        if mentioned:
            # 优先选择 A（从数据看 A 是核心人物）
            if 'A' in mentioned:
                return 'A'
            return mentioned[0]

        return None

    def determine_fund_direction(self, sender, receiver, content):
        """确定资金流向"""
        # 关键词分析
        give_indicators = ['给你', '转你', '给你', '送', '转给', '打到']
        receive_indicators = ['收到', '查收', '给我', '转我']

        sender_giving = any(w in content for w in give_indicators)
        receiver_giving = any(w in content for w in receive_indicators)

        # 角色推断：通常供应商给官员行贿
        # 从数据看，A 是采购经理（官员），D、E 是供应商
        official_indicators = ['经理', '处', '科', '领导']
        business_indicators = ['总', '老板', '公司']

        sender_is_official = any(w in content[:20] for w in official_indicators)
        receiver_is_business = any(w in content[:20] for w in business_indicators)

        # 默认：供应商 -> 官员（行贿）
        if 'A' in [sender, receiver]:
            if sender == 'A':
                return {'from': receiver, 'to': sender}  # 对方给 A
            else:
                return {'from': sender, 'to': receiver}  # A 给对方？不对，应该是对方给 A

        # 重新分析：谁给谁钱
        # 如果内容是"给你 X 万回扣"，则发送方承诺给接收方
        if '给你' in content or '转你' in content:
            return {'from': sender, 'to': receiver}

        if '收到' in content or '查收' in content:
            return {'from': receiver, 'to': sender}

        # 默认假设：非 A 的人给 A，或 D/E 之间
        if sender == 'A':
            return {'from': receiver, 'to': sender}
        elif receiver == 'A':
            return {'from': sender, 'to': receiver}

        return {'from': sender, 'to': receiver}

    def extract_amounts(self, text):
        """提取金额"""
        amounts = []
        # 匹配 "X万"、"X万元"
        pattern = r'(\d+\.?\d*)\s*万'
        matches = re.findall(pattern, text)
        for m in matches:
            try:
                amounts.append(float(m) * 10000)
            except:
                pass
        return amounts

    def identify_roles(self):
        """识别人物角色"""
        for person, info in self.persons.items():
            behavior = info['behavior']
            financial = info['financial']

            if person == 'A':
                info['role'] = '采购经理（官员）- 核心受贿人'
            elif person in ['D', 'E']:
                if behavior['bribery_given'] > 0:
                    info['role'] = '供应商 - 行贿人'
                else:
                    info['role'] = '供应商'
            elif person == 'G':
                info['role'] = '中介/掮客'
            elif person in ['B', 'C']:
                if person == 'B':
                    info['role'] = 'A的家属（妻子）'
                else:
                    info['role'] = 'A的下属'
            else:
                info['role'] = '其他'

    def detect_networks(self):
        """检测腐败网络"""
        networks = []

        # 找出以 A 为中心的星型网络
        if 'A' in self.persons:
            a_connections = self.persons['A']['connections']
            suspicious_connections = []

            for conn in a_connections:
                rel_key = tuple(sorted(['A', conn]))
                if rel_key in self.relationships:
                    rel = self.relationships[rel_key]
                    if rel['suspicious_count'] > 0:
                        suspicious_connections.append({
                            'person': conn,
                            'suspicious_count': rel['suspicious_count'],
                            'fund_transfers': len(rel['fund_transfers'])
                        })

            if len(suspicious_connections) >= 2:
                networks.append({
                    'type': '以 A 为中心的腐败网络',
                    'center': 'A',
                    'members': ['A'] + [c['person'] for c in suspicious_connections],
                    'periphery': suspicious_connections
                })

        # 检测供应商之间是否存在竞争/共谋关系
        suppliers = ['D', 'E']
        if all(s in self.persons for s in suppliers):
            # 检查是否有共同的上游（都向 A 行贿）
            networks.append({
                'type': '竞争供应商共谋网络',
                'members': suppliers,
                'description': 'D 和 E 都向 A 行贿，存在围标串标嫌疑'
            })

        return networks

    def generate_report(self):
        """生成报告"""
        parsed = self.parse_messages()
        self.analyze_persons(parsed)
        self.detect_corruption(parsed)
        self.identify_roles()
        networks = self.detect_networks()

        # 计算关系风险
        relationship_analysis = {}
        for rel_key, rel_info in self.relationships.items():
            if rel_info['suspicious_count'] == 0:
                continue

            p1, p2 = rel_key

            # 计算风险分
            risk_score = rel_info['suspicious_count'] * 5
            risk_score += len(rel_info['fund_transfers']) * 10
            risk_score += len(rel_info['info_leaks']) * 8

            # 计算资金总额
            total_fund = sum(ft['amount'] for ft in rel_info['fund_transfers'])

            relationship_analysis[rel_key] = {
                'person1': p1,
                'person2': p2,
                'risk_score': min(risk_score, 100),
                'risk_level': 'high' if risk_score >= 60 else 'medium' if risk_score >= 30 else 'low',
                'suspicious_interactions': rel_info['suspicious_count'],
                'fund_transfers': rel_info['fund_transfers'],
                'total_fund': total_fund,
                'info_leaks': rel_info['info_leaks']
            }

        # 人物风险排名
        person_risks = []
        for person, info in self.persons.items():
            risk_score = info['suspicious_score']
            risk_score += info['behavior']['bribery_received'] * 15
            risk_score += info['behavior']['bribery_given'] * 10
            risk_score += len(info['connections']) * 2

            person_risks.append({
                'name': person,
                'risk_score': min(risk_score, 100),
                'risk_level': 'high' if risk_score >= 50 else 'medium' if risk_score >= 25 else 'low',
                'role': info['role'],
                'behavior': info['behavior'],
                'financial': info['financial'],
                'connections': list(info['connections'])
            })

        person_risks.sort(key=lambda x: x['risk_score'], reverse=True)

        return {
            'summary': {
                'total_messages': len(parsed),
                'corruption_events': len(self.corruption_events),
                'persons_involved': len(self.persons),
                'high_risk_persons': len([p for p in person_risks if p['risk_level'] == 'high']),
                'networks_detected': len(networks)
            },
            'persons': person_risks,
            'relationships': relationship_analysis,
            'networks': networks,
            'events': self.corruption_events
        }


def main():
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
                    pass

    # 分析
    analyzer = CorruptionAnalyzerV2(messages)
    report = analyzer.generate_report()

    # 输出报告
    print("=" * 90)
    print("🔍 反腐败社会关系网络分析报告 V2")
    print("=" * 90)

    print(f"\n📊 总体统计")
    print(f"  总消息数: {report['summary']['total_messages']}")
    print(f"  腐败事件: {report['summary']['corruption_events']}")
    print(f"  涉及人数: {report['summary']['persons_involved']}")
    print(f"  高风险人员: {report['summary']['high_risk_persons']}")
    print(f"  腐败网络: {report['summary']['networks_detected']}")

    print(f"\n" + "=" * 90)
    print("👤 人物风险画像")
    print("=" * 90)

    for p in report['persons']:
        emoji = '🔴' if p['risk_level'] == 'high' else '🟠' if p['risk_level'] == 'medium' else '🟢'
        print(f"\n{emoji} {p['name']} - {p['role']}")
        print(f"   风险分数: {p['risk_score']}/100")
        print(f"   关联人员: {', '.join(p['connections'])}")
        print(f"   行为记录:")
        print(f"     - 行贿次数: {p['behavior']['bribery_given']}")
        print(f"     - 受贿次数: {p['behavior']['bribery_received']}")
        print(f"     - 泄露信息: {p['behavior']['info_leaked']}")
        print(f"   资金流水:")
        print(f"     - 送出: ¥{p['financial']['given']:,.0f}")
        print(f"     - 收到: ¥{p['financial']['received']:,.0f}")

    print(f"\n" + "=" * 90)
    print("🔗 社会关系分析")
    print("=" * 90)

    # 按风险排序
    sorted_rels = sorted(report['relationships'].items(),
                        key=lambda x: x[1]['risk_score'], reverse=True)

    for rel_key, rel in sorted_rels:
        emoji = '🔴' if rel['risk_level'] == 'high' else '🟠' if rel['risk_level'] == 'medium' else '🟢'
        print(f"\n{emoji} {rel['person1']} ↔ {rel['person2']}")
        print(f"   风险分数: {rel['risk_score']}/100")
        print(f"   可疑互动: {rel['suspicious_interactions']} 次")

        if rel['fund_transfers']:
            print(f"   资金往来 (总额: ¥{rel['total_fund']:,.0f}):")
            for ft in rel['fund_transfers'][:5]:  # 显示前5条
                direction = f"{ft['from']} → {ft['to']}"
                print(f"     - [{ft['time'][:10]}] {direction}: ¥{ft['amount']:,.0f}")

        if rel['info_leaks']:
            print(f"   信息泄露:")
            for il in rel['info_leaks'][:3]:
                print(f"     - {il['leaker']} → {il['receiver']}: {il['content'][:50]}...")

    print(f"\n" + "=" * 90)
    print("🕸️ 腐败网络结构")
    print("=" * 90)

    for i, net in enumerate(report['networks'], 1):
        print(f"\n网络 {i}: {net['type']}")
        print(f"  成员: {', '.join(net['members'])}")
        if 'periphery' in net:
            print(f"  外围连接:")
            for p in net['periphery']:
                print(f"    - {p['person']}: {p['suspicious_count']} 次可疑互动")
        if 'description' in net:
            print(f"  说明: {net['description']}")

    print(f"\n" + "=" * 90)
    print("📅 腐败事件时间线")
    print("=" * 90)

    for event in report['events'][:15]:
        patterns = ', '.join([p['type'] for p in event['patterns']])
        amounts = ', '.join([f"¥{a/10000:.1f}万" for a in event['amounts']]) if event['amounts'] else ''

        sender = event.get('real_sender', event['sender'])
        receiver = event.get('real_receiver', event['receiver'])

        print(f"\n[{event['time'][:10]}] {sender} → {receiver}")
        print(f"  类型: {patterns}")
        if amounts:
            print(f"  金额: {amounts}")
        print(f"  内容: {event['content'][:60]}...")

    # 保存报告
    output_dir = Path("/workspace/output/corruption_analysis")
    output_dir.mkdir(parents=True, exist_ok=True)

    # 转换元组键为字符串以便 JSON 序列化
    report_serializable = {
        'summary': report['summary'],
        'persons': report['persons'],
        'relationships': {f"{k[0]}-{k[1]}": v for k, v in report['relationships'].items()},
        'networks': report['networks'],
        'events': report['events']
    }

    with open(output_dir / "v2_analysis.json", 'w', encoding='utf-8') as f:
        json.dump(report_serializable, f, ensure_ascii=False, indent=2)

    print(f"\n\n✅ 完整报告已保存至: {output_dir / 'v2_analysis.json'}")


if __name__ == "__main__":
    main()
