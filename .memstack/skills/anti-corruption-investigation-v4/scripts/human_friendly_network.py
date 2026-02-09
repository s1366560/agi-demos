#!/usr/bin/env python3
"""
人类友好的关系网络分析器
专注于：谁和谁是什么关系，证据是什么
"""

import json
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Tuple, Any
import os


class HumanFriendlyNetworkAnalyzer:
    """人类友好的关系网络分析器"""
    
    def __init__(self):
        self.relationship_types = {
            'financial': '资金往来',
            'abuse_of_power': '权力滥用',
            'secret_meeting': '秘密会面',
            'collusion': '串通勾结',
            'evidence_destruction': '证据销毁',
            'frequent_contact': '频繁联系',
            'anomaly_contact': '异常联系'
        }
        
        # 关系强度阈值
        self.strength_thresholds = {
            'very_high': 0.8,    # 非常强关系
            'high': 0.6,         # 强关系
            'medium': 0.4,       # 中等关系
            'low': 0.2           # 弱关系
        }
        
    def analyze_friendly_network(self, messages_file: str, output_file: str = None):
        """分析人类友好的关系网络"""
        
        print("🔍 开始分析人类友好的关系网络...")
        
        # 1. 加载消息
        messages = self._load_messages(messages_file)
        print(f"📊 加载了 {len(messages)} 条消息")
        
        # 2. 构建关系网络
        relationships = self._build_relationships(messages)
        print(f"🕸️ 构建了 {len(relationships)} 个关系")
        
        # 3. 提取关键关系
        key_relationships = self._extract_key_relationships(relationships, messages)
        print(f"🎯 识别了 {len(key_relationships)} 个关键关系")
        
        # 4. 生成人类友好的报告
        report = self._generate_friendly_report(key_relationships, messages)
        
        # 5. 保存报告
        if output_file:
            self._save_report(report, output_file)
            print(f"✅ 报告已保存到: {output_file}")
        
        # 6. 打印摘要
        self._print_summary(report)
        
        return report
    
    def _load_messages(self, messages_file: str) -> List[Dict]:
        """加载消息数据"""
        messages = []
        
        try:
            with open(messages_file, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    try:
                        msg = json.loads(line.strip())
                        messages.append(msg)
                    except json.JSONDecodeError:
                        continue
                        
        except Exception as e:
            print(f"❌ 加载消息失败: {e}")
            return []
        
        return messages
    
    def _build_relationships(self, messages: List[Dict]) -> Dict:
        """构建关系网络"""
        
        relationships = defaultdict(lambda: {
            'count': 0,
            'types': defaultdict(int),
            'evidence': [],
            'strength': 0.0,
            'first_contact': None,
            'last_contact': None,
            'time_patterns': defaultdict(int)
        })
        
        for msg in messages:
            sender = msg.get('sender', 'Unknown')
            receiver = msg.get('receiver', 'Unknown')
            
            if sender == 'Unknown' or receiver == 'Unknown':
                continue
            
            # 创建关系键（按字母顺序，避免重复）
            key = tuple(sorted([sender, receiver]))
            
            # 更新关系统计
            relationships[key]['count'] += 1
            
            # 提取时间模式
            timestamp = msg.get('timestamp', '')
            if timestamp:
                hour = self._extract_hour(timestamp)
                if hour:
                    relationships[key]['time_patterns'][hour] += 1
            
            # 记录首次和最后联系
            if relationships[key]['first_contact'] is None:
                relationships[key]['first_contact'] = timestamp
            relationships[key]['last_contact'] = timestamp
            
            # 提取关系类型
            content = msg.get('content', '').lower()
            rel_types = self._classify_relationship(content)
            
            for rel_type in rel_types:
                relationships[key]['types'][rel_type] += 1
            
            # 添加证据
            evidence = {
                'timestamp': timestamp,
                'content': msg.get('content', ''),
                'sender': sender,
                'receiver': receiver,
                'types': rel_types
            }
            
            # 只保留重要的证据（最多20条）
            if len(relationships[key]['evidence']) < 20:
                relationships[key]['evidence'].append(evidence)
        
        # 计算关系强度
        for key, rel in relationships.items():
            rel['strength'] = self._calculate_strength(rel)
        
        return relationships
    
    def _classify_relationship(self, content: str) -> List[str]:
        """分类关系类型"""
        
        types = []
        
        # 资金往来关键词
        financial_keywords = ['钱', '款', '账', '转账', '汇款', '付款', '结算', '回扣', 
                            '贿赂', '好处费', '提成', '佣金', '分成', '资金']
        if any(kw in content for kw in financial_keywords):
            types.append('financial')
        
        # 权力滥用关键词
        abuse_keywords = ['特殊', '照顾', '方便', '通融', '违规', '按规矩', '老规矩',
                         '打招呼', '安排', '批示', '审批', '绿灯']
        if any(kw in content for kw in abuse_keywords):
            types.append('abuse_of_power')
        
        # 秘密会面关键词
        secret_keywords = ['私下', '保密', '秘密', '别告诉', '只有我们知道',
                          '老地方', '单独', '密谈', '不见外']
        if any(kw in content for kw in secret_keywords):
            types.append('secret_meeting')
        
        # 串通勾结关键词
        collusion_keywords = ['统一口径', '保持一致', '配合', '协作', '一起',
                            '商量好', '说好的', '按计划', '准备好了']
        if any(kw in content for kw in collusion_keywords):
            types.append('collusion')
        
        # 证据销毁关键词
        destruction_keywords = ['删除', '清除', '销毁', '清理', '不留痕迹',
                              '处理掉', '抹掉', '消失']
        if any(kw in content for kw in destruction_keywords):
            types.append('evidence_destruction')
        
        # 如果没有特定类型，标记为频繁联系
        if not types:
            types.append('frequent_contact')
        
        return types
    
    def _calculate_strength(self, rel: Dict) -> float:
        """计算关系强度"""
        
        # 基础强度：联系次数
        strength = min(rel['count'] / 100.0, 1.0) * 0.4
        
        # 类型强度：特殊关系类型加分
        type_weights = {
            'financial': 0.3,
            'abuse_of_power': 0.25,
            'secret_meeting': 0.2,
            'collusion': 0.15,
            'evidence_destruction': 0.2,
            'frequent_contact': 0.05
        }
        
        for type_name, count in rel['types'].items():
            weight = type_weights.get(type_name, 0.05)
            strength += min(count / 10.0, 1.0) * weight
        
        # 异常时间加分
        abnormal_hours = [h for h, count in rel['time_patterns'].items()
                         if 22 <= int(h) <= 24 or 0 <= int(h) <= 6]
        if abnormal_hours:
            strength += 0.1
        
        return min(strength, 1.0)
    
    def _extract_key_relationships(self, relationships: Dict, messages: List[Dict]) -> List[Dict]:
        """提取关键关系"""
        
        # 按强度排序
        sorted_rels = sorted(
            relationships.items(),
            key=lambda x: x[1]['strength'],
            reverse=True
        )
        
        # 只保留强关系（强度 >= 0.3）
        key_rels = []
        for (person1, person2), rel_data in sorted_rels:
            if rel_data['strength'] >= 0.3:
                key_rels.append({
                    'person1': person1,
                    'person2': person2,
                    'data': rel_data
                })
        
        # 最多返回50个关键关系
        return key_rels[:50]
    
    def _generate_friendly_report(self, key_relationships: List[Dict], 
                                  messages: List[Dict]) -> Dict:
        """生成人类友好的报告"""
        
        report = {
            'summary': {
                'total_relationships': len(key_relationships),
                'total_messages': len(messages),
                'generation_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            },
            'key_relationships': []
        }
        
        for rel in key_relationships:
            person1 = rel['person1']
            person2 = rel['person2']
            data = rel['data']
            
            # 获取主要关系类型
            main_types = sorted(
                data['types'].items(),
                key=lambda x: x[1],
                reverse=True
            )[:3]
            
            # 转换为中文类型
            type_names = [self.relationship_types.get(t[0], t[0]) for t in main_types]
            
            # 获取关系强度等级
            strength = data['strength']
            if strength >= 0.8:
                strength_level = '非常强'
                emoji = '🔴'
            elif strength >= 0.6:
                strength_level = '强'
                emoji = '🟠'
            elif strength >= 0.4:
                strength_level = '中等'
                emoji = '🟡'
            else:
                strength_level = '弱'
                emoji = '🟢'
            
            # 获取关键证据（最多5条）
            key_evidence = data['evidence'][:5]
            
            # 分析时间模式
            abnormal_contacts = sum(1 for e in key_evidence 
                                   if self._is_abnormal_time(e['timestamp']))
            
            relationship_info = {
                'person1': person1,
                'person2': person2,
                'relationship_types': type_names,
                'strength': strength,
                'strength_level': strength_level,
                'emoji': emoji,
                'contact_count': data['count'],
                'first_contact': data['first_contact'],
                'last_contact': data['last_contact'],
                'abnormal_contacts': abnormal_contacts,
                'key_evidence': key_evidence,
                'risk_assessment': self._assess_risk(data)
            }
            
            report['key_relationships'].append(relationship_info)
        
        return report
    
    def _assess_risk(self, rel_data: Dict) -> str:
        """评估风险等级"""
        
        strength = rel_data['strength']
        
        # 检查高风险类型
        high_risk_types = ['financial', 'abuse_of_power', 'secret_meeting', 
                          'collusion', 'evidence_destruction']
        
        has_high_risk = any(rel_data['types'].get(t, 0) > 0 for t in high_risk_types)
        
        if strength >= 0.7 and has_high_risk:
            return '🔴 高风险 - 需要重点关注'
        elif strength >= 0.5:
            return '🟠 中风险 - 需要关注'
        elif strength >= 0.3:
            return '🟡 低风险 - 正常监控'
        else:
            return '🟢 正常 - 无需特别关注'
    
    def _is_abnormal_time(self, timestamp: str) -> bool:
        """判断是否为异常时间"""
        try:
            hour = self._extract_hour(timestamp)
            if hour and (22 <= int(hour) <= 24 or 0 <= int(hour) <= 6):
                return True
        except:
            pass
        return False
    
    def _extract_hour(self, timestamp: str) -> str:
        """提取小时"""
        try:
            if 'T' in timestamp:
                time_part = timestamp.split('T')[1]
                hour = time_part.split(':')[0]
                return hour
        except:
            pass
        return None
    
    def _save_report(self, report: Dict, output_file: str):
        """保存报告"""
        
        # 保存JSON格式
        json_file = output_file.replace('.txt', '.json')
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        # 保存文本格式
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write("人类友好的关系网络分析报告\n")
            f.write("=" * 80 + "\n\n")
            
            # 摘要
            f.write("📊 分析摘要\n")
            f.write("-" * 80 + "\n")
            f.write(f"总关系数: {report['summary']['total_relationships']}\n")
            f.write(f"总消息数: {report['summary']['total_messages']}\n")
            f.write(f"生成时间: {report['summary']['generation_time']}\n\n")
            
            # 关键关系
            f.write("🔑 关键关系详情\n")
            f.write("=" * 80 + "\n\n")
            
            for i, rel in enumerate(report['key_relationships'], 1):
                f.write(f"关系 #{i}\n")
                f.write("-" * 80 + "\n")
                f.write(f"人物: {rel['person1']} ↔ {rel['person2']}\n")
                f.write(f"关系类型: {', '.join(rel['relationship_types'])}\n")
                f.write(f"关系强度: {rel['emoji']} {rel['strength_level']} ({rel['strength']:.2f})\n")
                f.write(f"联系次数: {rel['contact_count']}次\n")
                f.write(f"异常时间联系: {rel['abnormal_contacts']}次\n")
                f.write(f"首次联系: {rel['first_contact']}\n")
                f.write(f"最后联系: {rel['last_contact']}\n")
                f.write(f"风险评估: {rel['risk_assessment']}\n")
                
                f.write("\n📋 关键证据:\n")
                for j, evidence in enumerate(rel['key_evidence'], 1):
                    f.write(f"\n  证据 #{j}:\n")
                    f.write(f"  时间: {evidence['timestamp']}\n")
                    f.write(f"  发送者: {evidence['sender']}\n")
                    f.write(f"  接收者: {evidence['receiver']}\n")
                    f.write(f"  内容: {evidence['content'][:100]}...\n")
                
                f.write("\n" + "=" * 80 + "\n\n")
    
    def _print_summary(self, report: Dict):
        """打印摘要"""
        
        print("\n" + "=" * 80)
        print("📊 分析摘要")
        print("=" * 80)
        print(f"总关系数: {report['summary']['total_relationships']}")
        print(f"总消息数: {report['summary']['total_messages']}")
        print(f"生成时间: {report['summary']['generation_time']}")
        
        print("\n🔑 Top 10 关键关系:")
        print("-" * 80)
        
        for i, rel in enumerate(report['key_relationships'][:10], 1):
            print(f"\n{i}. {rel['person1']} ↔ {rel['person2']}")
            print(f"   关系: {', '.join(rel['relationship_types'])}")
            print(f"   强度: {rel['emoji']} {rel['strength_level']} ({rel['strength']:.2f})")
            print(f"   联系: {rel['contact_count']}次 | 异常时间: {rel['abnormal_contacts']}次")
            print(f"   风险: {rel['risk_assessment']}")


def main():
    """主函数"""
    import sys
    
    if len(sys.argv) < 2:
        print("用法: python human_friendly_network.py <messages_file> [output_file]")
        print("示例: python human_friendly_network.py data/messages.jsonl report.txt")
        sys.exit(1)
    
    messages_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else 'human_friendly_report.txt'
    
    analyzer = HumanFriendlyNetworkAnalyzer()
    report = analyzer.analyze_friendly_network(messages_file, output_file)


if __name__ == '__main__':
    main()
