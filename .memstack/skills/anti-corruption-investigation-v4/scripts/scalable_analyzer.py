#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
反腐败调查技能 v4.0 - 可扩展消息分析器
Anti-Corruption Investigation Skill v4.0 - Scalable Message Analyzer

专门用于大规模聊天记录的消息分析，支持流式处理和并行计算
"""

import json
import re
from datetime import datetime
from typing import Dict, List, Tuple, Any
from collections import defaultdict
import multiprocessing as mp
from functools import partial


class ScalableAnalyzer:
    """可扩展的消息分析器"""
    
    def __init__(self, batch_size=10000, workers=None):
        """初始化分析器
        
        Args:
            batch_size: 批处理大小
            workers: 工作进程数
        """
        self.batch_size = batch_size
        self.workers = workers or mp.cpu_count()
        
        # 可疑模式定义
        self.suspicious_patterns = {
            'financial': [
                r'钱|款|转账|支付|费用|回扣|佣金|好处费',
                r'分红|利润|收益|酬金',
                r'账户|银行卡|转账记录'
            ],
            'power_abuse': [
                r'审批|通过|批准|同意',
                r'照顾|特殊|通融|破例',
                r'违规|暗箱操作|打招呼',
                r'招标|中标|投标|评标'
            ],
            'secret_meeting': [
                r'保密|秘密|私下|别说',
                r'删除|清理|销毁',
                r'见面|吃饭|喝茶|地方|老地方',
                r'电话|微信|私聊'
            ],
            'collusion': [
                r'统一口径|对好|说法',
                r'配合|协作|联手',
                r'利益|好处|分成'
            ],
            'evidence_destruction': [
                r'删除|清理|销毁|毁掉',
                r'记录|聊天|邮件|文件',
                r'备份|恢复|找回'
            ]
        }
        
        # 语义模式（隐晦表达）
        self.semantic_patterns = {
            'high_risk': [
                r'老地方|那个东西|老规矩|老习惯',
                r'意思意思|表示表示|懂不懂',
                r'安排|处理|搞定|办妥'
            ],
            'medium_risk': [
                r'方便|合适|机会',
                r'帮忙|协助|支持',
                r'关系|熟人|朋友'
            ]
        }
    
    def analyze_batch(self, messages: List[Dict]) -> List[Dict]:
        """分析一批消息
        
        Args:
            messages: 消息列表
            
        Returns:
            分析结果列表
        """
        results = []
        
        for msg in messages:
            result = self.analyze_message(msg)
            results.append(result)
        
        return results
    
    def analyze_message(self, msg: Dict) -> Dict:
        """分析单条消息
        
        Args:
            msg: 消息对象
            
        Returns:
            分析结果
        """
        content = msg.get('content', '')
        sender = msg.get('sender', '')
        timestamp = msg.get('timestamp', '')
        
        # 初始化结果
        result = {
            'sender': sender,
            'timestamp': timestamp,
            'content': content,
            'is_suspicious': False,
            'risk_level': 'low',
            'patterns': [],
            'semantic_risk': 0.0,
            'behavioral_flags': []
        }
        
        # 检测可疑模式
        suspicious_count = 0
        for category, patterns in self.suspicious_patterns.items():
            for pattern in patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    result['patterns'].append({
                        'category': category,
                        'pattern': pattern
                    })
                    suspicious_count += 1
        
        # 检测语义模式
        semantic_score = 0.0
        for risk_level, patterns in self.semantic_patterns.items():
            for pattern in patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    if risk_level == 'high_risk':
                        semantic_score += 0.3
                    else:
                        semantic_score += 0.1
        
        result['semantic_risk'] = min(semantic_score, 1.0)
        
        # 行为分析
        result['behavioral_flags'] = self.analyze_behavior(msg)
        
        # 判断是否可疑
        if suspicious_count > 0 or semantic_score > 0.3 or result['behavioral_flags']:
            result['is_suspicious'] = True
        
        # 计算风险等级
        risk_score = suspicious_count * 2 + semantic_score * 5 + len(result['behavioral_flags'])
        if risk_score >= 5:
            result['risk_level'] = 'high'
        elif risk_score >= 2:
            result['risk_level'] = 'medium'
        
        return result
    
    def analyze_behavior(self, msg: Dict) -> List[str]:
        """分析行为异常
        
        Args:
            msg: 消息对象
            
        Returns:
            异常行为列表
        """
        flags = []
        timestamp = msg.get('timestamp', '')
        content = msg.get('content', '')
        
        # 时间异常分析
        if timestamp:
            try:
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                hour = dt.hour
                weekday = dt.weekday()
                
                # 深夜聊天 (22:00-02:00)
                if hour >= 22 or hour <= 2:
                    flags.append('深夜聊天')
                
                # 工作时间外 (周末或非工作时间)
                if weekday >= 5 or hour < 9 or hour > 18:
                    flags.append('非工作时间')
                    
            except:
                pass
        
        # 内容异常
        if len(content) < 10:
            flags.append('内容过短')
        elif len(content) > 500:
            flags.append('内容过长')
        
        # 敏感词
        sensitive_words = ['删除', '清理', '保密', '别说', '别告诉']
        if any(word in content for word in sensitive_words):
            flags.append('敏感操作')
        
        return flags
    
    def analyze_large_dataset(self, input_path: str, output_path: str) -> Dict[str, Any]:
        """分析大规模数据集
        
        Args:
            input_path: 输入文件路径 (JSONL格式)
            output_path: 输出文件路径
            
        Returns:
            分析结果摘要
        """
        print(f"🚀 开始分析大规模数据集...")
        print(f"📂 输入文件: {input_path}")
        print(f"⚙️ 批处理大小: {self.batch_size}")
        print(f"🔧 工作进程: {self.workers}")
        
        # 统计信息
        total_messages = 0
        suspicious_messages = 0
        risk_distribution = defaultdict(int)
        pattern_counts = defaultdict(int)
        behavioral_counts = defaultdict(int)
        sender_stats = defaultdict(lambda: {
            'total': 0,
            'suspicious': 0,
            'patterns': []
        })
        
        # 流式处理文件
        batch = []
        results_batch = []
        
        print("\n📊 流式处理数据...")
        with open(input_path, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                
                try:
                    msg = json.loads(line)
                    batch.append(msg)
                    total_messages += 1
                    
                    # 批处理
                    if len(batch) >= self.batch_size:
                        results_batch = self.analyze_batch(batch)
                        
                        # 统计结果
                        for result in results_batch:
                            if result['is_suspicious']:
                                suspicious_messages += 1
                                risk_distribution[result['risk_level']] += 1
                                
                                # 统计模式
                                for pattern in result['patterns']:
                                    pattern_counts[pattern['category']] += 1
                                
                                # 统计行为异常
                                for flag in result['behavioral_flags']:
                                    behavioral_counts[flag] += 1
                            
                            # 统计发送者
                            sender = result['sender']
                            sender_stats[sender]['total'] += 1
                            if result['is_suspicious']:
                                sender_stats[sender]['suspicious'] += 1
                                sender_stats[sender]['patterns'].extend([
                                    p['category'] for p in result['patterns']
                                ])
                        
                        batch = []
                        
                        # 显示进度
                        if total_messages % (self.batch_size * 10) == 0:
                            print(f"   已处理: {total_messages:,} 条消息")
                
                except json.JSONDecodeError:
                    continue
        
        # 处理最后一批
        if batch:
            results_batch = self.analyze_batch(batch)
            for result in results_batch:
                if result['is_suspicious']:
                    suspicious_messages += 1
                    risk_distribution[result['risk_level']] += 1
                    
                    for pattern in result['patterns']:
                        pattern_counts[pattern['category']] += 1
                    
                    for flag in result['behavioral_flags']:
                        behavioral_counts[flag] += 1
                
                sender = result['sender']
                sender_stats[sender]['total'] += 1
                if result['is_suspicious']:
                    sender_stats[sender]['suspicious'] += 1
                    sender_stats[sender]['patterns'].extend([
                        p['category'] for p in result['patterns']
                    ])
        
        # 计算风险评分
        suspicious_ratio = suspicious_messages / max(total_messages, 1)
        high_risk_ratio = risk_distribution.get('high', 0) / max(total_messages, 1)
        
        risk_score = (
            suspicious_ratio * 5 +
            high_risk_ratio * 3 +
            len(pattern_counts) * 0.5
        )
        risk_score = min(risk_score, 10.0)
        
        # 确定风险等级
        if risk_score >= 7:
            overall_risk = '高'
        elif risk_score >= 4:
            overall_risk = '中'
        else:
            overall_risk = '低'
        
        # 识别关键人物
        key_players = []
        for sender, stats in sender_stats.items():
            if stats['suspicious'] > 0:
                suspicious_ratio = stats['suspicious'] / stats['total']
                key_players.append({
                    'name': sender,
                    'total_messages': stats['total'],
                    'suspicious_messages': stats['suspicious'],
                    'suspicious_ratio': round(suspicious_ratio, 3),
                    'top_patterns': stats['patterns'][:5]
                })
        
        key_players.sort(key=lambda x: x['suspicious_ratio'], reverse=True)
        
        # 构建结果
        results = {
            'overall_risk': overall_risk,
            'risk_score': round(risk_score, 2),
            'statistics': {
                'total_messages': total_messages,
                'suspicious_messages': suspicious_messages,
                'suspicious_ratio': round(suspicious_ratio, 3),
                'risk_distribution': dict(risk_distribution)
            },
            'pattern_analysis': dict(pattern_counts),
            'behavioral_analysis': dict(behavioral_counts),
            'key_players': key_players[:10],
            'recommendations': self.generate_recommendations(
                overall_risk, pattern_counts, behavioral_counts
            )
        }
        
        # 保存结果
        self.save_report(results, output_path)
        
        # 打印摘要
        self.print_summary(results)
        
        return results
    
    def generate_recommendations(self, risk_level: str, 
                                patterns: Dict[str, int],
                                behaviors: Dict[str, int]) -> List[str]:
        """生成处理建议
        
        Args:
            risk_level: 风险等级
            patterns: 模式统计
            behaviors: 行为统计
            
        Returns:
            建议列表
        """
        recommendations = []
        
        # 基于风险等级的建议
        if risk_level == '高':
            recommendations.extend([
                '立即开展深入调查',
                '对关键人物进行重点监控',
                '收集和保护相关证据',
                '考虑采取预防性措施'
            ])
        elif risk_level == '中':
            recommendations.extend([
                '加强监控和关注',
                '收集更多信息',
                '定期评估风险变化'
            ])
        else:
            recommendations.extend([
                '保持常规监控',
                '定期复查'
            ])
        
        # 基于模式的建议
        if patterns.get('financial', 0) > 10:
            recommendations.append('重点调查资金往来情况')
        
        if patterns.get('power_abuse', 0) > 10:
            recommendations.append('审查相关审批和决策过程')
        
        if patterns.get('evidence_destruction', 0) > 5:
            recommendations.append('立即采取措施保护证据')
        
        # 基于行为的建议
        if behaviors.get('深夜聊天', 0) > 20:
            recommendations.append('关注非工作时间活动')
        
        if behaviors.get('敏感操作', 0) > 10:
            recommendations.append('加强数据安全管理')
        
        return recommendations
    
    def save_report(self, results: Dict[str, Any], output_path: str):
        """保存分析报告
        
        Args:
            results: 分析结果
            output_path: 输出文件路径
        """
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print(f"\n✅ 报告已保存: {output_path}")
        except Exception as e:
            print(f"\n❌ 保存报告失败: {e}")
    
    def print_summary(self, results: Dict[str, Any]):
        """打印分析摘要
        
        Args:
            results: 分析结果
        """
        print("\n" + "="*60)
        print("📊 反腐败调查分析报告")
        print("="*60)
        
        stats = results['statistics']
        print(f"\n📈 统计信息:")
        print(f"  总消息数: {stats['total_messages']:,}")
        print(f"  可疑消息: {stats['suspicious_messages']:,}")
        print(f"  可疑比例: {stats['suspicious_ratio']:.1%}")
        
        print(f"\n🎯 风险评估:")
        print(f"  风险等级: 🟢{results['overall_risk']}" if results['overall_risk'] == '低' else
              f"  风险等级: 🟡{results['overall_risk']}" if results['overall_risk'] == '中' else
              f"  风险等级: 🔴{results['overall_risk']}")
        print(f"  风险分数: {results['risk_score']}/10")
        
        if results['pattern_analysis']:
            print(f"\n🔍 可疑模式:")
            for pattern, count in sorted(results['pattern_analysis'].items(), 
                                        key=lambda x: x[1], reverse=True):
                print(f"  {pattern}: {count} 次")
        
        if results['behavioral_analysis']:
            print(f"\n⚠️ 行为异常:")
            for behavior, count in sorted(results['behavioral_analysis'].items(),
                                         key=lambda x: x[1], reverse=True):
                print(f"  {behavior}: {count} 次")
        
        if results['key_players']:
            print(f"\n👥 关键人物 (Top 5):")
            for i, player in enumerate(results['key_players'][:5], 1):
                print(f"  {i}. {player['name']}")
                print(f"     可疑消息: {player['suspicious_messages']}/{player['total_messages']}")
                print(f"     可疑比例: {player['suspicious_ratio']:.1%}")
        
        if results['recommendations']:
            print(f"\n💡 处理建议:")
            for i, rec in enumerate(results['recommendations'], 1):
                print(f"  {i}. {rec}")
        
        print("\n" + "="*60)


def main():
    """主函数"""
    import sys
    
    if len(sys.argv) < 3:
        print("用法: python scalable_analyzer.py <input_file> <output_file>")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2]
    
    # 创建分析器
    analyzer = ScalableAnalyzer(batch_size=10000, workers=8)
    
    # 分析数据
    results = analyzer.analyze_large_dataset(input_file, output_file)
    
    print("\n✅ 分析完成!")


if __name__ == '__main__':
    main()
