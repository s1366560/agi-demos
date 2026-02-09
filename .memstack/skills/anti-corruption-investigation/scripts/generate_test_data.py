#!/usr/bin/env python3
"""
生成测试用聊天记录数据
"""

import json
import random
from datetime import datetime, timedelta

def generate_test_chat(output_file: str = "test_chat.json"):
    """生成测试聊天记录"""
    
    # 定义参与者
    participants = ["张三", "李四", "王五"]
    
    # 定义消息模板
    normal_messages = [
        "好的，我知道了",
        "明天见",
        "项目进展如何？",
        "需要我帮忙吗？",
        "收到",
        "谢谢",
        "不客气",
        "好的好的"
    ]
    
    suspicious_messages = [
        ("那笔钱准备好了吗？", "money_keywords"),
        ("今晚私下见面谈谈", "secret_meeting"),
        ("这个项目给老张安排一下", "power_abuse"),
        ("记得删除聊天记录", "evidence_concealment"),
        ("5万块现金已经准备好了", "money_keywords"),
        ("这件事别让其他人知道", "secret_meeting"),
        ("我会给你10%的回扣", "money_keywords"),
        ("领导那边我已经打过招呼了", "power_abuse"),
        ("把之前的转账记录都删了", "evidence_concealment"),
        ("明天凌晨3点老地方见", "secret_meeting"),
    ]
    
    messages = []
    base_time = datetime.now() - timedelta(days=30)
    
    # 生成100条消息
    for i in range(100):
        sender = random.choice(participants)
        
        # 10%的概率生成可疑消息
        if random.random() < 0.1:
            content, category = random.choice(suspicious_messages)
        else:
            content = random.choice(normal_messages)
        
        # 生成时间戳
        timestamp = base_time + timedelta(
            days=random.randint(0, 30),
            hours=random.randint(0, 23),
            minutes=random.randint(0, 59)
        )
        
        messages.append({
            "timestamp": timestamp.isoformat(),
            "sender": sender,
            "content": content
        })
    
    # 按时间排序
    messages.sort(key=lambda x: x["timestamp"])
    
    # 保存到文件
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 测试聊天记录已生成: {output_file}")
    print(f"📊 总消息数: {len(messages)}")
    print(f"👥 参与者: {', '.join(participants)}")


if __name__ == "__main__":
    generate_test_chat()
