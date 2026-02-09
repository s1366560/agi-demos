#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基本使用示例 - 反腐败调查技能 v4.0
Basic Usage Example for Anti-Corruption Investigation Skill v4.0
"""

import sys
import os

# 添加scripts目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from relationship_analyzer import RelationshipAnalyzer
from scalable_analyzer import ScalableAnalyzer


def example_1_message_analysis():
    """示例1: 消息分析"""
    print("="*60)
    print("示例1: 消息分析")
    print("="*60)
    
    # 创建分析器
    analyzer = ScalableAnalyzer(batch_size=1000)
    
    # 分析单条消息
    test_message = {
        'timestamp': '2024-01-15T14:30:00',
        'sender': '张三',
        'receiver': '李四',
        'content': '那笔钱准备好了吗？老地方见。'
    }
    
    result = analyzer.analyze_message(test_message)
    
    print(f"\n消息内容: {test_message['content']}")
    print(f"是否可疑: {'是' if result['is_suspicious'] else '否'}")
    print(f"风险等级: {result['risk_level']}")
    print(f"语义风险: {result['semantic_risk']:.2f}")
    print(f"检测到的模式: {[p['category'] for p in result['patterns']]}")
    print(f"行为异常: {result['behavioral_flags']}")


def example_2_relationship_analysis():
    """示例2: 关系网络分析"""
    print("\n" + "="*60)
    print("示例2: 关系网络分析")
    print("="*60)
    
    # 创建关系分析器
    analyzer = RelationshipAnalyzer()
    
    # 加载测试数据
    data_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'relationship_test_data.jsonl')
    
    if not os.path.exists(data_path):
        print(f"⚠️ 测试数据不存在: {data_path}")
        print("请先运行: python scripts/generate_test_data.py")
        return
    
    # 加载消息
    messages = analyzer.load_messages(data_path)
    
    # 构建网络
    analyzer.build_network(messages)
    
    # 计算中心性
    print("\n📊 中心性指标:")
    centrality = analyzer.calculate_centrality()
    for person, metrics in list(centrality.items())[:5]:
        print(f"\n{person}:")
        print(f"  度中心性: {metrics['degree']:.3f}")
        print(f"  中介中心性: {metrics['betweenness']:.3f}")
        print(f"  PageRank: {metrics['pagerank']:.3f}")
    
    # 检测社区
    print("\n👥 社区检测:")
    communities = analyzer.detect_communities()
    for i, community in enumerate(communities['communities'][:3], 1):
        print(f"\n社区 {i}:")
        print(f"  成员: {', '.join(community['members'])}")
        print(f"  密度: {community['density']:.3f}")
        print(f"  风险分数: {community['risk_score']}/10")
    
    # 识别关键人物
    print("\n🎯 关键人物:")
    key_players = analyzer.identify_key_players(centrality, communities)
    for i, player in enumerate(key_players[:5], 1):
        print(f"\n{i}. {player['name']} - {player['role']}")
        print(f"   得分: {player['score']}")
        print(f"   PageRank: {player['metrics']['pagerank']:.3f}")


def example_3_large_scale_analysis():
    """示例3: 大规模数据分析"""
    print("\n" + "="*60)
    print("示例3: 大规模数据分析")
    print("="*60)
    
    # 创建可扩展分析器
    analyzer = ScalableAnalyzer(batch_size=10000, workers=8)
    
    # 生成测试数据
    data_path = '/tmp/large_test.jsonl'
    print(f"\n生成测试数据到: {data_path}")
    
    from scripts.generate_test_data import generate_large_dataset
    generate_large_dataset(data_path, num_messages=10000)
    
    # 分析数据
    output_path = '/tmp/analysis_report.json'
    results = analyzer.analyze_large_dataset(data_path, output_path)
    
    print(f"\n✅ 分析完成!")
    print(f"风险等级: {results['overall_risk']}")
    print(f"风险分数: {results['risk_score']}/10")


def example_4_complete_workflow():
    """示例4: 完整工作流程"""
    print("\n" + "="*60)
    print("示例4: 完整工作流程")
    print("="*60)
    
    # 步骤1: 消息分析
    print("\n步骤1: 消息分析")
    scalable_analyzer = ScalableAnalyzer()
    
    data_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'relationship_test_data.jsonl')
    if not os.path.exists(data_path):
        print("⚠️ 测试数据不存在，跳过此步骤")
        return
    
    output_path = '/tmp/message_analysis.json'
    message_results = scalable_analyzer.analyze_large_dataset(data_path, output_path)
    
    # 步骤2: 关系网络分析
    print("\n步骤2: 关系网络分析")
    relationship_analyzer = RelationshipAnalyzer()
    messages = relationship_analyzer.load_messages(data_path)
    relationship_analyzer.build_network(messages)
    
    # 步骤3: 生成综合报告
    print("\n步骤3: 生成综合报告")
    summary = relationship_analyzer.generate_summary()
    
    # 保存完整报告
    report_path = '/tmp/complete_report.json'
    relationship_analyzer.save_report(summary, report_path)
    
    # 步骤4: 可视化（如果可用）
    print("\n步骤4: 生成可视化")
    try:
        viz_path = '/tmp/network_visualization.html'
        relationship_analyzer.visualize_network(viz_path)
        print(f"✅ 可视化已保存: {viz_path}")
    except Exception as e:
        print(f"⚠️ 可视化生成失败: {e}")
    
    print("\n✅ 完整工作流程完成!")


def main():
    """主函数"""
    print("🚀 反腐败调查技能 v4.0 - 基本使用示例")
    print("="*60)
    
    # 运行示例
    example_1_message_analysis()
    example_2_relationship_analysis()
    example_3_large_scale_analysis()
    example_4_complete_workflow()
    
    print("\n" + "="*60)
    print("✅ 所有示例运行完成!")
    print("="*60)


if __name__ == '__main__':
    main()
