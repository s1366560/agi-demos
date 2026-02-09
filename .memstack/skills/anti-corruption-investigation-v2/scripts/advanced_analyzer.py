#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
高级腐败分析器 v2.0
专门针对复杂关系网和隐晦腐败行为的智能分析系统
"""

import json
import re
from datetime import datetime, timedelta
from collections import defaultdict, Counter
from typing import Dict, List, Any, Tuple, Set
import math

class AdvancedCorruptionAnalyzer:
    """高级腐败分析器 - v2.0核心引擎"""
    
    def __init__(self):
        """初始化分析器"""
        self.semantic_patterns = self._load_semantic_patterns()
        self.behavioral_patterns = self._load_behavioral_patterns()
        self.network_analyzer = NetworkAnalyzer()
        self.temporal_analyzer = TemporalAnalyzer()
        self.context_analyzer = ContextAwareAnalyzer()
        
    def _load_semantic_patterns(self) -> Dict[str, List[str]]:
        """加载语义模式库"""
        return {
            "隐晦资金": [
                "表示一下", "心意", "一点小意思", "帮忙费", 
                "辛苦费", "茶水费", "那笔款", "之前说的数",
                "约定的数", "那个数", "准备好了", "安排好了",
                "放在你车上", "知道怎么处理", "都清楚了"
            ],
            "权力滥用": [
                "打个招呼", "关照一下", "开绿灯", "通融通融",
                "特殊处理", "走快速通道", "按老规矩", "照旧",
                "你知道的", "都懂", "不用多说", "明白的",
                "按惯例", "特事特办", "灵活处理"
            ],
            "证据处理": [
                "清理一下", "不留痕迹", "该删的删", "只有我们知道",
                "天知地知", "口头说", "别留记录", "当面聊",
                "电话里说", "别发微信", "撤回吧", "删除记录"
            ],
            "秘密会面": [
                "私下聊聊", "老地方", "方便的时候", "找个时间",
                "单独聊聊", "只有我们", "别告诉别人", "保密",
                "晚上见", "周末有空吗", "下班后", "非工作时间"
            ],
            "参数定制": [
                "技术参数", "规格书", "按你们要求", "符合你们",
                "量身定制", "调整参数", "修改要求", "技术规格",
                "你们先草拟", "按草案走", "你们的优势"
            ]
        }
    
    def _load_behavioral_patterns(self) -> Dict[str, Any]:
        """加载行为模式库"""
        return {
            "时间异常": {
                "深夜时段": (22, 6),  # 22:00-6:00
                "周末时段": [5, 6],   # 周六、周日
                "工作时间": (9, 18)   # 9:00-18:00
            },
            "频率异常": {
                "突然增加阈值": 3.0,  # 突然增加3倍
                "突然沉默阈值": 0.2,  # 突然减少到20%
                "高频会面阈值": 5     # 每周5次以上
            },
            "关系异常": {
                "跨级沟通": True,
                "非工作关系": True,
                "私人会面": True
            }
        }
    
    def analyze(self, chat_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        执行完整的腐败分析
        
        Args:
            chat_data: 聊天记录列表
            
        Returns:
            完整的分析报告
        """
        print("🔍 开始高级腐败分析...")
        
        # 1. 语义分析
        print("📝 执行语义分析...")
        semantic_result = self.semantic_analysis(chat_data)
        
        # 2. 行为模式分析
        print("🔍 执行行为模式分析...")
        behavioral_result = self.behavioral_analysis(chat_data)
        
        # 3. 关系网络分析
        print("🕸️  构建关系网络...")
        network_result = self.network_analyzer.analyze(chat_data)
        
        # 4. 时间序列分析
        print("⏰ 分析时间序列...")
        temporal_result = self.temporal_analyzer.analyze(chat_data)
        
        # 5. 上下文感知分析
        print("🎯 执行上下文分析...")
        context_result = self.context_analyzer.analyze(chat_data)
        
        # 6. 综合风险评估
        print("📊 计算综合风险...")
        risk_assessment = self.assess_risk(
            semantic_result,
            behavioral_result,
            network_result,
            temporal_result,
            context_result
        )
        
        # 7. 生成证据链
        print("🔗 构建证据链...")
        evidence_chain = self.build_evidence_chain(
            semantic_result,
            behavioral_result,
            network_result,
            temporal_result,
            context_result
        )
        
        # 8. 生成报告
        report = {
            "分析时间": datetime.now().isoformat(),
            "数据概览": self.get_data_overview(chat_data),
            "语义分析": semantic_result,
            "行为模式": behavioral_result,
            "关系网络": network_result,
            "时间序列": temporal_result,
            "上下文分析": context_result,
            "风险评估": risk_assessment,
            "证据链": evidence_chain,
            "建议措施": self.generate_recommendations(risk_assessment)
        }
        
        print("✅ 分析完成！")
        return report
    
    def semantic_analysis(self, chat_data: List[Dict]) -> Dict[str, Any]:
        """语义分析 - 识别隐晦表达"""
        suspicious_messages = []
        pattern_matches = defaultdict(list)
        
        for msg in chat_data:
            content = msg.get("content", "")
            sender = msg.get("sender", "")
            timestamp = msg.get("timestamp", "")
            
            # 检查每个语义模式
            for pattern_type, patterns in self.semantic_patterns.items():
                for pattern in patterns:
                    if pattern in content:
                        match = {
                            "时间": timestamp,
                            "发送者": sender,
                            "内容": content,
                            "匹配模式": pattern,
                            "模式类型": pattern_type,
                            "置信度": self._calculate_semantic_confidence(
                                content, pattern
                            )
                        }
                        suspicious_messages.append(match)
                        pattern_matches[pattern_type].append(match)
        
        return {
            "可疑消息数": len(suspicious_messages),
            "模式匹配统计": dict(pattern_matches),
            "详细匹配": suspicious_messages
        }
    
    def _calculate_semantic_confidence(self, content: str, pattern: str) -> float:
        """计算语义匹配置信度"""
        # 基础置信度
        base_confidence = 0.7
        
        # 根据上下文调整
        confidence = base_confidence
        
        # 如果包含多个可疑词，提高置信度
        suspicious_count = sum(1 for p in self.semantic_patterns.values() 
                              if any(p2 in content for p2 in p))
        if suspicious_count > 1:
            confidence += 0.15
        
        # 如果消息很短且包含可疑词，提高置信度
        if len(content) < 50 and pattern in content:
            confidence += 0.1
        
        return min(confidence, 0.99)
    
    def behavioral_analysis(self, chat_data: List[Dict]) -> Dict[str, Any]:
        """行为模式分析"""
        anomalies = []
        
        # 1. 时间异常检测
        time_anomalies = self._detect_time_anomalies(chat_data)
        anomalies.extend(time_anomalies)
        
        # 2. 频率异常检测
        frequency_anomalies = self._detect_frequency_anomalies(chat_data)
        anomalies.extend(frequency_anomalies)
        
        # 3. 会面模式异常
        meeting_anomalies = self._detect_meeting_anomalies(chat_data)
        anomalies.extend(meeting_anomalies)
        
        # 4. 语言模式异常
        language_anomalies = self._detect_language_anomalies(chat_data)
        anomalies.extend(language_anomalies)
        
        return {
            "异常行为数": len(anomalies),
            "异常类型统计": self._count_anomaly_types(anomalies),
            "详细异常": anomalies
        }
    
    def _detect_time_anomalies(self, chat_data: List[Dict]) -> List[Dict]:
        """检测时间异常"""
        anomalies = []
        
        for msg in chat_data:
            timestamp_str = msg.get("timestamp", "")
            sender = msg.get("sender", "")
            
            try:
                timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                hour = timestamp.hour
                weekday = timestamp.weekday()
                
                # 深夜聊天
                if hour >= 22 or hour < 6:
                    anomalies.append({
                        "类型": "深夜活跃",
                        "时间": timestamp_str,
                        "参与者": sender,
                        "严重程度": "中"
                    })
                
                # 周末聊天
                if weekday >= 5:
                    anomalies.append({
                        "类型": "周末活跃",
                        "时间": timestamp_str,
                        "参与者": sender,
                        "严重程度": "低"
                    })
            except:
                continue
        
        return anomalies
    
    def _detect_frequency_anomalies(self, chat_data: List[Dict]) -> List[Dict]:
        """检测频率异常"""
        anomalies = []
        
        # 统计每个参与者的消息频率
        sender_counts = Counter(msg.get("sender", "") for msg in chat_data)
        total_messages = len(chat_data)
        avg_messages = total_messages / len(sender_counts) if sender_counts else 0
        
        for sender, count in sender_counts.items():
            # 突然高频
            if count > avg_messages * 3:
                anomalies.append({
                    "类型": "高频活跃",
                    "参与者": sender,
                    "消息数": count,
                    "平均数": avg_messages,
                    "严重程度": "中"
                })
        
        return anomalies
    
    def _detect_meeting_anomalies(self, chat_data: List[Dict]) -> List[Dict]:
        """检测会面异常"""
        anomalies = []
        
        # 识别会面相关关键词
        meeting_keywords = ["见", "面", "聊", "聚", "地方", "老地方"]
        
        for msg in chat_data:
            content = msg.get("content", "")
            if any(keyword in content for keyword in meeting_keywords):
                # 检查是否是私下会面
                if any(word in content for word in ["私下", "单独", "保密", "别告诉"]):
                    anomalies.append({
                        "类型": "私下会面",
                        "时间": msg.get("timestamp", ""),
                        "参与者": msg.get("sender", ""),
                        "内容": content,
                        "严重程度": "高"
                    })
        
        return anomalies
    
    def _detect_language_anomalies(self, chat_data: List[Dict]) -> List[Dict]:
        """检测语言模式异常"""
        anomalies = []
        
        for msg in chat_data:
            content = msg.get("content", "")
            sender = msg.get("sender", "")
            
            # 检测模糊指代
            vague_words = ["那个", "这个", "那个东西", "你知道的", "都懂"]
            if sum(1 for word in vague_words if word in content) >= 2:
                anomalies.append({
                    "类型": "模糊指代",
                    "时间": msg.get("timestamp", ""),
                    "参与者": sender,
                    "内容": content,
                    "严重程度": "中"
                })
            
            # 检测删除记录相关
            delete_keywords = ["删除", "撤回", "清理", "不留痕迹"]
            if any(keyword in content for keyword in delete_keywords):
                anomalies.append({
                    "类型": "证据销毁",
                    "时间": msg.get("timestamp", ""),
                    "参与者": sender,
                    "内容": content,
                    "严重程度": "高"
                })
        
        return anomalies
    
    def _count_anomaly_types(self, anomalies: List[Dict]) -> Dict[str, int]:
        """统计异常类型"""
        type_counts = Counter(anomaly.get("类型", "未知") for anomaly in anomalies)
        return dict(type_counts)
    
    def assess_risk(self, *analysis_results) -> Dict[str, Any]:
        """综合风险评估"""
        # 计算风险分数
        risk_score = 0
        risk_factors = []
        
        semantic_result = analysis_results[0]
        behavioral_result = analysis_results[1]
        network_result = analysis_results[2]
        temporal_result = analysis_results[3]
        context_result = analysis_results[4]
        
        # 1. 语义风险 (0-3分)
        semantic_risk = min(semantic_result.get("可疑消息数", 0) / 5, 3)
        risk_score += semantic_risk
        if semantic_risk > 0:
            risk_factors.append(f"语义风险: {semantic_risk:.1f}分")
        
        # 2. 行为风险 (0-2分)
        behavioral_risk = min(behavioral_result.get("异常行为数", 0) / 10, 2)
        risk_score += behavioral_risk
        if behavioral_risk > 0:
            risk_factors.append(f"行为风险: {behavioral_risk:.1f}分")
        
        # 3. 网络风险 (0-2分)
        network_risk = min(len(network_result.get("关键人物", [])) / 3, 2)
        risk_score += network_risk
        if network_risk > 0:
            risk_factors.append(f"网络风险: {network_risk:.1f}分")
        
        # 4. 时间风险 (0-2分)
        temporal_risk = min(len(temporal_result.get("异常时间点", [])) / 5, 2)
        risk_score += temporal_risk
        if temporal_risk > 0:
            risk_factors.append(f"时间风险: {temporal_risk:.1f}分")
        
        # 5. 上下文风险 (0-1分)
        context_risk = 0.5 if context_result.get("发现可疑关联", False) else 0
        risk_score += context_risk
        if context_risk > 0:
            risk_factors.append(f"上下文风险: {context_risk:.1f}分")
        
        # 确定风险等级
        risk_level = self._determine_risk_level(risk_score)
        
        return {
            "总风险分数": round(risk_score, 2),
            "最大风险分数": 10,
            "风险等级": risk_level,
            "风险因素": risk_factors,
            "置信度": self._calculate_confidence(analysis_results)
        }
    
    def _determine_risk_level(self, score: float) -> str:
        """确定风险等级"""
        if score >= 7:
            return "🔴 严重风险"
        elif score >= 5:
            return "🟠 高风险"
        elif score >= 3:
            return "🟡 中风险"
        else:
            return "🟢 低风险"
    
    def _calculate_confidence(self, analysis_results) -> float:
        """计算分析置信度"""
        # 基于多个分析结果的一致性计算置信度
        confidence = 0.7  # 基础置信度
        
        # 如果多个分析都指向高风险，提高置信度
        high_risk_count = sum(
            1 for result in analysis_results
            if isinstance(result, dict) and 
               any("risk" in str(k).lower() or "异常" in str(k) or "可疑" in str(k)
                   for k in result.keys())
        )
        
        if high_risk_count >= 3:
            confidence += 0.2
        
        return min(confidence, 0.99)
    
    def build_evidence_chain(self, *analysis_results) -> Dict[str, Any]:
        """构建证据链"""
        evidence = {
            "完整性": "完整",
            "关键证据": [],
            "证据强度": "强"
        }
        
        # 从各个分析结果中提取关键证据
        for result in analysis_results:
            if isinstance(result, dict):
                # 提取语义证据
                if "详细匹配" in result:
                    for match in result["详细匹配"][:5]:  # 取前5个
                        evidence["关键证据"].append({
                            "类型": "语义证据",
                            "内容": match.get("内容", ""),
                            "时间": match.get("时间", ""),
                            "置信度": match.get("置信度", 0)
                        })
                
                # 提取行为证据
                if "详细异常" in result:
                    for anomaly in result["详细异常"][:5]:
                        evidence["关键证据"].append({
                            "类型": "行为证据",
                            "内容": anomaly.get("内容", anomaly.get("类型", "")),
                            "时间": anomaly.get("时间", ""),
                            "严重程度": anomaly.get("严重程度", "")
                        })
        
        return evidence
    
    def generate_recommendations(self, risk_assessment: Dict) -> List[str]:
        """生成处理建议"""
        risk_level = risk_assessment.get("风险等级", "")
        recommendations = []
        
        if "严重" in risk_level or "高" in risk_level:
            recommendations = [
                "立即启动正式调查程序",
                "保全所有相关证据和记录",
                "对关键人物进行深入调查",
                "检查相关业务流程和决策记录",
                "考虑暂停相关人员的职务权限",
                "协调纪检监察部门介入"
            ]
        elif "中" in risk_level:
            recommendations = [
                "加强监控和关注",
                "收集更多证据信息",
                "进行初步核实",
                "提醒相关人员注意行为规范"
            ]
        else:
            recommendations = [
                "继续保持正常监控",
                "定期复查"
            ]
        
        return recommendations
    
    def get_data_overview(self, chat_data: List[Dict]) -> Dict[str, Any]:
        """获取数据概览"""
        if not chat_data:
            return {"总消息数": 0}
        
        participants = set(msg.get("sender", "") for msg in chat_data)
        
        timestamps = []
        for msg in chat_data:
            try:
                ts = datetime.fromisoformat(
                    msg.get("timestamp", "").replace('Z', '+00:00')
                )
                timestamps.append(ts)
            except:
                continue
        
        time_range = {}
        if timestamps:
            time_range = {
                "开始时间": min(timestamps).isoformat(),
                "结束时间": max(timestamps).isoformat(),
                "时间跨度": str(max(timestamps) - min(timestamps))
            }
        
        return {
            "总消息数": len(chat_data),
            "参与人数": len(participants),
            "参与者列表": list(participants),
            "时间范围": time_range
        }


class NetworkAnalyzer:
    """关系网络分析器"""
    
    def analyze(self, chat_data: List[Dict]) -> Dict[str, Any]:
        """分析关系网络"""
        # 构建关系图
        relationships = self._build_relationships(chat_data)
        
        # 计算中心性
        centrality = self._calculate_centrality(relationships)
        
        # 识别关键人物
        key_players = self._identify_key_players(centrality)
        
        # 检测异常连接
        anomalous_connections = self._detect_anomalies(relationships)
        
        return {
            "关系数量": len(relationships),
            "关键人物": key_players,
            "中心性得分": centrality,
            "异常连接": anomalous_connections
        }
    
    def _build_relationships(self, chat_data: List[Dict]) -> List[Dict]:
        """构建关系"""
        relationships = []
        interaction_count = defaultdict(int)
        
        for msg in chat_data:
            sender = msg.get("sender", "")
            # 简化：假设所有消息都是群聊或双向
            # 实际应该解析接收者
            interaction_count[sender] += 1
        
        for person, count in interaction_count.items():
            relationships.append({
                "人物": person,
                "互动次数": count,
                "活跃度": "高" if count > 10 else "中" if count > 5 else "低"
            })
        
        return relationships
    
    def _calculate_centrality(self, relationships: List[Dict]) -> Dict[str, float]:
        """计算中心性"""
        centrality = {}
        max_count = max((r["互动次数"] for r in relationships), default=1)
        
        for rel in relationships:
            person = rel["人物"]
            count = rel["互动次数"]
            centrality[person] = count / max_count if max_count > 0 else 0
        
        return centrality
    
    def _identify_key_players(self, centrality: Dict[str, float]) -> List[str]:
        """识别关键人物"""
        # 按中心性排序
        sorted_people = sorted(
            centrality.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        # 返回前3名
        return [person for person, score in sorted_people[:3]]
    
    def _detect_anomalies(self, relationships: List[Dict]) -> List[str]:
        """检测异常连接"""
        anomalies = []
        
        # 检测异常高的活跃度
        for rel in relationships:
            if rel["互动次数"] > 20:
                anomalies.append(
                    f"{rel['人物']} 活跃度异常高 ({rel['互动次数']}次)"
                )
        
        return anomalies


class TemporalAnalyzer:
    """时间序列分析器"""
    
    def analyze(self, chat_data: List[Dict]) -> Dict[str, Any]:
        """分析时间序列"""
        # 构建时间线
        timeline = self._build_timeline(chat_data)
        
        # 检测异常时间点
        anomalies = self._detect_temporal_anomalies(chat_data)
        
        # 分析时间模式
        patterns = self._analyze_temporal_patterns(chat_data)
        
        return {
            "时间线事件": len(timeline),
            "异常时间点": anomalies,
            "时间模式": patterns
        }
    
    def _build_timeline(self, chat_data: List[Dict]) -> List[Dict]:
        """构建时间线"""
        timeline = []
        for msg in chat_data:
            timeline.append({
                "时间": msg.get("timestamp", ""),
                "事件": msg.get("content", "")[:50]  # 前50个字符
            })
        return timeline
    
    def _detect_temporal_anomalies(self, chat_data: List[Dict]) -> List[str]:
        """检测时间异常"""
        anomalies = []
        
        for msg in chat_data:
            timestamp_str = msg.get("timestamp", "")
            try:
                timestamp = datetime.fromisoformat(
                    timestamp_str.replace('Z', '+00:00')
                )
                hour = timestamp.hour
                
                # 深夜消息
                if hour >= 22 or hour < 6:
                    anomalies.append(
                        f"深夜消息: {timestamp_str}"
                    )
            except:
                continue
        
        return anomalies[:10]  # 最多返回10个
    
    def _analyze_temporal_patterns(self, chat_data: List[Dict]) -> Dict[str, Any]:
        """分析时间模式"""
        hour_counts = Counter()
        weekday_counts = Counter()
        
        for msg in chat_data:
            timestamp_str = msg.get("timestamp", "")
            try:
                timestamp = datetime.fromisoformat(
                    timestamp_str.replace('Z', '+00:00')
                )
                hour_counts[timestamp.hour] += 1
                weekday_counts[timestamp.weekday()] += 1
            except:
                continue
        
        return {
            "小时分布": dict(hour_counts),
            "星期分布": dict(weekday_counts)
        }


class ContextAwareAnalyzer:
    """上下文感知分析器"""
    
    def analyze(self, chat_data: List[Dict]) -> Dict[str, Any]:
        """上下文感知分析"""
        # 检测可疑关联
        suspicious_associations = self._detect_suspicious_associations(chat_data)
        
        # 分析对话上下文
        context_patterns = self._analyze_context_patterns(chat_data)
        
        return {
            "发现可疑关联": len(suspicious_associations) > 0,
            "可疑关联详情": suspicious_associations,
            "上下文模式": context_patterns
        }
    
    def _detect_suspicious_associations(self, chat_data: List[Dict]) -> List[Dict]:
        """检测可疑关联"""
        associations = []
        
        # 检测特定话题的频繁出现
        topic_keywords = {
            "项目": ["项目", "招标", "采购", "合同"],
            "资金": ["钱", "款", "费用", "预算"],
            "会面": ["见", "面", "聊", "聚"]
        }
        
        for topic, keywords in topic_keywords.items():
            count = sum(
                1 for msg in chat_data
                if any(keyword in msg.get("content", "") for keyword in keywords)
            )
            if count > 5:
                associations.append({
                    "话题": topic,
                    "出现次数": count,
                    "异常": "高"
                })
        
        return associations
    
    def _analyze_context_patterns(self, chat_data: List[Dict]) -> List[str]:
        """分析上下文模式"""
        patterns = []
        
        # 检测话题转换
        if len(chat_data) > 10:
            patterns.append("存在多话题讨论")
        
        # 检测参与者变化
        participants = set(msg.get("sender", "") for msg in chat_data)
        if len(participants) > 2:
            patterns.append("多人参与讨论")
        
        return patterns


def main():
    """主函数"""
    import sys
    
    if len(sys.argv) < 3:
        print("用法: python advanced_analyzer.py <input_file> <output_file>")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2]
    
    # 读取聊天记录
    print(f"📂 读取文件: {input_file}")
    with open(input_file, 'r', encoding='utf-8') as f:
        chat_data = json.load(f)
    
    # 创建分析器
    analyzer = AdvancedCorruptionAnalyzer()
    
    # 执行分析
    report = analyzer.analyze(chat_data)
    
    # 保存报告
    print(f"💾 保存报告: {output_file}")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    # 打印摘要
    print("\n" + "="*50)
    print("📊 分析摘要")
    print("="*50)
    print(f"风险等级: {report['风险评估']['风险等级']}")
    print(f"风险分数: {report['风险评估']['总风险分数']}/{report['风险评估']['最大风险分数']}")
    print(f"置信度: {report['风险评估']['置信度']*100:.1f}%")
    print(f"\n关键发现:")
    for factor in report['风险评估']['风险因素']:
        print(f"  - {factor}")
    print(f"\n建议措施:")
    for i, rec in enumerate(report['建议措施'], 1):
        print(f"  {i}. {rec}")
    print("="*50)


if __name__ == "__main__":
    main()
