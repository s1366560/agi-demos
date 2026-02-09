#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
反腐败调查技能 v2.0 - 快速使用示例
演示如何使用高级分析器进行腐败调查
"""

import json
from advanced_analyzer import AdvancedCorruptionAnalyzer

def example_usage():
    """使用示例"""
    
    print("=" * 60)
    print("反腐败调查技能 v2.0 - 快速使用示例")
    print("=" * 60)
    
    # 1. 创建分析器
    print("\n📊 步骤1: 创建分析器")
    analyzer = AdvancedCorruptionAnalyzer()
    print("✅ 分析器创建成功！")
    
    # 2. 准备测试数据
    print("\n📂 步骤2: 准备测试数据")
    test_data = [
        {
            "timestamp": "2024-01-10T09:30:00",
            "sender": "王科长",
            "content": "技术参数已经调整了，基本按你们建议来的"
        },
        {
            "timestamp": "2024-01-08T19:45:00",
            "sender": "刘经理",
            "content": "今晚有空吗？老地方见"
        },
        {
            "timestamp": "2024-01-13T20:30:00",
            "sender": "刘经理",
            "content": "陈总，那个东西准备好了，什么时候方便？"
        },
        {
            "timestamp": "2024-01-15T10:10:00",
            "sender": "陈总",
            "content": "是的，按老规矩办"
        },
        {
            "timestamp": "2024-02-10T11:15:00",
            "sender": "陈总",
            "content": "放心，只有我们知道"
        },
        {
            "timestamp": "2024-03-15T16:10:00",
            "sender": "王科长",
            "content": "明白，聊天记录都清理了"
        }
    ]
    print(f"✅ 测试数据准备完成！共 {len(test_data)} 条消息")
    
    # 3. 执行分析
    print("\n🔍 步骤3: 执行分析")
    report = analyzer.analyze(test_data)
    print("✅ 分析完成！")
    
    # 4. 显示结果
    print("\n📊 步骤4: 分析结果")
    print("=" * 60)
    
    # 风险评估
    print("\n🎯 风险评估:")
    risk_assessment = report['风险评估']
    print(f"  风险等级: {risk_assessment['风险等级']}")
    print(f"  风险分数: {risk_assessment['总风险分数']}/{risk_assessment['最大风险分数']}")
    print(f"  置信度: {risk_assessment['置信度']*100:.1f}%")
    
    # 语义分析
    print("\n🧠 语义分析:")
    semantic_result = report['语义分析']
    print(f"  可疑消息数: {semantic_result['可疑消息数']}")
    print("  模式匹配统计:")
    for pattern_type, matches in semantic_result['模式匹配统计'].items():
        print(f"    - {pattern_type}: {len(matches)}条")
    
    # 关系网络
    print("\n🕸️  关系网络:")
    network_result = report['关系网络']
    print("  关键人物:")
    for i, person in enumerate(network_result['关键人物'], 1):
        centrality = network_result['中心性得分'][person]
        print(f"    {i}. {person} (中心性: {centrality:.2f})")
    
    # 行为模式
    print("\n🔍 行为模式:")
    behavioral_result = report['行为模式']
    print(f"  异常行为数: {behavioral_result['异常行为数']}")
    print("  异常类型统计:")
    for anomaly_type, count in behavioral_result['异常类型统计'].items():
        print(f"    - {anomaly_type}: {count}次")
    
    # 证据链
    print("\n🔗 证据链:")
    evidence_chain = report['证据链']
    print(f"  完整性: {evidence_chain['完整性']}")
    print(f"  关键证据数: {len(evidence_chain['关键证据'])}")
    print(f"  证据强度: {evidence_chain['证据强度']}")
    
    # 建议措施
    print("\n💡 建议措施:")
    for i, recommendation in enumerate(report['建议措施'], 1):
        print(f"  {i}. {recommendation}")
    
    print("\n" + "=" * 60)
    print("✅ 分析完成！")
    print("=" * 60)
    
    return report


def save_report_example():
    """保存报告示例"""
    
    print("\n📝 保存报告示例")
    print("=" * 60)
    
    # 生成报告
    analyzer = AdvancedCorruptionAnalyzer()
    
    # 使用复杂案例数据
    data_file = "data/complex_corruption_case.json"
    output_file = "reports/example_report.json"
    
    print(f"\n📂 读取数据: {data_file}")
    with open(data_file, 'r', encoding='utf-8') as f:
        chat_data = json.load(f)
    
    print(f"📊 总消息数: {len(chat_data)}")
    
    print("\n🔍 执行分析...")
    report = analyzer.analyze(chat_data)
    
    print(f"\n💾 保存报告: {output_file}")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    print("✅ 报告保存成功！")
    print(f"📄 查看报告: cat {output_file}")
    
    print("\n" + "=" * 60)


def custom_analysis_example():
    """自定义分析示例"""
    
    print("\n🎯 自定义分析示例")
    print("=" * 60)
    
    # 创建分析器
    analyzer = AdvancedCorruptionAnalyzer()
    
    # 自定义数据
    custom_data = [
        {
            "timestamp": "2024-02-01T10:00:00",
            "sender": "张主任",
            "content": "项目批下来了，准备启动"
        },
        {
            "timestamp": "2024-02-01T10:05:00",
            "sender": "李经理",
            "content": "好的，什么时候方便聊聊细节？"
        },
        {
            "timestamp": "2024-02-01T20:30:00",
            "sender": "张主任",
            "content": "今晚老地方见"
        },
        {
            "timestamp": "2024-02-05T14:00:00",
            "sender": "李经理",
            "content": "心意准备好了，放您车上"
        },
        {
            "timestamp": "2024-02-05T14:05:00",
            "sender": "张主任",
            "content": "收到了，按老规矩办"
        }
    ]
    
    print(f"\n📊 自定义数据: {len(custom_data)} 条消息")
    
    # 执行分析
    report = analyzer.analyze(custom_data)
    
    # 显示关键结果
    print("\n🎯 风险评估:")
    print(f"  风险等级: {report['风险评估']['风险等级']}")
    print(f"  风险分数: {report['风险评估']['总风险分数']}/10")
    
    print("\n🧠 关键发现:")
    semantic_result = report['语义分析']
    for pattern_type, matches in semantic_result['模式匹配统计'].items():
        if len(matches) > 0:
            print(f"  - {pattern_type}: {len(matches)}条")
    
    print("\n💡 建议:")
    for i, rec in enumerate(report['建议措施'][:3], 1):
        print(f"  {i}. {rec}")
    
    print("\n" + "=" * 60)


def interactive_example():
    """交互式示例"""
    
    print("\n🎮 交互式分析示例")
    print("=" * 60)
    
    print("\n请输入聊天记录（输入空行结束）:")
    
    messages = []
    while True:
        line = input("> ")
        if not line:
            break
        
        # 简单解析格式: [时间] 发送者: 内容
        try:
            if line.startswith("["):
                # 格式: [2024-01-15 14:30:00] 张三: 消息内容
                time_end = line.index("]")
                timestamp = line[1:time_end].strip()
                rest = line[time_end+1:].strip()
                
                if ":" in rest:
                    sender_end = rest.index(":")
                    sender = rest[:sender_end].strip()
                    content = rest[sender_end+1:].strip()
                    
                    messages.append({
                        "timestamp": timestamp,
                        "sender": sender,
                        "content": content
                    })
        except:
            print(f"⚠️  格式错误，请使用: [时间] 发送者: 内容")
    
    if messages:
        print(f"\n📊 收集到 {len(messages)} 条消息")
        
        # 执行分析
        analyzer = AdvancedCorruptionAnalyzer()
        report = analyzer.analyze(messages)
        
        # 显示结果
        print("\n🎯 分析结果:")
        print(f"  风险等级: {report['风险评估']['风险等级']}")
        print(f"  风险分数: {report['风险评估']['总风险分数']}/10")
        print(f"  置信度: {report['风险评估']['置信度']*100:.1f}%")
        
        print("\n💡 建议:")
        for i, rec in enumerate(report['建议措施'][:3], 1):
            print(f"  {i}. {rec}")
    else:
        print("\n⚠️  没有输入有效消息")
    
    print("\n" + "=" * 60)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "basic":
            example_usage()
        elif command == "save":
            save_report_example()
        elif command == "custom":
            custom_analysis_example()
        elif command == "interactive":
            interactive_example()
        else:
            print("❌ 未知命令")
            print("可用命令: basic, save, custom, interactive")
    else:
        # 默认运行基本示例
        example_usage()
        
        print("\n" + "=" * 60)
        print("📚 更多示例:")
        print("  python quick_example.py basic       - 基本示例")
        print("  python quick_example.py save        - 保存报告")
        print("  python quick_example.py custom      - 自定义分析")
        print("  python quick_example.py interactive - 交互式分析")
        print("=" * 60)
