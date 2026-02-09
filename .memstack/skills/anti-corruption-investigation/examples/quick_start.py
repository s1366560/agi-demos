#!/usr/bin/env python3
"""
Quick Start Example for Anti-Corruption Investigation Tool v5.0

This example demonstrates basic usage of the tool.
"""

import sys
sys.path.insert(0, '/workspace/.skills/anti-corruption-v5/scripts')

from anti_corruption import ChatAnalyzer, RelationshipAnalyzer, ReportGenerator
import json


def example_basic_analysis():
    """Example 1: Basic chat analysis."""
    print("=" * 80)
    print("Example 1: Basic Chat Analysis")
    print("=" * 80)

    # Sample messages
    messages = [
        {"timestamp": "2024-01-15T14:30:00", "sender": "张三", "receiver": "李四", "content": "那笔钱准备好了吗？"},
        {"timestamp": "2024-01-15T14:31:00", "sender": "李四", "receiver": "张三", "content": "已经准备好了，什么时候给你？"},
        {"timestamp": "2024-01-15T22:30:00", "sender": "张三", "receiver": "李四", "content": "老地方见，不要告诉别人"},
    ]

    # Analyze
    analyzer = ChatAnalyzer(messages)
    results = analyzer.analyze()

    # Display results
    print(f"\n📊 Total Messages: {results['total_messages']}")
    print(f"🚨 Suspicious Messages: {results['suspicious_count']}")
    print(f"🎯 Risk Level: {results['risk_level']}")
    print(f"📈 Suspicious Rate: {results['suspicious_rate']:.2%}")

    print("\n🔍 Pattern Counts:")
    for pattern, count in results['pattern_counts'].items():
        if count > 0:
            print(f"  • {pattern}: {count}")

    print("\n⏰ Time Anomalies:")
    print(f"  • Late Night: {results['time_anomalies']['late_night']}")
    print(f"  • Weekend: {results['time_anomalies']['weekend']}")

    print("\n👤 Key Players:")
    for player in results['key_players'][:3]:
        print(f"  • {player['name']}: {player['suspicious_count']} suspicious messages")

    print("\n🚨 Suspicious Messages:")
    for msg in results['suspicious_messages'][:3]:
        print(f"\n  [{msg['timestamp']}] {msg['sender']} -> {msg['receiver']}")
        print(f"  Content: {msg['content']}")
        print(f"  Patterns: {', '.join(msg['patterns'])}")


def example_relationship_analysis():
    """Example 2: Relationship analysis."""
    print("\n" + "=" * 80)
    print("Example 2: Relationship Analysis")
    print("=" * 80)

    # Sample messages
    messages = [
        {"timestamp": "2024-01-15T14:30:00", "sender": "冯供应商", "receiver": "陈总", "content": "不留痕迹"},
        {"timestamp": "2024-01-16T08:15:00", "sender": "陈总", "receiver": "冯供应商", "content": "大家统一一下口径"},
        {"timestamp": "2024-01-17T22:30:00", "sender": "冯供应商", "receiver": "陈总", "content": "见面细说"},
        {"timestamp": "2024-01-18T10:00:00", "sender": "张局长", "receiver": "韩子", "content": "账户已经转过去了"},
        {"timestamp": "2024-01-19T15:00:00", "sender": "韩子", "receiver": "张局长", "content": "谢谢你的帮助"},
    ]

    # Analyze relationships
    analyzer = RelationshipAnalyzer(messages)
    results = analyzer.analyze()

    # Display results
    print(f"\n🕸️ Total Relationships: {results['total_relationships']}")

    print("\n📊 Statistics:")
    stats = results['statistics']
    print(f"  • Average Message Count: {stats['avg_message_count']:.1f}")
    print(f"  • Max Message Count: {stats['max_message_count']}")
    print(f"  • High Risk: {stats['high_risk_count']}")
    print(f"  • Medium Risk: {stats['medium_risk_count']}")
    print(f"  • Low Risk: {stats['low_risk_count']}")

    print("\n🎯 Top Relationships:")
    for i, rel in enumerate(results['top_relationships'][:3], 1):
        print(f"\n{i}. {rel['person_a']} ↔ {rel['person_b']}")
        print(f"   Type: {', '.join(rel['relationship_type'])}")
        print(f"   Strength: {rel['strength']:.2f}")
        print(f"   Messages: {rel['message_count']}")
        print(f"   Risk: {rel['risk_level']}")

        if rel['evidence']:
            print(f"   Evidence:")
            for evidence in rel['evidence'][:2]:
                print(f"   • [{evidence['timestamp']}] {evidence['content'][:50]}...")


def example_text_report():
    """Example 3: Generate human-friendly text report."""
    print("\n" + "=" * 80)
    print("Example 3: Text Report Generation")
    print("=" * 80)

    # Sample messages
    messages = [
        {"timestamp": "2024-01-15T14:30:00", "sender": "冯供应商", "receiver": "陈总", "content": "不留痕迹"},
        {"timestamp": "2024-01-16T08:15:00", "sender": "陈总", "receiver": "冯供应商", "content": "大家统一一下口径"},
        {"timestamp": "2024-01-17T22:30:00", "sender": "冯供应商", "receiver": "陈总", "content": "见面细说"},
    ]

    # Analyze
    analyzer = RelationshipAnalyzer(messages)
    results = analyzer.analyze()

    # Generate report
    report = ReportGenerator.generate_relationship_report(results)

    print("\n📄 Generated Report:")
    print("\n" + report)


def main():
    """Run all examples."""
    print("\n" + "=" * 80)
    print("Anti-Corruption Investigation Tool v5.0 - Quick Start Examples")
    print("=" * 80)

    example_basic_analysis()
    example_relationship_analysis()
    example_text_report()

    print("\n" + "=" * 80)
    print("✅ All examples completed!")
    print("=" * 80)


if __name__ == '__main__':
    main()
