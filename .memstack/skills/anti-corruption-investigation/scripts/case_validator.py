#!/usr/bin/env python3
"""
反腐调查结果验证模块
用于验证检测准确性和生成改进建议
"""

import json
from typing import Dict, List, Any, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime


@dataclass
class ValidationResult:
    """验证结果"""
    detection_accuracy: float  # 检测准确率 0-1
    false_positive_rate: float  # 误报率
    key_findings: List[str]  # 关键发现
    missed_indicators: List[str]  # 遗漏的指标
    recommendations: List[str]  # 改进建议


class PatternValidator:
    """
    模式验证器
    验证腐败模式检测的准确性
    """

    # 通用腐败模式库（用于验证）
    CORRUPTION_PATTERNS = {
        'financial_corruption': {
            'keywords': ['bribe', 'kickback', 'payment', 'transfer', '回扣', '贿赂'],
            'description': '财务腐败'
        },
        'evidence_destruction': {
            'keywords': ['delete', 'destroy', 'shred', '删除', '销毁'],
            'description': '证据销毁'
        },
        'insider_trading': {
            'keywords': ['insider', 'stock', 'option', '内幕', '股票'],
            'description': '内幕交易'
        },
        'pressure_manipulation': {
            'keywords': ['pressure', 'hit the target', '压力', '达标'],
            'description': '施压操纵'
        },
        'enterprise_fraud': {
            'keywords': ['SPE', 'off-balance', 'accounting', '财务', '会计'],
            'description': '企业欺诈'
        }
    }

    @classmethod
    def validate_analysis(
        cls,
        analysis_results: Dict[str, Any]
    ) -> ValidationResult:
        """
        验证分析结果

        Args:
            analysis_results: 分析结果字典

        Returns:
            ValidationResult: 验证结果
        """
        key_findings = []
        missed_indicators = []

        # 获取模式计数
        pattern_counts = analysis_results.get('pattern_counts', {})
        suspicious_messages = analysis_results.get('suspicious_messages', [])

        # 验证各模式检测情况
        for pattern_name, pattern_info in cls.CORRUPTION_PATTERNS.items():
            detected = cls._check_pattern_detection(
                analysis_results,
                pattern_info['keywords']
            )

            if detected:
                key_findings.append(f"{pattern_info['description']}: 已检测")
            else:
                missed_indicators.append(f"未检测到: {pattern_info['description']}")

        # 计算准确率
        total_patterns = len(cls.CORRUPTION_PATTERNS)
        detected_patterns = len(key_findings)
        detection_accuracy = detected_patterns / total_patterns if total_patterns > 0 else 0

        # 估算误报率（基于可疑消息比例）
        total_messages = analysis_results.get('total_messages', 1)
        suspicious_count = len(suspicious_messages)
        suspicious_rate = suspicious_count / total_messages if total_messages > 0 else 0
        false_positive_rate = max(0, suspicious_rate - 0.1)  # 假设10%以下为正常

        # 生成建议
        recommendations = cls._generate_recommendations(
            missed_indicators,
            suspicious_rate
        )

        return ValidationResult(
            detection_accuracy=detection_accuracy,
            false_positive_rate=false_positive_rate,
            key_findings=key_findings,
            missed_indicators=missed_indicators,
            recommendations=recommendations
        )

    @classmethod
    def _check_pattern_detection(
        cls,
        results: Dict,
        keywords: List[str]
    ) -> bool:
        """检查关键词是否被检测到"""
        suspicious = results.get('suspicious_messages', [])
        pattern_counts = results.get('pattern_counts', {})

        # 检查可疑消息中是否包含关键词
        for msg in suspicious:
            content = msg.get('content', '').lower()
            for keyword in keywords:
                if keyword.lower() in content:
                    return True

        # 检查模式计数
        for category, count in pattern_counts.items():
            if count > 0 and any(kw in category.lower() for kw in keywords):
                return True

        return False

    @classmethod
    def _generate_recommendations(
        cls,
        missed: List[str],
        suspicious_rate: float
    ) -> List[str]:
        """生成改进建议"""
        recommendations = []

        if missed:
            recommendations.append(
                f"考虑添加遗漏的检测模式"
            )

        if suspicious_rate > 0.3:
            recommendations.append(
                "可疑率较高，建议调整检测阈值以减少误报"
            )
        elif suspicious_rate < 0.01:
            recommendations.append(
                "可疑率较低，可能存在漏检，建议检查检测逻辑"
            )

        recommendations.extend([
            "增加上下文分析以提高准确性",
            "结合时间序列分析检测异常行为模式",
            "引入机器学习模型减少误报"
        ])

        return recommendations


class ReportValidator:
    """
    调查报告验证器
    验证报告内容的完整性和准确性
    """

    REQUIRED_SECTIONS = [
        'executive_summary',
        'methodology',
        'key_findings',
        'risk_assessment',
        'recommendations'
    ]

    @classmethod
    def validate_report(cls, report: Dict[str, Any]) -> Dict[str, Any]:
        """验证报告结构"""
        issues = []
        warnings = []

        # 检查必需章节
        for section in cls.REQUIRED_SECTIONS:
            if section not in report:
                issues.append(f"缺少必需章节: {section}")

        # 检查数据完整性
        if 'key_findings' in report:
            findings = report['key_findings']
            if not findings.get('suspicious_count'):
                warnings.append("未发现可疑消息，可能需要调整检测阈值")

            if findings.get('suspicious_rate', 0) > 0.5:
                warnings.append("可疑率过高，可能存在大量误报")

        # 检查风险评分合理性
        if 'risk_assessment' in report:
            risk = report['risk_assessment']
            score = risk.get('score', 0)
            if score > 9:
                warnings.append("风险评分接近满分，建议人工复核")
            elif score < 1 and findings.get('suspicious_count', 0) > 0:
                warnings.append("存在可疑消息但风险评分过低，算法可能需要调整")

        return {
            'is_valid': len(issues) == 0,
            'issues': issues,
            'warnings': warnings,
            'completeness_score': (len(cls.REQUIRED_SECTIONS) - len(issues)) / len(cls.REQUIRED_SECTIONS)
        }


def validate_analysis(analysis_results: Dict[str, Any]) -> ValidationResult:
    """
    快速验证分析结果

    Example:
        results = analyzer.analyze('data.jsonl')
        validation = validate_analysis(results)
        print(f"准确率: {validation.detection_accuracy:.1%}")
    """
    return PatternValidator.validate_analysis(analysis_results)


def generate_validation_report(
    validation: ValidationResult,
    output_file: str = None
) -> str:
    """生成验证报告"""
    lines = []
    lines.append("=" * 80)
    lines.append("反腐调查验证报告")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"验证时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    lines.append("检测准确率")
    lines.append("-" * 80)
    lines.append(f"整体准确率: {validation.detection_accuracy:.1%}")
    lines.append(f"误报率: {validation.false_positive_rate:.1%}")
    lines.append("")

    lines.append("关键发现")
    lines.append("-" * 80)
    for finding in validation.key_findings:
        lines.append(f"✓ {finding}")
    if not validation.key_findings:
        lines.append("未检测到关键发现")
    lines.append("")

    lines.append("遗漏的指标")
    lines.append("-" * 80)
    for indicator in validation.missed_indicators:
        lines.append(f"✗ {indicator}")
    if not validation.missed_indicators:
        lines.append("未发现明显遗漏")
    lines.append("")

    lines.append("改进建议")
    lines.append("-" * 80)
    for i, rec in enumerate(validation.recommendations, 1):
        lines.append(f"{i}. {rec}")
    lines.append("")

    report = "\n".join(lines)

    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"验证报告已保存: {output_file}")

    return report


if __name__ == '__main__':
    # 测试验证功能
    print("测试验证功能...")

    # 模拟分析结果
    mock_results = {
        'total_messages': 1000,
        'suspicious_messages': [
            {'content': 'We need to delete these documents before audit'},
            {'content': 'The SPE structure is working well'},
            {'content': 'Make sure we hit the target number'}
        ],
        'pattern_counts': {
            'evidence_destruction': 15,
            'enterprise_fraud': 25,
            'pressure_manipulation': 10
        }
    }

    validation = validate_analysis(mock_results)
    report = generate_validation_report(validation)
    print(report)
