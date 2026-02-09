#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
大规模测试数据生成器
生成百万量级的聊天记录用于性能测试

功能:
1. 生成正常日常聊天 (90%)
2. 生成隐晦腐败聊天 (10%)
3. 模拟真实时间分布
4. 支持JSON Lines格式
"""

import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict
import argparse


class LargeDatasetGenerator:
    """大规模数据集生成器"""
    
    # 正常聊天模板
    NORMAL_TEMPLATES = [
        "今天天气不错",
        "中午吃什么？",
        "项目进展如何？",
        "收到，谢谢",
        "好的，没问题",
        "明天开会吗？",
        "文件已发送",
        "请查收附件",
        "周末有空吗？",
        "生日快乐！",
        "工作辛苦了",
        "谢谢帮助",
        "稍后回复",
        "正在处理",
        "已完成任务",
        "需要协助吗？",
        "好的收到",
        "明白了",
        "继续跟进",
        "保持联系"
    ]
    
    # 隐晦腐败模板
    CORRUPTION_TEMPLATES = [
        # 资金相关
        ("那笔钱准备好了吗？", "financial", 0.8),
        ("那个东西什么时候方便？", "financial", 0.7),
        ("按老规矩办", "financial", 0.9),
        ("一点心意，收下吧", "financial", 0.8),
        ("辛苦费，别客气", "financial", 0.7),
        ("茶水费已备好", "financial", 0.6),
        
        # 秘密会面
        ("今晚老地方见", "meeting", 0.8),
        ("私下单独聊聊", "meeting", 0.9),
        ("保密，别告诉别人", "meeting", 0.8),
        ("只有我们两人知道", "meeting", 0.9),
        ("找个安静的地方", "meeting", 0.7),
        
        # 权力滥用
        ("特殊照顾一下", "abuse", 0.8),
        ("通融一下，拜托", "abuse", 0.7),
        ("按以前的规矩", "abuse", 0.8),
        ("破例处理", "abuse", 0.7),
        ("开个绿灯", "abuse", 0.9),
        ("多多关照", "abuse", 0.6),
        
        # 证据销毁
        ("聊天记录清理下", "evidence", 0.9),
        ("删除这些消息", "evidence", 0.9),
        ("不留痕迹", "evidence", 0.8),
        ("撤回刚才说的", "evidence", 0.7),
        ("毁掉相关文件", "evidence", 0.9)
    ]
    
    # 参与者名单
    PARTICIPANTS = [
        "张三", "李四", "王五", "赵六", "陈七",
        "刘经理", "王科长", "陈总", "周主任",
        "孙秘书", "吴助理", "郑主管", "钱董事",
        "小明", "小红", "小华", "小李"
    ]
    
    def __init__(self, 
                 total_messages: int = 1000000,
                 corruption_rate: float = 0.1):
        """
        初始化生成器
        
        Args:
            total_messages: 总消息数
            corruption_rate: 腐败消息比例
        """
        self.total_messages = total_messages
        self.corruption_rate = corruption_rate
        self.corruption_count = int(total_messages * corruption_rate)
        self.normal_count = total_messages - self.corruption_count
        
        print(f"初始化数据生成器:")
        print(f"  总消息数: {total_messages:,}")
        print(f"  腐败消息: {self.corruption_count:,} ({corruption_rate:.1%})")
        print(f"  正常消息: {self.normal_count:,} ({1-corruption_rate:.1%})")
    
    def generate(self, output_path: str) -> None:
        """
        生成数据集
        
        Args:
            output_path: 输出文件路径
        """
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        print(f"\n开始生成数据集...")
        start_time = datetime.now()
        
        with open(output_file, 'w', encoding='utf-8') as f:
            # 生成正常消息
            print(f"生成正常消息...")
            for i in range(self.normal_count):
                message = self._generate_normal_message(i)
                f.write(json.dumps(message, ensure_ascii=False) + '\n')
                
                if (i + 1) % 100000 == 0:
                    print(f"  进度: {i+1:,}/{self.normal_count:,}")
            
            # 生成腐败消息
            print(f"生成腐败消息...")
            for i in range(self.corruption_count):
                message = self._generate_corruption_message(i)
                f.write(json.dumps(message, ensure_ascii=False) + '\n')
                
                if (i + 1) % 10000 == 0:
                    print(f"  进度: {i+1:,}/{self.corruption_count:,}")
        
        elapsed = (datetime.now() - start_time).total_seconds()
        file_size = output_file.stat().st_size / (1024 * 1024)  # MB
        
        print(f"\n✅ 数据集生成完成!")
        print(f"  文件路径: {output_path}")
        print(f"  文件大小: {file_size:.2f} MB")
        print(f"  生成耗时: {elapsed:.2f} 秒")
        print(f"  平均速度: {self.total_messages/elapsed:,.0f} 条/秒")
    
    def _generate_normal_message(self, index: int) -> Dict:
        """生成正常消息"""
        # 随机选择参与者
        sender = random.choice(self.PARTICIPANTS)
        
        # 随机选择内容
        content = random.choice(self.NORMAL_TEMPLATES)
        
        # 生成时间戳（分布在最近90天）
        days_ago = random.randint(0, 90)
        hour = random.randint(8, 18)  # 工作时间
        minute = random.randint(0, 59)
        
        timestamp = (datetime.now() - timedelta(days=days_ago))
        timestamp = timestamp.replace(hour=hour, minute=minute)
        
        return {
            'id': f"msg_{index:08d}",
            'timestamp': timestamp.isoformat(),
            'sender': sender,
            'content': content,
            'type': 'normal'
        }
    
    def _generate_corruption_message(self, index: int) -> Dict:
        """生成腐败消息"""
        # 随机选择腐败模板
        template = random.choice(self.CORRUPTION_TEMPLATES)
        content, category, expected_risk = template[0], template[1], template[2]
        
        # 随机选择参与者（偏向使用职位高的）
        sender = random.choice(["刘经理", "王科长", "陈总", "周主任"])
        
        # 生成时间戳（偏向非工作时间）
        days_ago = random.randint(0, 90)
        
        # 70%概率在非工作时间
        if random.random() < 0.7:
            hour = random.choice([22, 23, 0, 1, 2, 3, 4, 5])  # 深夜
        else:
            hour = random.randint(8, 18)
        
        minute = random.randint(0, 59)
        
        timestamp = (datetime.now() - timedelta(days=days_ago))
        timestamp = timestamp.replace(hour=hour, minute=minute)
        
        return {
            'id': f"corr_{index:08d}",
            'timestamp': timestamp.isoformat(),
            'sender': sender,
            'content': content,
            'type': 'corruption',
            'category': category,
            'expected_risk': expected_risk
        }


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='生成大规模测试数据集')
    parser.add_argument('-n', '--num-messages', 
                       type=int, 
                       default=1000000,
                       help='总消息数 (默认: 1000000)')
    parser.add_argument('-r', '--corruption-rate',
                       type=float,
                       default=0.1,
                       help='腐败消息比例 (默认: 0.1)')
    parser.add_argument('-o', '--output',
                       type=str,
                       default='data/large_test_dataset.jsonl',
                       help='输出文件路径')
    
    args = parser.parse_args()
    
    # 创建生成器
    generator = LargeDatasetGenerator(
        total_messages=args.num_messages,
        corruption_rate=args.corruption_rate
    )
    
    # 生成数据
    generator.generate(args.output)


if __name__ == '__main__':
    main()
