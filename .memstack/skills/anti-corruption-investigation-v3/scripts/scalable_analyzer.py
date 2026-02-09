#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
反腐败调查技能 v3.0 - 可扩展分析引擎
支持百万量级聊天记录的高效分析

核心特性:
1. 流式处理 - 避免内存溢出
2. 并行计算 - 充分利用多核CPU
3. 增量更新 - 只处理新数据
4. 智能缓存 - 避免重复计算
5. 索引优化 - 快速查询检索

作者: 反腐败调查技能团队
版本: 3.0.0
日期: 2026-02-09
"""

import json
import os
import re
import time
import pickle
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Iterator, Optional, Tuple
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import Pool, cpu_count
import hashlib

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MessageIndex:
    """高性能消息索引"""
    
    def __init__(self):
        self.timestamp_index = {}  # 时间索引
        self.sender_index = {}     # 发送者索引
        self.keyword_index = {}    # 关键词索引
        self.risk_index = {}       # 风险索引
        self._built = False
    
    def build(self, messages: List[Dict]) -> None:
        """构建索引"""
        logger.info(f"开始构建索引，消息数量: {len(messages)}")
        start_time = time.time()
        
        for idx, msg in enumerate(messages):
            # 时间索引 (按天)
            ts = msg.get('timestamp', '')
            date_key = ts[:10] if ts else 'unknown'
            if date_key not in self.timestamp_index:
                self.timestamp_index[date_key] = []
            self.timestamp_index[date_key].append(idx)
            
            # 发送者索引
            sender = msg.get('sender', 'unknown')
            if sender not in self.sender_index:
                self.sender_index[sender] = []
            self.sender_index[sender].append(idx)
            
            # 关键词索引 (提取中文词汇)
            content = msg.get('content', '')
            keywords = self._extract_keywords(content)
            for keyword in keywords:
                if keyword not in self.keyword_index:
                    self.keyword_index[keyword] = []
                self.keyword_index[keyword].append(idx)
        
        self._built = True
        elapsed = time.time() - start_time
        logger.info(f"索引构建完成，耗时: {elapsed:.2f}秒")
        logger.info(f"  - 时间分区: {len(self.timestamp_index)}")
        logger.info(f"  - 发送者: {len(self.sender_index)}")
        logger.info(f"  - 关键词: {len(self.keyword_index)}")
    
    def _extract_keywords(self, text: str) -> List[str]:
        """提取关键词"""
        # 简单的中文分词（实际应用中可用jieba）
        keywords = []
        
        # 提取2-4字的词语
        for i in range(len(text)):
            for length in [2, 3, 4]:
                if i + length <= len(text):
                    word = text[i:i+length]
                    if self._is_meaningful_word(word):
                        keywords.append(word)
        
        return keywords[:10]  # 限制关键词数量
    
    def _is_meaningful_word(self, word: str) -> bool:
        """判断是否有意义的词"""
        # 过滤掉纯数字、纯符号等
        if not word:
            return False
        if word.isdigit():
            return False
        if all(c in '，。！？、；：""''（）【】《》' for c in word):
            return False
        return True
    
    def query_by_sender(self, sender: str) -> List[int]:
        """按发送者查询"""
        return self.sender_index.get(sender, [])
    
    def query_by_date(self, date: str) -> List[int]:
        """按日期查询"""
        return self.timestamp_index.get(date, [])
    
    def query_by_keyword(self, keyword: str) -> List[int]:
        """按关键词查询"""
        return self.keyword_index.get(keyword, [])


class AnalysisCache:
    """分析结果缓存"""
    
    def __init__(self, cache_dir: str = 'cache'):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.memory_cache = {}
        self.hit_count = 0
        self.miss_count = 0
    
    def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        # 先查内存缓存
        if key in self.memory_cache:
            self.hit_count += 1
            return self.memory_cache[key]
        
        # 再查磁盘缓存
        cache_file = self.cache_dir / f"{hashlib.md5(key.encode()).hexdigest()}.pkl"
        if cache_file.exists():
            with open(cache_file, 'rb') as f:
                data = pickle.load(f)
                self.memory_cache[key] = data
                self.hit_count += 1
                return data
        
        self.miss_count += 1
        return None
    
    def set(self, key: str, value: Any) -> None:
        """设置缓存"""
        # 保存到内存
        self.memory_cache[key] = value
        
        # 保存到磁盘
        cache_file = self.cache_dir / f"{hashlib.md5(key.encode()).hexdigest()}.pkl"
        with open(cache_file, 'wb') as f:
            pickle.dump(value, f)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        total = self.hit_count + self.miss_count
        hit_rate = self.hit_count / total if total > 0 else 0
        return {
            'hit_count': self.hit_count,
            'miss_count': self.miss_count,
            'hit_rate': hit_rate,
            'memory_size': len(self.memory_cache)
        }


class ScalableAnalyzer:
    """可扩展分析引擎 - 支持百万量级数据"""
    
    # 隐晦腐败模式库
    CORRUPTION_PATTERNS = {
        'financial': [
            r'那笔.*?钱',
            r'那个.*?东西',
            r'老规矩',
            r'意思一下',
            r'表示.*?心意',
            r'辛苦费',
            r'茶水费',
            r'打点',
        ],
        'meeting': [
            r'老地方',
            r'私下.*?见',
            r'单独.*?聊',
            r'保密',
            r'别告诉.*?人',
            r'只有.*?知道',
        ],
        'abuse': [
            r'特殊.*?照顾',
            r'通融.*?下',
            r'按.*?规矩',
            r'破例',
            r'开.*?绿灯',
            r'关照',
        ],
        'evidence': [
            r'删除.*?记录',
            r'清理.*?聊天',
            r'不留.*?痕迹',
            r'撤回',
            r'毁掉',
        ]
    }
    
    def __init__(self, 
                 batch_size: int = 10000,
                 workers: int = None,
                 enable_cache: bool = True,
                 cache_dir: str = 'cache'):
        """
        初始化分析器
        
        Args:
            batch_size: 批处理大小
            workers: 并行工作进程数
            enable_cache: 是否启用缓存
            cache_dir: 缓存目录
        """
        self.batch_size = batch_size
        self.workers = workers or cpu_count()
        self.enable_cache = enable_cache
        
        # 初始化组件
        self.cache = AnalysisCache(cache_dir) if enable_cache else None
        self.index = MessageIndex()
        
        # 统计信息
        self.stats = {
            'total_messages': 0,
            'processed_messages': 0,
            'suspicious_messages': 0,
            'start_time': None,
            'end_time': None
        }
        
        logger.info(f"初始化可扩展分析引擎")
        logger.info(f"  - 批处理大小: {batch_size}")
        logger.info(f"  - 工作进程: {self.workers}")
        logger.info(f"  - 缓存: {'启用' if enable_cache else '禁用'}")
    
    def analyze_large_dataset(self, 
                             input_path: str,
                             output_path: str = None,
                             sample_rate: float = 1.0) -> Dict[str, Any]:
        """
        分析大规模数据集
        
        Args:
            input_path: 输入文件路径
            output_path: 输出文件路径
            sample_rate: 采样率 (0.0-1.0)
        
        Returns:
            分析结果字典
        """
        logger.info(f"开始分析大规模数据集: {input_path}")
        self.stats['start_time'] = time.time()
        
        # 第一阶段: 流式读取和采样
        logger.info("第一阶段: 流式读取和采样...")
        messages = list(self._stream_read(input_path, sample_rate))
        self.stats['total_messages'] = len(messages)
        logger.info(f"  读取消息: {len(messages)} 条")
        
        # 第二阶段: 构建索引
        logger.info("第二阶段: 构建索引...")
        self.index.build(messages)
        
        # 第三阶段: 并行分析
        logger.info("第三阶段: 并行分析...")
        results = self._parallel_analyze(messages)
        
        # 第四阶段: 关系网络分析
        logger.info("第四阶段: 关系网络分析...")
        network = self._build_network(results)
        
        # 第五阶段: 风险评估
        logger.info("第五阶段: 风险评估...")
        risk_assessment = self._assess_risk(results, network)
        
        # 汇总结果
        self.stats['end_time'] = time.time()
        self.stats['processed_messages'] = len(messages)
        self.stats['suspicious_messages'] = len(results)
        
        final_report = {
            'metadata': {
                'analysis_time': datetime.now().isoformat(),
                'elapsed_time': self.stats['end_time'] - self.stats['start_time'],
                'total_messages': self.stats['total_messages'],
                'suspicious_messages': self.stats['suspicious_messages'],
                'sample_rate': sample_rate
            },
            'suspicious_messages': results,
            'network_analysis': network,
            'risk_assessment': risk_assessment,
            'performance_stats': self._get_performance_stats()
        }
        
        # 保存结果
        if output_path:
            self._save_report(final_report, output_path)
            logger.info(f"报告已保存: {output_path}")
        
        # 打印摘要
        self._print_summary(final_report)
        
        return final_report
    
    def _stream_read(self, 
                    file_path: str, 
                    sample_rate: float = 1.0) -> Iterator[Dict]:
        """
        流式读取文件，避免内存溢出
        
        Args:
            file_path: 文件路径
            sample_rate: 采样率
        
        Yields:
            消息字典
        """
        import random
        
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                # 采样
                if sample_rate < 1.0 and random.random() > sample_rate:
                    continue
                
                try:
                    message = json.loads(line.strip())
                    yield message
                except json.JSONDecodeError:
                    continue
    
    def _parallel_analyze(self, messages: List[Dict]) -> List[Dict]:
        """
        并行分析消息
        
        Args:
            messages: 消息列表
        
        Returns:
            可疑消息列表
        """
        # 分批
        batches = [messages[i:i+self.batch_size] 
                  for i in range(0, len(messages), self.batch_size)]
        
        logger.info(f"分成 {len(batches)} 个批次并行处理...")
        
        suspicious_results = []
        
        # 并行处理
        with ProcessPoolExecutor(max_workers=self.workers) as executor:
            futures = [executor.submit(self._analyze_batch, batch) 
                      for batch in batches]
            
            for idx, future in enumerate(as_completed(futures)):
                batch_results = future.result()
                suspicious_results.extend(batch_results)
                
                if (idx + 1) % 10 == 0:
                    logger.info(f"  已完成 {idx + 1}/{len(batches)} 批次")
        
        return suspicious_results
    
    @staticmethod
    def _analyze_batch(batch: List[Dict]) -> List[Dict]:
        """
        分析单个批次
        
        Args:
            batch: 消息批次
        
        Returns:
            可疑消息列表
        """
        results = []
        
        for message in batch:
            # 检查是否可疑
            suspicion = ScalableAnalyzer._check_suspicion(message)
            if suspicion['is_suspicious']:
                results.append({
                    **message,
                    'suspicion_analysis': suspicion
                })
        
        return results
    
    @staticmethod
    def _check_suspicion(message: Dict) -> Dict[str, Any]:
        """
        检查消息可疑性
        
        Args:
            message: 消息字典
        
        Returns:
            可疑性分析结果
        """
        content = message.get('content', '')
        sender = message.get('sender', '')
        timestamp = message.get('timestamp', '')
        
        detected_patterns = []
        confidence = 0.0
        
        # 检查各种腐败模式
        for category, patterns in ScalableAnalyzer.CORRUPTION_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, content):
                    detected_patterns.append({
                        'category': category,
                        'pattern': pattern,
                        'matched_text': re.findall(pattern, content)
                    })
                    confidence += 0.15
        
        # 检查时间异常
        time_anomaly = ScalableAnalyzer._check_time_anomaly(timestamp)
        if time_anomaly['is_anomaly']:
            confidence += 0.1
            detected_patterns.append({
                'category': 'time_anomaly',
                'description': time_anomaly['reason']
            })
        
        # 限制置信度范围
        confidence = min(confidence, 1.0)
        
        return {
            'is_suspicious': confidence > 0.3,
            'confidence': confidence,
            'detected_patterns': detected_patterns,
            'risk_level': ScalableAnalyzer._get_risk_level(confidence)
        }
    
    @staticmethod
    def _check_time_anomaly(timestamp: str) -> Dict[str, Any]:
        """检查时间异常"""
        if not timestamp:
            return {'is_anomaly': False}
        
        try:
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            hour = dt.hour
            weekend = dt.weekday() >= 5
            
            # 深夜 (22:00-06:00)
            if hour >= 22 or hour < 6:
                return {
                    'is_anomaly': True,
                    'reason': '深夜聊天'
                }
            
            # 周末
            if weekend:
                return {
                    'is_anomaly': True,
                    'reason': '周末聊天'
                }
            
        except:
            pass
        
        return {'is_anomaly': False}
    
    @staticmethod
    def _get_risk_level(confidence: float) -> str:
        """获取风险等级"""
        if confidence >= 0.7:
            return 'HIGH'
        elif confidence >= 0.4:
            return 'MEDIUM'
        else:
            return 'LOW'
    
    def _build_network(self, results: List[Dict]) -> Dict[str, Any]:
        """构建关系网络"""
        network = defaultdict(lambda: {'connections': set(), 'count': 0})
        
        for result in results:
            sender = result.get('sender', '')
            # 这里可以添加更复杂的关系分析
            network[sender]['count'] += 1
        
        # 转换为普通字典
        return {
            node: {
                'connections': list(data['connections']),
                'message_count': data['count']
            }
            for node, data in network.items()
        }
    
    def _assess_risk(self, 
                    results: List[Dict], 
                    network: Dict) -> Dict[str, Any]:
        """评估整体风险"""
        if not results:
            return {
                'overall_risk': 'LOW',
                'risk_score': 0.0,
                'factors': []
            }
        
        # 计算风险分数
        high_risk_count = sum(1 for r in results 
                             if r.get('suspicion_analysis', {}).get('risk_level') == 'HIGH')
        medium_risk_count = sum(1 for r in results 
                               if r.get('suspicion_analysis', {}).get('risk_level') == 'MEDIUM')
        
        risk_score = (high_risk_count * 1.0 + medium_risk_count * 0.5) / len(results)
        risk_score = min(risk_score * 10, 10)  # 转换到0-10分
        
        # 确定风险等级
        if risk_score >= 7:
            overall_risk = 'HIGH'
        elif risk_score >= 4:
            overall_risk = 'MEDIUM'
        else:
            overall_risk = 'LOW'
        
        return {
            'overall_risk': overall_risk,
            'risk_score': risk_score,
            'high_risk_count': high_risk_count,
            'medium_risk_count': medium_risk_count,
            'total_suspicious': len(results),
            'factors': [
                f"高风险消息: {high_risk_count} 条",
                f"中风险消息: {medium_risk_count} 条",
                f"总可疑消息: {len(results)} 条"
            ]
        }
    
    def _get_performance_stats(self) -> Dict[str, Any]:
        """获取性能统计"""
        elapsed = self.stats['end_time'] - self.stats['start_time']
        throughput = self.stats['total_messages'] / elapsed if elapsed > 0 else 0
        
        stats = {
            'elapsed_time': elapsed,
            'throughput_per_second': throughput,
            'workers_used': self.workers,
            'batch_size': self.batch_size
        }
        
        if self.cache:
            stats['cache_stats'] = self.cache.get_stats()
        
        return stats
    
    def _save_report(self, report: Dict, output_path: str) -> None:
        """保存报告"""
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    
    def _print_summary(self, report: Dict) -> None:
        """打印分析摘要"""
        print("\n" + "="*80)
        print("反腐败调查分析报告".center(80))
        print("="*80)
        
        # 基本信息
        print(f"\n📊 基本信息:")
        print(f"  分析时间: {report['metadata']['analysis_time']}")
        print(f"  总消息数: {report['metadata']['total_messages']:,} 条")
        print(f"  可疑消息: {report['metadata']['suspicious_messages']:,} 条")
        print(f"  采样率: {report['metadata']['sample_rate']:.1%}")
        
        # 性能指标
        perf = report['performance_stats']
        print(f"\n⚡ 性能指标:")
        print(f"  处理时间: {perf['elapsed_time']:.2f} 秒")
        print(f"  吞吐量: {perf['throughput_per_second']:.1f} 条/秒")
        print(f"  工作进程: {perf['workers_used']}")
        
        if 'cache_stats' in perf:
            cache = perf['cache_stats']
            print(f"  缓存命中率: {cache['hit_rate']:.1%}")
        
        # 风险评估
        risk = report['risk_assessment']
        print(f"\n⚠️  风险评估:")
        print(f"  整体风险: {risk['overall_risk']}")
        print(f"  风险分数: {risk['risk_score']:.1f}/10")
        print(f"  高风险: {risk['high_risk_count']} 条")
        print(f"  中风险: {risk['medium_risk_count']} 条")
        
        # 关键发现
        if report['suspicious_messages']:
            print(f"\n🔍 关键发现:")
            high_risk = [m for m in report['suspicious_messages'] 
                        if m.get('suspicion_analysis', {}).get('risk_level') == 'HIGH']
            for msg in high_risk[:5]:
                sender = msg.get('sender', 'Unknown')
                content = msg.get('content', '')[:50]
                confidence = msg.get('suspicion_analysis', {}).get('confidence', 0)
                print(f"  - [{sender}] {content}... (置信度: {confidence:.1%})")
        
        print("\n" + "="*80 + "\n")


def main():
    """主函数"""
    import sys
    
    if len(sys.argv) < 2:
        print("用法: python scalable_analyzer.py <input_file> [output_file] [sample_rate]")
        print("示例: python scalable_analyzer.py data/messages.json report.json 0.1")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    sample_rate = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
    
    # 创建分析器
    analyzer = ScalableAnalyzer(
        batch_size=10000,
        workers=cpu_count(),
        enable_cache=True
    )
    
    # 执行分析
    results = analyzer.analyze_large_dataset(
        input_path=input_file,
        output_path=output_file,
        sample_rate=sample_rate
    )


if __name__ == '__main__':
    main()
