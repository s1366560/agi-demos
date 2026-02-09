#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成测试数据 - 反腐败调查技能 v4.0
Generate Test Data for Anti-Corruption Investigation Skill v4.0
"""

import json
import random
from datetime import datetime, timedelta


def generate_relationship_test_data(output_path='data/relationship_test_data.jsonl', num_messages=5000):
    """生成关系网络测试数据
    
    Args:
        output_path: 输出文件路径
        num_messages: 消息数量
    """
    # 定义参与者
    participants = {
        'officials': ['张局长', '李处长', '王科长', '赵主任'],
        'business': ['刘总', '陈总', '孙总', '钱总'],
        'intermediaries': ['周秘书', '吴助理', '郑经理'],
        'suppliers': ['冯供应商', '卫承包商', '蒋商贩'],
        'family': ['沈妻', '韩子', '杨女'],
        'others': ['朱司机', '秦会计', '尤秘书']
    }
    
    all_people = []
    for group in participants.values():
        all_people.extend(group)
    
    # 定义关系模式
    relationships = {
        # 核心腐败团伙
        ('张局长', '刘总'): {'weight': 0.9, 'type': '资金'},
        ('张局长', '周秘书'): {'weight': 0.8, 'type': '权力'},
        ('刘总', '陈总'): {'weight': 0.7, 'type': '会面'},
        ('李处长', '孙总'): {'weight': 0.85, 'type': '资金'},
        ('王科长', '钱总'): {'weight': 0.75, 'type': '权力'},
        
        # 外围利益链
        ('陈总', '冯供应商'): {'weight': 0.6, 'type': '会面'},
        ('孙总', '卫承包商'): {'weight': 0.65, 'type': '资金'},
        ('钱总', '蒋商贩'): {'weight': 0.55, 'type': '普通'},
        
        # 中间人网络
        ('周秘书', '吴助理'): {'weight': 0.7, 'type': '秘密'},
        ('吴助理', '郑经理'): {'weight': 0.6, 'type': '普通'},
        
        # 家庭关系
        ('张局长', '沈妻'): {'weight': 0.5, 'type': '普通'},
        ('张局长', '韩子'): {'weight': 0.4, 'type': '普通'},
        ('刘总', '杨女'): {'weight': 0.3, 'type': '普通'},
    }
    
    # 定义消息模板
    message_templates = {
        'financial': [
            "那笔钱准备好了吗？",
            "这次的好处费怎么算？",
            "账户已经转过去了",
            "老规矩，20%的提成",
            "钱已经到账了，放心吧",
            "这次的分红什么时候发？"
        ],
        'power_abuse': [
            "招标的事情我已经安排好了",
            "技术参数按你们的要求调整了",
            "审批流程我会打招呼",
            "这个项目给你们做",
            "特殊照顾一下老朋友",
            "放心，我会关照的"
        ],
        'secret_meeting': [
            "今晚有空吗？老地方见",
            "这件事要保密，别告诉别人",
            "见面细说",
            "私下里处理就行",
            "别留下记录",
            "电话里不方便说"
        ],
        'collusion': [
            "大家统一一下口径",
            "对好说法再对外公布",
            "这个事情要配合好",
            "我们一起合作",
            "利益共享，风险共担"
        ],
        'evidence_destruction': [
            "聊天记录都清理了吗？",
            "把那些邮件删了",
            "备份文件要销毁",
            "不留痕迹",
            "这件事要烂在肚子里"
        ],
        'normal': [
            "好的，收到",
            "明天见",
            "文件我已经看了",
            "这个问题需要研究一下",
            "好的，没问题",
            "谢谢你的帮助"
        ]
    }
    
    # 生成消息
    messages = []
    base_time = datetime(2024, 1, 1)
    
    for i in range(num_messages):
        # 随机选择发送者
        sender = random.choice(all_people)
        
        # 根据关系选择接收者
        possible_receivers = []
        for (p1, p2), rel in relationships.items():
            if p1 == sender:
                possible_receivers.append((p2, rel))
            elif p2 == sender:
                possible_receivers.append((p1, rel))
        
        if not possible_receivers:
            receiver = random.choice([p for p in all_people if p != sender])
            relationship_type = 'normal'
        else:
            receiver, rel = random.choice(possible_receivers)
            relationship_type = rel['type']
        
        # 根据关系类型选择消息内容
        if relationship_type in ['financial', 'power_abuse', 'secret', '会面']:
            template_category = random.choice([
                'financial', 'power_abuse', 'secret_meeting',
                'collusion', 'evidence_destruction'
            ])
        else:
            template_category = random.choice(['normal'] * 7 + ['financial'])
        
        content = random.choice(message_templates[template_category])
        
        # 生成时间戳
        days_offset = random.randint(0, 90)
        hours_offset = random.randint(0, 23)
        timestamp = (base_time + timedelta(days=days_offset, hours=hours_offset)).isoformat()
        
        # 创建消息
        message = {
            'timestamp': timestamp,
            'sender': sender,
            'receiver': receiver,
            'content': content
        }
        
        messages.append(message)
    
    # 按时间排序
    messages.sort(key=lambda x: x['timestamp'])
    
    # 保存为JSONL格式
    with open(output_path, 'w', encoding='utf-8') as f:
        for msg in messages:
            f.write(json.dumps(msg, ensure_ascii=False) + '\n')
    
    print(f"✅ 已生成 {num_messages} 条测试消息")
    print(f"📂 文件路径: {output_path}")
    print(f"👥 参与人数: {len(all_people)}")
    print(f"🕐 时间跨度: 90天")
    print(f"🔗 关系数量: {len(relationships)}")


def generate_large_dataset(output_path='data/large_dataset.jsonl', num_messages=100000):
    """生成大规模数据集
    
    Args:
        output_path: 输出文件路径
        num_messages: 消息数量
    """
    # 简化版生成器，用于性能测试
    participants = [f"用户{i}" for i in range(1, 101)]  # 100个参与者
    
    message_templates = [
        "好的，收到",
        "明白了",
        "这个问题需要研究",
        "请尽快处理",
        "谢谢",
        "好的",
        "知道了",
        "没问题"
    ]
    
    suspicious_templates = [
        "那笔钱准备好了吗？",
        "老地方见",
        "这件事要保密",
        "招标的事情已经安排好了",
        "聊天记录都清理了吗？"
    ]
    
    messages = []
    base_time = datetime(2024, 1, 1)
    
    for i in range(num_messages):
        sender = random.choice(participants)
        receiver = random.choice([p for p in participants if p != sender])
        
        # 5%的消息包含可疑内容
        if random.random() < 0.05:
            content = random.choice(suspicious_templates)
        else:
            content = random.choice(message_templates)
        
        days_offset = random.randint(0, 365)
        hours_offset = random.randint(0, 23)
        timestamp = (base_time + timedelta(days=days_offset, hours=hours_offset)).isoformat()
        
        message = {
            'timestamp': timestamp,
            'sender': sender,
            'receiver': receiver,
            'content': content
        }
        
        messages.append(message)
    
    messages.sort(key=lambda x: x['timestamp'])
    
    with open(output_path, 'w', encoding='utf-8') as f:
        for msg in messages:
            f.write(json.dumps(msg, ensure_ascii=False) + '\n')
    
    print(f"✅ 已生成 {num_messages} 条大规模测试数据")
    print(f"📂 文件路径: {output_path}")


if __name__ == '__main__':
    import sys
    
    # 生成关系网络测试数据
    print("🔧 生成关系网络测试数据...")
    generate_relationship_test_data(num_messages=5000)
    
    # 生成大规模数据集
    print("\n🔧 生成大规模数据集...")
    generate_large_dataset(num_messages=100000)
    
    print("\n✅ 测试数据生成完成!")
