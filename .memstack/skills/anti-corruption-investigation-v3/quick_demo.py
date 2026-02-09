#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
反腐败调查技能 v3.0 - 快速演示
展示大规模数据处理能力

使用方法:
1. 生成测试数据 (10万条消息)
2. 运行分析
3. 查看性能报告
"""

import sys
import time
from pathlib import Path

# 添加脚本目录到路径
sys.path.insert(0, str(Path(__file__).parent / 'scripts'))

from generate_large_dataset import LargeDatasetGenerator
from scalable_analyzer import ScalableAnalyzer


def demo_small_scale():
    """小规模演示 (1万条消息)"""
    print("\n" + "="*80)
    print("小规模演示 - 1万条消息".center(80))
    print("="*80 + "\n")
    
    # 生成数据
    print("步骤 1/2: 生成测试数据...")
    generator = LargeDatasetGenerator(
        total_messages=10000,
        corruption_rate=0.1
    )
    generator.generate('data/demo_10k.jsonl')
    
    # 分析数据
    print("\n步骤 2/2: 分析数据...")
    analyzer = ScalableAnalyzer(
        batch_size=1000,
        workers=4,
        enable_cache=True
    )
    
    results = analyzer.analyze_large_dataset(
        input_path='data/demo_10k.jsonl',
        output_path='reports/demo_10k_report.json',
        sample_rate=1.0
    )
    
    return results


def demo_medium_scale():
    """中等规模演示 (10万条消息)"""
    print("\n" + "="*80)
    print("中等规模演示 - 10万条消息".center(80))
    print("="*80 + "\n")
    
    # 生成数据
    print("步骤 1/2: 生成测试数据...")
    generator = LargeDatasetGenerator(
        total_messages=100000,
        corruption_rate=0.1
    )
    generator.generate('data/demo_100k.jsonl')
    
    # 分析数据
    print("\n步骤 2/2: 分析数据...")
    analyzer = ScalableAnalyzer(
        batch_size=10000,
        workers=8,
        enable_cache=True
    )
    
    results = analyzer.analyze_large_dataset(
        input_path='data/demo_100k.jsonl',
        output_path='reports/demo_100k_report.json',
        sample_rate=1.0
    )
    
    return results


def demo_large_scale():
    """大规模演示 (100万条消息)"""
    print("\n" + "="*80)
    print("大规模演示 - 100万条消息".center(80))
    print("="*80 + "\n")
    
    # 生成数据
    print("步骤 1/2: 生成测试数据...")
    generator = LargeDatasetGenerator(
        total_messages=1000000,
        corruption_rate=0.1
    )
    generator.generate('data/demo_1M.jsonl')
    
    # 分析数据
    print("\n步骤 2/2: 分析数据...")
    analyzer = ScalableAnalyzer(
        batch_size=10000,
        workers=8,
        enable_cache=True
    )
    
    results = analyzer.analyze_large_dataset(
        input_path='data/demo_1M.jsonl',
        output_path='reports/demo_1M_report.json',
        sample_rate=0.1  # 采样10%进行快速演示
    )
    
    return results


def demo_performance_comparison():
    """性能对比演示"""
    print("\n" + "="*80)
    print("性能对比演示".center(80))
    print("="*80 + "\n")
    
    scales = [
        ("1万", 10000),
        ("10万", 100000),
        ("100万", 1000000)
    ]
    
    results = []
    
    for name, count in scales:
        print(f"\n测试规模: {name}条消息")
        print("-" * 60)
        
        # 生成数据
        generator = LargeDatasetGenerator(
            total_messages=count,
            corruption_rate=0.1
        )
        data_file = f'data/perf_{count}.jsonl'
        generator.generate(data_file)
        
        # 分析数据
        analyzer = ScalableAnalyzer(
            batch_size=10000,
            workers=8,
            enable_cache=True
        )
        
        start_time = time.time()
        report = analyzer.analyze_large_dataset(
            input_path=data_file,
            output_path=f'reports/perf_{count}_report.json',
            sample_rate=0.1 if count > 100000 else 1.0
        )
        elapsed = time.time() - start_time
        
        results.append({
            'scale': name,
            'count': count,
            'elapsed_time': elapsed,
            'throughput': count / elapsed
        })
    
    # 打印对比结果
    print("\n" + "="*80)
    print("性能对比结果".center(80))
    print("="*80)
    print(f"\n{'规模':<10} {'消息数':<15} {'耗时(秒)':<15} {'吞吐量(条/秒)':<20}")
    print("-" * 80)
    
    for r in results:
        print(f"{r['scale']:<10} {r['count']:<15,} {r['elapsed_time']:<15.2f} {r['throughput']:<20,.1f}")
    
    print("\n" + "="*80 + "\n")


def main():
    """主函数"""
    print("\n" + "="*80)
    print("反腐败调查技能 v3.0 - 演示程序".center(80))
    print("="*80)
    
    print("\n请选择演示模式:")
    print("1. 小规模演示 (1万条消息)")
    print("2. 中等规模演示 (10万条消息)")
    print("3. 大规模演示 (100万条消息)")
    print("4. 性能对比演示")
    print("5. 退出")
    
    choice = input("\n请输入选择 (1-5): ").strip()
    
    if choice == '1':
        demo_small_scale()
    elif choice == '2':
        demo_medium_scale()
    elif choice == '3':
        demo_large_scale()
    elif choice == '4':
        demo_performance_comparison()
    elif choice == '5':
        print("\n再见！")
        sys.exit(0)
    else:
        print("\n无效选择，请重新运行程序")
        sys.exit(1)


if __name__ == '__main__':
    main()
