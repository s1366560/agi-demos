#!/usr/bin/env python3
"""
Anti-Corruption Investigation Tool v5.0

A unified tool for analyzing chat logs to detect corruption patterns,
build relationship networks, and generate human-friendly reports.

Usage:
    python anti_corruption.py analyze <input_file> <output_file> [options]
    python anti_corruption.py relationships <input_file> <output_file> [options]
    python anti_corruption.py full <input_file> <output_dir> [options]

Examples:
    # Basic analysis
    python anti_corruption.py analyze data.jsonl report.json

    # Relationship analysis
    python anti_corruption.py relationships data.jsonl relationships.json

    # Full analysis with all features
    python anti_corruption.py full data.jsonl output/ --batch-size 10000 --workers 8
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Tuple
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


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Anti-Corruption Investigation Tool v5.0',
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

    elif args.command == 'full':
        print("🚀 Running full analysis...")
        output_dir = Path(args.output_dir)
        output_dir.mkdir(exist_ok=True)

        # Run both analyses
        print("🔬 Analyzing messages...")
        chat_analyzer = ChatAnalyzer(messages)
        chat_results = chat_analyzer.analyze()

        chat_output = output_dir / 'chat_analysis.json'
        with open(chat_output, 'w', encoding='utf-8') as f:
            json.dump(chat_results, f, ensure_ascii=False, indent=2)
        print(f"✅ Chat analysis saved to {chat_output}")

        print("🕸️ Analyzing relationships...")
        rel_analyzer = RelationshipAnalyzer(messages)
        rel_results = rel_analyzer.analyze()

        rel_output = output_dir / 'relationships.json'
        with open(rel_output, 'w', encoding='utf-8') as f:
            json.dump(rel_results, f, ensure_ascii=False, indent=2)
        print(f"✅ Relationships saved to {rel_output}")

        # Generate text report
        print("📝 Generating text report...")
        report = ReportGenerator.generate_relationship_report(rel_results)

        report_output = output_dir / 'report.txt'
        with open(report_output, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"✅ Text report saved to {report_output}")

    print("\n🎉 Analysis complete!")


if __name__ == '__main__':
    main()
