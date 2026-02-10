#!/usr/bin/env python3
"""
聊天记录反腐调查分析工具

用于分析聊天记录中的可疑模式、异常行为和潜在腐败线索。
"""

import re
import json
from datetime import datetime
from typing import Dict, List, Any, Tuple
from collections import defaultdict, Counter
import os

class ChatAnalyzer:
    """聊天记录分析器"""

    def __init__(self, chat_file: str):
        """
        初始化分析器

        Args:
            chat_file: 聊天记录文件路径
        """
        self.chat_file = chat_file
        self.messages = []
        self.participants = set()
        self.suspicious_patterns = self._load_patterns()

    def _load_patterns(self) -> Dict[str, List[str]]:
        """加载可疑模式"""
        return {
            'money_keywords': [
                r'\d+[万千百]*[元美金块]',  # 金额
                r'转账|汇款|现金|红包',  # 转账相关
                r'回扣|佣金|好处费',  # 回扣
                r'贿赂|贪|腐败',  # 直接腐败词汇
            ],
            'secret_meeting': [
                r'私下|单独|密谈|保密',
                r'不要告诉|别让.*知道',
                r'删除记录|清空聊天',
                r'加密|暗号',
            ],
            'abnormal_timing': [
                r'深夜|凌晨',
                r'周末|节假日',
                r'非工作时间',
            ],
            'power_abuse': [
                r'帮.*办|给.*安排',
                r'通融|破例|特殊',
                r'关系|面子|人情',
                r'领导|老板|主管',
            ],
            'evidence_concealment': [
                r'销毁|删除|清除',
                r'不留痕迹',
                r'假装|否认',
            ]
        }

    def load_chat_data(self) -> bool:
        """
        加载聊天记录

        支持的格式:
        - JSON: [{sender, content, timestamp}, ...]
        - TXT: 每行一条消息
        """
        try:
            if not os.path.exists(self.chat_file):
                print(f"❌ 文件不存在: {self.chat_file}")
                return False

            with open(self.chat_file, 'r', encoding='utf-8') as f:
                content = f.read().strip()

            # 尝试JSON格式
            try:
                data = json.loads(content)
                if isinstance(data, list):
                    self.messages = data
                else:
                    print("❌ JSON格式错误: 应该是消息数组")
                    return False
            except json.JSONDecodeError:
                # 纯文本格式
                lines = content.split('\n')
                for line in lines:
                    if line.strip():
                        # 简单解析: [时间] 发送人: 内容
                        match = re.match(r'\[?(\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2})\]?\s*(.+?)[:：]\s*(.+)', line)
                        if match:
                            timestamp, sender, content = match.groups()
                            self.messages.append({
                                'timestamp': timestamp,
                                'sender': sender.strip(),
                                'content': content.strip()
                            })
                        else:
                            # 没有时间戳的格式
                            if ':' in line or '：' in line:
                                parts = re.split(r'[:：]', line, 1)
                                if len(parts) == 2:
                                    self.messages.append({
                                        'timestamp': None,
                                        'sender': parts[0].strip(),
                                        'content': parts[1].strip()
                                    })

            # 提取参与者
            for msg in self.messages:
                if 'sender' in msg:
                    self.participants.add(msg['sender'])

            print(f"✅ 成功加载 {len(self.messages)} 条消息")
            print(f"📊 参与者: {', '.join(sorted(self.participants))}")
            return True

        except Exception as e:
            print(f"❌ 加载失败: {str(e)}")
            return False

    def analyze_suspicious_keywords(self) -> Dict[str, Any]:
        """分析可疑关键词"""
        results = {
            'total_matches': 0,
            'by_category': defaultdict(lambda: defaultdict(int)),
            'suspicious_messages': []
        }

        for msg in self.messages:
            content = msg.get('content', '')
            if not content:
                continue

            for category, patterns in self.suspicious_patterns.items():
                for pattern in patterns:
                    matches = re.findall(pattern, content)
                    if matches:
                        results['by_category'][category][msg.get('sender', 'unknown')] += len(matches)
                        results['total_matches'] += len(matches)

                        if len(results['suspicious_messages']) < 10:  # 限制数量
                            results['suspicious_messages'].append({
                                'sender': msg.get('sender', 'unknown'),
                                'timestamp': msg.get('timestamp', 'unknown'),
                                'content': content[:100] + '...' if len(content) > 100 else content,
                                'category': category,
                                'matches': matches
                            })

        return dict(results)

    def analyze_communication_patterns(self) -> Dict[str, Any]:
        """分析通信模式"""
        patterns = {
            'message_frequency': defaultdict(int),
            'active_hours': defaultdict(int),
            'response_times': [],
            'suspicious_intervals': []
        }

        for msg in self.messages:
            sender = msg.get('sender', 'unknown')
            patterns['message_frequency'][sender] += 1

            # 分析时间模式
            timestamp = msg.get('timestamp')
            if timestamp:
                try:
                    dt = datetime.fromisoformat(timestamp.replace('T', ' '))
                    hour = dt.hour
                    if hour >= 22 or hour <= 6:
                        patterns['active_hours']['深夜/凌晨'] += 1
                    elif 11 <= hour <= 13:
                        patterns['active_hours']['午休时间'] += 1
                    else:
                        patterns['active_hours']['工作时间'] += 1
                except:
                    pass

        return dict(patterns)

    def detect_anomalous_behavior(self) -> Dict[str, Any]:
        """检测异常行为"""
        anomalies = {
            'high_risk_users': [],
            'unusual_patterns': [],
            'evidence_destruction_attempts': []
        }

        # 检测高风险用户
        keyword_analysis = self.analyze_suspicious_keywords()
        user_risk_scores = defaultdict(int)

        for category, users in keyword_analysis.get('by_category', {}).items():
            for user, count in users.items():
                weight = 3 if category in ['money_keywords', 'power_abuse'] else 1
                user_risk_scores[user] += count * weight

        # 找出高风险用户
        if user_risk_scores:
            avg_score = sum(user_risk_scores.values()) / len(user_risk_scores)
            for user, score in user_risk_scores.items():
                if score > avg_score * 2:
                    anomalies['high_risk_users'].append({
                        'user': user,
                        'risk_score': score,
                        'avg_score': avg_score
                    })

        # 检测销毁证据的尝试
        for msg in self.messages:
            content = msg.get('content', '').lower()
            if any(keyword in content for keyword in ['删除', '销毁', '清除', '不留痕迹']):
                anomalies['evidence_destruction_attempts'].append({
                    'sender': msg.get('sender', 'unknown'),
                    'timestamp': msg.get('timestamp', 'unknown'),
                    'content': msg.get('content', '')[:100]
                })

        return anomalies

    def generate_report(self) -> str:
        """生成分析报告"""
        if not self.messages:
            return "❌ 没有可分析的消息数据"

        report = []
        report.append("=" * 60)
        report.append("反腐调查分析报告")
        report.append("=" * 60)
        report.append(f"\n📁 分析文件: {self.chat_file}")
        report.append(f"📊 消息总数: {len(self.messages)}")
        report.append(f"👥 参与者: {', '.join(sorted(self.participants))}")
        report.append(f"⏰ 分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # 可疑关键词分析
        report.append("\n" + "-" * 60)
        report.append("🔍 可疑关键词分析")
        report.append("-" * 60)

        keyword_results = self.analyze_suspicious_keywords()
        report.append(f"\n📈 可疑内容匹配总数: {keyword_results['total_matches']}")

        if keyword_results['by_category']:
            report.append("\n📋 分类统计:")
            for category, users in keyword_results['by_category'].items():
                report.append(f"\n  【{category}】")
                for user, count in sorted(users.items(), key=lambda x: x[1], reverse=True):
                    report.append(f"    - {user}: {count} 次")

        if keyword_results['suspicious_messages']:
            report.append("\n🚨 高风险消息示例:")
            for i, msg in enumerate(keyword_results['suspicious_messages'][:5], 1):
                report.append(f"\n  {i}. [{msg['timestamp']}] {msg['sender']}")
                report.append(f"     类别: {msg['category']}")
                report.append(f"     内容: {msg['content']}")

        # 通信模式分析
        report.append("\n" + "-" * 60)
        report.append("📊 通信模式分析")
        report.append("-" * 60)

        comm_patterns = self.analyze_communication_patterns()
        report.append("\n💬 消息频率:")
        for user, count in sorted(comm_patterns['message_frequency'].items(),
                                   key=lambda x: x[1], reverse=True):
            report.append(f"  - {user}: {count} 条")

        if comm_patterns['active_hours']:
            report.append("\n⏰ 活跃时间段:")
            for period, count in sorted(comm_patterns['active_hours'].items(),
                                       key=lambda x: x[1], reverse=True):
                report.append(f"  - {period}: {count} 条")

        # 异常行为检测
        report.append("\n" + "-" * 60)
        report.append("⚠️  异常行为检测")
        report.append("-" * 60)

        anomalies = self.detect_anomalous_behavior()

        if anomalies['high_risk_users']:
            report.append("\n🎯 高风险用户:")
            for user in anomalies['high_risk_users']:
                report.append(f"  - {user['user']}: 风险分数 {user['risk_score']:.1f} "
                           f"(平均: {user['avg_score']:.1f})")

        if anomalies['evidence_destruction_attempts']:
            report.append(f"\n🗑️  销毁证据尝试 ({len(anomalies['evidence_destruction_attempts'])} 次):")
            for attempt in anomalies['evidence_destruction_attempts'][:3]:
                report.append(f"  - [{attempt['timestamp']}] {attempt['sender']}")
                report.append(f"    {attempt['content'][:80]}...")

        # 风险评估
        report.append("\n" + "=" * 60)
        report.append("📊 风险评估总结")
        report.append("=" * 60)

        risk_level = "低"
        risk_score = 0

        if keyword_results['total_matches'] > 50:
            risk_score += 3
        elif keyword_results['total_matches'] > 20:
            risk_score += 2
        elif keyword_results['total_matches'] > 5:
            risk_score += 1

        if anomalies['high_risk_users']:
            risk_score += 2

        if anomalies['evidence_destruction_attempts']:
            risk_score += 3

        if risk_score >= 6:
            risk_level = "🔴 高风险"
        elif risk_score >= 3:
            risk_level = "🟡 中风险"
        else:
            risk_level = "🟢 低风险"

        report.append(f"\n🎯 综合风险等级: {risk_level}")
        report.append(f"📈 风险评分: {risk_score}/8")

        if risk_score >= 3:
            report.append("\n💡 建议:")
            report.append("  1. 深入调查高风险用户的通信记录")
            report.append("  2. 核实可疑交易和资金流向")
            report.append("  3. 查找相关物证和证人")
            report.append("  4. 保护相关数据和证据")

        report.append("\n" + "=" * 60)

        return "\n".join(report)


def main():
    """主函数"""
    import sys

    if len(sys.argv) < 2:
        print("使用方法: python analyze_chat.py <聊天记录文件> [输出文件]")
        print("\n支持的格式:")
        print("  - JSON: [{sender, content, timestamp}, ...]")
        print("  - TXT: [时间] 发送人: 内容")
        sys.exit(1)

    chat_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None

    # 创建分析器
    analyzer = ChatAnalyzer(chat_file)

    # 加载数据
    if not analyzer.load_chat_data():
        sys.exit(1)

    # 生成报告
    report = analyzer.generate_report()

    # 输出报告
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"\n✅ 报告已保存到: {output_file}")
    else:
        print("\n" + report)


if __name__ == "__main__":
    main()