#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
反腐败调查技能 v4.0 - 关系网络分析器
Anti-Corruption Investigation Skill v4.0 - Relationship Network Analyzer

专门用于分析聊天记录中的人物关系网络，识别腐败团伙和关键人物
"""

import json
import networkx as nx
from collections import defaultdict, Counter
from datetime import datetime
from typing import Dict, List, Tuple, Any
import numpy as np
from community import community_louvain
from scipy import spatial


class RelationshipAnalyzer:
    """关系网络分析器"""
    
    def __init__(self):
        """初始化分析器"""
        self.graph = None
        self.messages = []
        self.participants = set()
        
    def load_messages(self, file_path: str) -> List[Dict]:
        """加载聊天消息
        
        Args:
            file_path: JSONL文件路径
            
        Returns:
            消息列表
        """
        messages = []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        try:
                            msg = json.loads(line)
                            messages.append(msg)
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            print(f"加载文件失败: {e}")
            return []
            
        self.messages = messages
        print(f"✅ 成功加载 {len(messages)} 条消息")
        return messages
    
    def build_network(self, messages: List[Dict]) -> nx.Graph:
        """构建关系网络
        
        Args:
            messages: 消息列表
            
        Returns:
            NetworkX图对象
        """
        G = nx.Graph()
        
        # 统计交互频率和类型
        interactions = defaultdict(lambda: {
            'count': 0,
            'types': Counter(),
            'time_patterns': [],
            'suspicious_count': 0
        })
        
        # 提取所有参与者
        participants = set()
        for msg in messages:
            sender = msg.get('sender', '')
            receiver = msg.get('receiver', '')
            participants.add(sender)
            if receiver:
                participants.add(receiver)
        
        self.participants = participants
        
        # 分析每条消息
        for msg in messages:
            sender = msg.get('sender', '')
            receiver = msg.get('receiver', '')
            content = msg.get('content', '')
            timestamp = msg.get('timestamp', '')
            
            # 如果有明确的接收者，直接建立连接
            if receiver and receiver != sender:
                key = tuple(sorted([sender, receiver]))
                interactions[key]['count'] += 1
                
                # 分析交互类型
                interaction_type = self._classify_interaction(content)
                interactions[key]['types'][interaction_type] += 1
                
                # 记录时间模式
                if timestamp:
                    try:
                        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                        hour = dt.hour
                        interactions[key]['time_patterns'].append(hour)
                    except:
                        pass
                
                # 检测可疑行为
                if self._is_suspicious_interaction(content):
                    interactions[key]['suspicious_count'] += 1
            else:
                # 如果没有明确接收者，尝试从内容中提及的人
                mentioned = self._extract_mentions(content, participants)
                for mentioned_person in mentioned:
                    if mentioned_person != sender:
                        key = tuple(sorted([sender, mentioned_person]))
                        interactions[key]['count'] += 1
                        
                        # 分析交互类型
                        interaction_type = self._classify_interaction(content)
                        interactions[key]['types'][interaction_type] += 1
                        
                        # 记录时间模式
                        if timestamp:
                            try:
                                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                                hour = dt.hour
                                interactions[key]['time_patterns'].append(hour)
                            except:
                                pass
                        
                        # 检测可疑行为
                        if self._is_suspicious_interaction(content):
                            interactions[key]['suspicious_count'] += 1
        
        # 构建图
        for (person1, person2), data in interactions.items():
            if person1 in participants and person2 in participants:
                # 计算权重
                weight = data['count']
                
                # 计算可疑度
                suspicious_ratio = data['suspicious_count'] / max(data['count'], 1)
                
                # 添加边
                G.add_edge(person1, person2, 
                          weight=weight,
                          suspicious_ratio=suspicious_ratio,
                          interaction_types=dict(data['types']),
                          suspicious_count=data['suspicious_count'])
        
        self.graph = G
        print(f"✅ 构建关系网络: {G.number_of_nodes()} 个节点, {G.number_of_edges()} 条边")
        return G
    
    def _extract_mentions(self, content: str, participants: set) -> List[str]:
        """提取消息中提到的人
        
        Args:
            content: 消息内容
            participants: 参与者列表
            
        Returns:
            提到的人名列表
        """
        mentioned = []
        
        # 直接提及
        for person in participants:
            if person in content:
                mentioned.append(person)
        
        return mentioned
    
    def _classify_interaction(self, content: str) -> str:
        """分类交互类型
        
        Args:
            content: 消息内容
            
        Returns:
            交互类型
        """
        content_lower = content.lower()
        
        # 资金相关
        if any(word in content_lower for word in ['钱', '款', '转账', '支付', '费用', '回扣', '佣金']):
            return '资金'
        
        # 权力相关
        if any(word in content_lower for word in ['审批', '通过', '批准', '同意', '照顾', '特殊']):
            return '权力'
        
        # 秘密相关
        if any(word in content_lower for word in ['保密', '秘密', '私下', '别说', '删除']):
            return '秘密'
        
        # 会面相关
        if any(word in content_lower for word in ['见面', '吃饭', '喝茶', '地方', '老地方']):
            return '会面'
        
        return '普通'
    
    def _is_suspicious_interaction(self, content: str) -> bool:
        """判断是否为可疑交互
        
        Args:
            content: 消息内容
            
        Returns:
            是否可疑
        """
        suspicious_keywords = [
            '回扣', '贿赂', '佣金', '好处费',
            '保密', '别说', '删除记录',
            '特殊照顾', '违规', '暗箱操作',
            '老地方', '私下', '秘密'
        ]
        
        content_lower = content.lower()
        return any(keyword in content_lower for keyword in suspicious_keywords)
    
    def calculate_centrality(self) -> Dict[str, Dict[str, float]]:
        """计算中心性指标
        
        Returns:
            中心性指标字典
        """
        if self.graph is None or self.graph.number_of_nodes() == 0:
            return {}
        
        centrality_metrics = {}
        
        # 度中心性
        degree_centrality = nx.degree_centrality(self.graph)
        
        # 接近中心性 (对于不连通图，只计算连通分量)
        try:
            closeness_centrality = nx.closeness_centrality(self.graph)
        except:
            # 如果图不连通，使用harmonic中心性代替
            closeness_centrality = nx.harmonic_centrality(self.graph)
        
        # 中介中心性
        betweenness_centrality = nx.betweenness_centrality(self.graph)
        
        # 特征向量中心性
        try:
            eigenvector_centrality = nx.eigenvector_centrality(self.graph, max_iter=1000)
        except:
            eigenvector_centrality = {node: 0.0 for node in self.graph.nodes()}
        
        # PageRank
        pagerank = nx.pagerank(self.graph)
        
        # 组合结果
        for node in self.graph.nodes():
            centrality_metrics[node] = {
                'degree': degree_centrality.get(node, 0.0),
                'closeness': closeness_centrality.get(node, 0.0),
                'betweenness': betweenness_centrality.get(node, 0.0),
                'eigenvector': eigenvector_centrality.get(node, 0.0),
                'pagerank': pagerank.get(node, 0.0)
            }
        
        return centrality_metrics
    
    def detect_communities(self) -> Dict[str, Any]:
        """检测社区（团伙）
        
        Returns:
            社区检测结果
        """
        if self.graph is None or self.graph.number_of_nodes() == 0:
            return {'communities': [], 'modularity': 0.0}
        
        # 使用Louvain算法检测社区
        partition = community_louvain.best_partition(self.graph)
        
        # 按社区分组
        communities_dict = defaultdict(list)
        for node, community_id in partition.items():
            communities_dict[community_id].append(node)
        
        # 计算每个社区的指标
        communities = []
        for community_id, members in communities_dict.items():
            # 创建子图
            subgraph = self.graph.subgraph(members)
            
            # 计算密度
            density = nx.density(subgraph)
            
            # 计算内部边数
            internal_edges = subgraph.number_of_edges()
            
            # 计算外部边数
            external_edges = 0
            for node in members:
                for neighbor in self.graph.neighbors(node):
                    if neighbor not in members:
                        external_edges += 1
            external_edges = external_edges // 2  # 每条边被计算两次
            
            # 计算风险分数（基于可疑交互比例）
            risk_score = 0.0
            total_suspicious = 0
            total_edges = 0
            for u, v, data in subgraph.edges(data=True):
                total_edges += 1
                total_suspicious += data.get('suspicious_count', 0)
            
            if total_edges > 0:
                risk_score = (total_suspicious / total_edges) * 10
            
            communities.append({
                'id': community_id,
                'members': members,
                'size': len(members),
                'density': round(density, 3),
                'internal_edges': internal_edges,
                'external_edges': external_edges,
                'risk_score': round(min(risk_score, 10.0), 2)
            })
        
        # 计算模块度
        modularity = community_louvain.modularity(partition, self.graph)
        
        # 按风险分数排序
        communities.sort(key=lambda x: x['risk_score'], reverse=True)
        
        return {
            'communities': communities,
            'modularity': round(modularity, 3),
            'num_communities': len(communities)
        }
    
    def identify_key_players(self, centrality: Dict[str, Dict[str, float]], 
                            communities: Dict[str, Any]) -> List[Dict[str, Any]]:
        """识别关键人物
        
        Args:
            centrality: 中心性指标
            communities: 社区检测结果
            
        Returns:
            关键人物列表
        """
        key_players = []
        
        for node in self.graph.nodes():
            metrics = centrality.get(node, {})
            
            # 计算综合得分
            score = (
                metrics.get('pagerank', 0.0) * 3.0 +
                metrics.get('betweenness', 0.0) * 2.0 +
                metrics.get('degree', 0.0) * 1.5 +
                metrics.get('eigenvector', 0.0) * 1.0
            ) * 10
            
            # 确定角色
            role = self._determine_role(metrics, node, communities)
            
            key_players.append({
                'name': node,
                'score': round(score, 2),
                'role': role,
                'metrics': {
                    'pagerank': round(metrics.get('pagerank', 0.0), 3),
                    'betweenness': round(metrics.get('betweenness', 0.0), 3),
                    'degree': round(metrics.get('degree', 0.0), 3),
                    'eigenvector': round(metrics.get('eigenvector', 0.0), 3)
                }
            })
        
        # 按得分排序
        key_players.sort(key=lambda x: x['score'], reverse=True)
        
        return key_players[:10]  # 返回前10名
    
    def _determine_role(self, metrics: Dict[str, float], 
                       node: str, communities: Dict[str, Any]) -> str:
        """确定人物角色
        
        Args:
            metrics: 中心性指标
            node: 节点名称
            communities: 社区检测结果
            
        Returns:
            角色描述
        """
        betweenness = metrics.get('betweenness', 0.0)
        pagerank = metrics.get('pagerank', 0.0)
        degree = metrics.get('degree', 0.0)
        
        # 中间人 - 高中介中心性
        if betweenness > 0.3:
            return '关键中间人'
        
        # 核心人物 - 高PageRank和高度中心性
        if pagerank > 0.15 and degree > 0.4:
            return '核心人物'
        
        # 连接者 - 高度中心性
        if degree > 0.5:
            return '活跃连接者'
        
        # 影响者 - 高特征向量中心性
        if metrics.get('eigenvector', 0.0) > 0.3:
            return '影响力人物'
        
        return '普通参与者'
    
    def analyze_network_metrics(self) -> Dict[str, Any]:
        """分析网络整体指标
        
        Returns:
            网络指标字典
        """
        if self.graph is None or self.graph.number_of_nodes() == 0:
            return {}
        
        # 基本指标
        num_nodes = self.graph.number_of_nodes()
        num_edges = self.graph.number_of_edges()
        density = nx.density(self.graph)
        
        # 连通性
        is_connected = nx.is_connected(self.graph)
        if is_connected:
            avg_path_length = nx.average_shortest_path_length(self.graph)
            diameter = nx.diameter(self.graph)
        else:
            # 对于不连通图，计算最大连通分量
            largest_cc = max(nx.connected_components(self.graph), key=len)
            largest_subgraph = self.graph.subgraph(largest_cc)
            avg_path_length = nx.average_shortest_path_length(largest_subgraph)
            diameter = nx.diameter(largest_subgraph)
        
        # 聚类系数
        avg_clustering = nx.average_clustering(self.graph)
        
        # 度分布
        degrees = [d for n, d in self.graph.degree()]
        avg_degree = np.mean(degrees) if degrees else 0
        
        return {
            'num_nodes': num_nodes,
            'num_edges': num_edges,
            'density': round(density, 3),
            'is_connected': is_connected,
            'avg_path_length': round(avg_path_length, 2),
            'diameter': diameter,
            'avg_clustering': round(avg_clustering, 3),
            'avg_degree': round(avg_degree, 2),
            'max_degree': max(degrees) if degrees else 0,
            'min_degree': min(degrees) if degrees else 0
        }
    
    def find_bridging_ties(self) -> List[Dict[str, Any]]:
        """发现桥梁连接（跨社区的关键连接）
        
        Returns:
            桥梁连接列表
        """
        if self.graph is None:
            return []
        
        # 检测社区
        communities_result = self.detect_communities()
        partition = community_louvain.best_partition(self.graph)
        
        # 找出跨社区的边
        bridging_edges = []
        for u, v, data in self.graph.edges(data=True):
            if partition.get(u) != partition.get(v):
                bridging_edges.append({
                    'person1': u,
                    'person2': v,
                    'community1': partition.get(u),
                    'community2': partition.get(v),
                    'weight': data.get('weight', 0),
                    'suspicious_ratio': data.get('suspicious_ratio', 0.0)
                })
        
        # 按权重排序
        bridging_edges.sort(key=lambda x: x['weight'], reverse=True)
        
        return bridging_edges[:10]  # 返回前10个
    
    def analyze_temporal_patterns(self) -> Dict[str, Any]:
        """分析时间模式
        
        Returns:
            时间模式分析结果
        """
        if not self.messages:
            return {}
        
        # 按小时统计
        hour_counts = defaultdict(int)
        # 按星期统计
        weekday_counts = defaultdict(int)
        # 按是否工作时间统计
        work_hours = 0
        non_work_hours = 0
        
        for msg in self.messages:
            timestamp = msg.get('timestamp', '')
            if not timestamp:
                continue
            
            try:
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                hour = dt.hour
                weekday = dt.weekday()
                
                hour_counts[hour] += 1
                weekday_counts[weekday] += 1
                
                # 判断是否工作时间 (9-18点)
                if 9 <= hour <= 18:
                    work_hours += 1
                else:
                    non_work_hours += 1
            except:
                continue
        
        # 找出最活跃的时间段
        peak_hour = max(hour_counts.items(), key=lambda x: x[1])[0] if hour_counts else 0
        
        return {
            'hour_distribution': dict(hour_counts),
            'weekday_distribution': dict(weekday_counts),
            'peak_hour': peak_hour,
            'work_hours_ratio': round(work_hours / max(work_hours + non_work_hours, 1), 3),
            'non_work_hours_ratio': round(non_work_hours / max(work_hours + non_work_hours, 1), 3)
        }
    
    def generate_summary(self) -> Dict[str, Any]:
        """生成分析摘要
        
        Returns:
            分析摘要
        """
        if self.graph is None or self.graph.number_of_nodes() == 0:
            return {'error': '没有可分析的网络数据'}
        
        # 计算各项指标
        network_metrics = self.analyze_network_metrics()
        centrality = self.calculate_centrality()
        communities = self.detect_communities()
        key_players = self.identify_key_players(centrality, communities)
        bridging_ties = self.find_bridging_ties()
        temporal_patterns = self.analyze_temporal_patterns()
        
        # 评估整体风险
        high_risk_communities = [c for c in communities['communities'] if c['risk_score'] >= 6.0]
        overall_risk = '低'
        if len(high_risk_communities) >= 2:
            overall_risk = '高'
        elif len(high_risk_communities) >= 1:
            overall_risk = '中'
        
        return {
            'overall_risk': overall_risk,
            'network_metrics': network_metrics,
            'centrality': centrality,
            'communities': communities,
            'key_players': key_players,
            'bridging_ties': bridging_ties,
            'temporal_patterns': temporal_patterns,
            'summary': {
                'total_participants': network_metrics.get('num_nodes', 0),
                'total_connections': network_metrics.get('num_edges', 0),
                'num_communities': communities.get('num_communities', 0),
                'high_risk_communities': len(high_risk_communities),
                'network_density': network_metrics.get('density', 0.0),
                'clustering_coefficient': network_metrics.get('avg_clustering', 0.0)
            }
        }
    
    def save_report(self, results: Dict[str, Any], output_path: str):
        """保存分析报告
        
        Args:
            results: 分析结果
            output_path: 输出文件路径
        """
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print(f"✅ 报告已保存: {output_path}")
        except Exception as e:
            print(f"❌ 保存报告失败: {e}")
    
    def visualize_network(self, output_path: str):
        """可视化关系网络（简化版本）
        
        Args:
            output_path: 输出HTML文件路径
        """
        if self.graph is None or self.graph.number_of_nodes() == 0:
            print("❌ 没有可可视化的网络数据")
            return
        
        try:
            import plotly.graph_objects as go
            
            # 获取布局
            pos = nx.spring_layout(self.graph, k=2, iterations=50)
            
            # 准备节点数据
            node_x = []
            node_y = []
            node_text = []
            node_sizes = []
            
            for node in self.graph.nodes():
                x, y = pos[node]
                node_x.append(x)
                node_y.append(y)
                node_text.append(node)
                # 根据度数调整大小
                node_sizes.append(self.graph.degree(node) * 10 + 20)
            
            # 准备边数据
            edge_x = []
            edge_y = []
            
            for edge in self.graph.edges():
                x0, y0 = pos[edge[0]]
                x1, y1 = pos[edge[1]]
                edge_x.extend([x0, x1, None])
                edge_y.extend([y0, y1, None])
            
            # 创建图
            fig = go.Figure()
            
            # 添加边
            fig.add_trace(go.Scatter(
                x=edge_x, y=edge_y,
                line=dict(width=0.5, color='#888'),
                hoverinfo='none',
                mode='lines'
            ))
            
            # 添加节点
            fig.add_trace(go.Scatter(
                x=node_x, y=node_y,
                mode='markers+text',
                hoverinfo='text',
                text=node_text,
                textposition='top center',
                marker=dict(
                    size=node_sizes,
                    color='lightblue',
                    line=dict(width=2, color='DarkBlue')
                )
            ))
            
            fig.update_layout(
                title='反腐败关系网络图',
                showlegend=False,
                hovermode='closest',
                margin=dict(b=20, l=5, r=5, t=40),
                annotations=[
                    dict(
                        text="关系网络可视化",
                        showarrow=False,
                        xref="paper", yref="paper",
                        x=0.005, y=-0.002,
                        xanchor='left', yanchor='bottom',
                        font=dict(size=12)
                    )
                ]
            )
            
            # 保存HTML
            fig.write_html(output_path)
            print(f"✅ 网络可视化已保存: {output_path}")
            
        except ImportError:
            print("❌ 需要安装 plotly: pip install plotly")
        except Exception as e:
            print(f"❌ 可视化失败: {e}")


def main():
    """主函数"""
    import sys
    
    if len(sys.argv) < 3:
        print("用法: python relationship_analyzer.py <input_file> <output_file> [--visualize]")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2]
    visualize = '--visualize' in sys.argv
    
    # 创建分析器
    analyzer = RelationshipAnalyzer()
    
    # 加载数据
    print("📊 加载聊天数据...")
    messages = analyzer.load_messages(input_file)
    
    if not messages:
        print("❌ 没有加载到消息数据")
        sys.exit(1)
    
    # 构建网络
    print("🕸️ 构建关系网络...")
    analyzer.build_network(messages)
    
    # 生成分析报告
    print("📈 生成分析报告...")
    results = analyzer.generate_summary()
    
    # 保存报告
    analyzer.save_report(results, output_file)
    
    # 可视化
    if visualize:
        print("🎨 生成可视化...")
        viz_path = output_file.replace('.json', '_network.html')
        analyzer.visualize_network(viz_path)
    
    # 打印摘要
    print("\n" + "="*50)
    print("📊 分析摘要")
    print("="*50)
    summary = results.get('summary', {})
    print(f"参与人数: {summary.get('total_participants', 0)}")
    print(f"连接数量: {summary.get('total_connections', 0)}")
    print(f"社区数量: {summary.get('num_communities', 0)}")
    print(f"高风险社区: {summary.get('high_risk_communities', 0)}")
    print(f"网络密度: {summary.get('network_density', 0.0):.3f}")
    print(f"聚类系数: {summary.get('clustering_coefficient', 0.0):.3f}")
    print(f"整体风险: {results.get('overall_risk', '未知')}")
    
    # 打印关键人物
    print("\n🎯 关键人物 (Top 5):")
    for i, player in enumerate(results.get('key_players', [])[:5], 1):
        print(f"{i}. {player['name']} - {player['role']} (得分: {player['score']})")
    
    print("\n✅ 分析完成!")


if __name__ == '__main__':
    main()
