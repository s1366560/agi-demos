#!/usr/bin/env python3
"""
Social Network Analysis Example

Demonstrates the new v6.0 features for person social relationship analysis.
"""

import json
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from anti_corruption import SocialNetworkAnalyzer, ReportGenerator


def generate_sample_data():
    """Generate sample chat data for demonstration."""
    messages = [
        # 张三 (Official) - High risk
        {"timestamp": "2024-01-15T09:00:00", "sender": "张三", "receiver": "李四", "content": "那个项目审批的事情，你准备得怎么样了？"},
        {"timestamp": "2024-01-15T14:30:00", "sender": "李四", "receiver": "张三", "content": "张局，资料都准备好了，晚上老地方见？"},
        {"timestamp": "2024-01-15T22:00:00", "sender": "张三", "receiver": "李四", "content": "好，见面细说。"},
        {"timestamp": "2024-01-16T23:30:00", "sender": "张三", "receiver": "李四", "content": "那笔钱收到了，事情我会尽快处理。"},

        # 王五 (Intermediary) - Bridge between official and business
        {"timestamp": "2024-01-15T10:00:00", "sender": "王五", "receiver": "张三", "content": "张局，有个朋友想认识您，我帮您牵线一下？"},
        {"timestamp": "2024-01-15T10:30:00", "sender": "张三", "receiver": "王五", "content": "好，你安排吧。"},
        {"timestamp": "2024-01-15T11:00:00", "sender": "王五", "receiver": "赵六", "content": "赵总，我帮您联系到张局了，晚上一起吃饭？"},
        {"timestamp": "2024-01-15T11:30:00", "sender": "赵六", "receiver": "王五", "content": "太好了，王中介，这次多亏你帮忙。"},
        {"timestamp": "2024-01-16T00:15:00", "sender": "王五", "receiver": "钱七", "content": "钱老板，有个项目可以合作，我帮你介绍个人。"},

        # 赵六 (Business) - Connected through intermediary
        {"timestamp": "2024-01-15T15:00:00", "sender": "赵六", "receiver": "张三", "content": "张局长，我是王五介绍来的，有个项目想请您关照。"},
        {"timestamp": "2024-01-16T08:00:00", "sender": "赵六", "receiver": "张三", "content": "感谢费已经准备好了，按老规矩办。"},
        {"timestamp": "2024-01-16T21:00:00", "sender": "张三", "receiver": "赵六", "content": "事情办好了，以后有事直接找我。"},

        # 钱七 (Business) - Another connection
        {"timestamp": "2024-01-16T09:00:00", "sender": "钱七", "receiver": "王五", "content": "王总，那个招标的事情有眉目了吗？"},
        {"timestamp": "2024-01-16T09:30:00", "sender": "王五", "receiver": "钱七", "content": "正在帮你疏通关系，需要一点表示。"},
        {"timestamp": "2024-01-16T10:00:00", "sender": "钱七", "receiver": "王五", "content": "明白，钱不是问题。"},

        # 李四 (Business) - Close to official
        {"timestamp": "2024-01-17T08:00:00", "sender": "李四", "receiver": "张三", "content": "张局，大家统一一下口径，对外就说正常审批。"},
        {"timestamp": "2024-01-17T22:30:00", "sender": "张三", "receiver": "李四", "content": "知道了，删除之前的聊天记录。"},

        # 孙八 (Family) - Official's relative
        {"timestamp": "2024-01-15T12:00:00", "sender": "孙八", "receiver": "张三", "content": "哥，我朋友公司那个事情你帮忙看看。"},
        {"timestamp": "2024-01-15T12:30:00", "sender": "张三", "receiver": "孙八", "content": "好，让他把资料发给我。"},

        # 周九 (Business) - Less connected
        {"timestamp": "2024-01-15T13:00:00", "sender": "周九", "receiver": "张三", "content": "张局长，有个事情想咨询一下。"},
        {"timestamp": "2024-01-15T13:30:00", "sender": "张三", "receiver": "周九", "content": "正常程序办理即可。"},
    ]

    return messages


def main():
    """Run social network analysis example."""
    print("=" * 80)
    print("Social Network Analysis Example (v6.0)")
    print("=" * 80)
    print()

    # Generate sample data
    print("📊 Generating sample data...")
    messages = generate_sample_data()
    print(f"✅ Generated {len(messages)} messages")
    print()

    # Run social network analysis
    print("🔬 Running social network analysis...")
    analyzer = SocialNetworkAnalyzer(messages)
    results = analyzer.analyze()
    print("✅ Analysis complete")
    print()

    # Display results
    stats = results['network_statistics']
    print("📈 Network Statistics:")
    print(f"   • Total persons: {stats['total_persons']}")
    print(f"   • Total relationships: {stats['total_relationships']}")
    print(f"   • Network density: {stats['network_density']:.4f}")
    print(f"   • Average contacts per person: {stats['avg_contacts_per_person']:.1f}")
    print()

    # Risk distribution
    risk_dist = stats['risk_distribution']
    print("🎯 Risk Distribution:")
    print(f"   • 🔴 High risk: {risk_dist['high']} persons")
    print(f"   • 🟠 Medium risk: {risk_dist['medium']} persons")
    print(f"   • 🟢 Low risk: {risk_dist['low']} persons")
    print()

    # Role distribution
    role_dist = stats['role_distribution']
    print("👔 Role Distribution:")
    role_names = {
        'official': 'Official',
        'business': 'Business',
        'intermediary': 'Intermediary',
        'family': 'Family',
        'unknown': 'Unknown'
    }
    for role, count in sorted(role_dist.items(), key=lambda x: x[1], reverse=True):
        print(f"   • {role_names.get(role, role)}: {count} persons")
    print()

    # Person profiles
    print("=" * 80)
    print("👤 Person Profiles (Top by Risk):")
    print("=" * 80)
    print()

    profiles = results['person_profiles']
    sorted_profiles = sorted(profiles.items(), key=lambda x: x[1]['risk_score'], reverse=True)

    for name, profile in sorted_profiles:
        print(f"{name}:")
        print(f"   Role: {profile['primary_role']}")
        print(f"   Risk: {profile['risk_level']} ({profile['risk_score']:.1f}/10)")
        print(f"   Messages: {profile['message_count']} total, {profile['suspicious_message_count']} suspicious")
        print(f"   Contacts: {profile['contact_count']}")
        print()

    # Intermediaries
    print("=" * 80)
    print("🔗 Intermediaries Detected:")
    print("=" * 80)
    print()

    intermediaries = results['intermediaries']
    if intermediaries:
        for inter in intermediaries:
            print(f"{inter['name']}:")
            print(f"   Brokerage Score: {inter['brokerage_score']}/10")
            print(f"   Contacts: {inter['contact_count']}")
            print(f"   Role: {inter['primary_role']}")
            print()
    else:
        print("No intermediaries detected")
        print()

    # Communities
    print("=" * 80)
    print("👥 Communities Detected:")
    print("=" * 80)
    print()

    communities = results['communities']
    if communities:
        for i, comm in enumerate(communities, 1):
            print(f"Community {i}:")
            print(f"   Members ({comm['member_count']}): {', '.join(comm['members'])}")
            print(f"   Average Risk: {comm['average_risk_score']}/10 ({comm['risk_level']})")
            print(f"   Internal Connections: {comm['internal_connections']}")
            print()
    else:
        print("No communities detected")
        print()

    # Influence ranking
    print("=" * 80)
    print("⭐ Influence Ranking:")
    print("=" * 80)
    print()

    influence = results['influence_ranking']
    for i, person in enumerate(influence[:5], 1):
        print(f"{i}. {person['name']}")
        print(f"   Influence Score: {person['influence_score']:.2f}")
        print(f"   Centrality: {person['centrality']:.2f}")
        print(f"   Contacts: {person['contact_count']}")
        print()

    # Connection paths
    print("=" * 80)
    print("🌉 Key Bridges:")
    print("=" * 80)
    print()

    paths = results['connection_paths']
    if paths.get('key_bridges'):
        for bridge in paths['key_bridges']:
            print(f"{bridge['name']} connects {bridge['connection_count']} high-risk persons:")
            for conn in bridge['connects']:
                print(f"   - {conn}")
            print()
    else:
        print("No key bridges detected")
        print()

    # Generate full report
    print("=" * 80)
    print("📝 Generating Full Report...")
    print("=" * 80)
    print()

    report = ReportGenerator.generate_social_network_report(results)
    print(report)

    # Save results
    output_dir = Path(__file__).parent / 'output'
    output_dir.mkdir(exist_ok=True)

    with open(output_dir / 'social_network_results.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    with open(output_dir / 'social_network_report.txt', 'w', encoding='utf-8') as f:
        f.write(report)

    print(f"\n✅ Results saved to {output_dir}/")


if __name__ == '__main__':
    main()