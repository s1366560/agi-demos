#!/usr/bin/env python3
"""
多语言腐败模式检测模块
支持中文、英文及企业欺诈通用模式
"""

import re
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass
from enum import Enum


class PatternCategory(Enum):
    """腐败模式类别"""
    FINANCIAL_CORRUPTION = "financial_corruption"
    POWER_ABUSE = "power_abuse"
    SECRET_MEETING = "secret_meeting"
    COLLUSION = "collusion"
    EVIDENCE_DESTRUCTION = "evidence_destruction"
    INSIDER_TRADING = "insider_trading"
    ENTERPRISE_FRAUD = "enterprise_fraud"
    PRESSURE_MANIPULATION = "pressure_manipulation"


@dataclass
class PatternMatch:
    """模式匹配结果"""
    category: PatternCategory
    language: str
    pattern: str
    matched_text: str
    confidence: float
    context: str


class MultiLangPatternMatcher:
    """
    多语言腐败模式匹配器
    支持中文、英文及通用企业欺诈模式检测
    """

    # 中文直接模式
    CHINESE_DIRECT_PATTERNS = {
        PatternCategory.FINANCIAL_CORRUPTION: [
            r'转账|汇款|账户|资金|钱款|回扣|贿赂|好处费|手续费',
            r'那笔钱|这笔钱|款项|费用|分成|提成|佣金',
            r'表示一下|心意|意思一下|感谢费'
        ],
        PatternCategory.POWER_ABUSE: [
            r'特殊照顾|通融一下|按老规矩|开绿灯|走后门',
            r'违规操作|暗箱操作|内部协调|打招呼|批条子',
            r'帮忙看看|关照一下|照顾一下|帮忙处理'
        ],
        PatternCategory.SECRET_MEETING: [
            r'老地方|私下见面|秘密会面|单独聊聊|当面说',
            r'不要告诉别人|保密|私事|私下|只有我们',
            r'见面聊|当面谈|出来坐坐|一起吃饭'
        ],
        PatternCategory.COLLUSION: [
            r'统一口径|对好供词|串通|勾结|联手|合作',
            r'删除记录|清理聊天|销毁证据|不留痕迹',
            r'保持一致|这么说|统一说法|口径一致'
        ],
        PatternCategory.EVIDENCE_DESTRUCTION: [
            r'删除|销毁|粉碎|清理|移除|擦除',
            r'不要记录|不要留痕|彻底删除|永久删除'
        ]
    }

    # 英文直接模式
    ENGLISH_DIRECT_PATTERNS = {
        PatternCategory.FINANCIAL_CORRUPTION: [
            r'\$[\d,]+(?:\.\d{2})?',
            r'\b(?:million|billion|thousand)\s+(?:dollars?|USD)\b',
            r'\bkickback|bribe|bribery|payoff|payola\b',
            r'\bcommission|fee|payment|transfer\b',
            r'\bhidden|secret|undisclosed\s+(?:payment|fee|account)\b'
        ],
        PatternCategory.EVIDENCE_DESTRUCTION: [
            r'\bdelete|destroy|shred|remove|erase|clean\s+up\b',
            r'\boff\s+the\s+record|not\s+for\s+publication\b',
            r'\bconfidential|top\s+secret|classified\b',
            r"\bdon'?t\s+tell|keep\s+quiet|between\s+us\b",
            r'\bdocument\s+retention|record\s+keeping\b'
        ],
        PatternCategory.INSIDER_TRADING: [
            r'\bstock\s+option|exercise\s+option|vest(?:ing)?\b',
            r'\bsell\s+stock|dump\s+shares|unload\s+position\b',
            r'\binsider\s+information|material\s+non.?public\b',
            r'\bbefore\s+announcement|prior\s+to\s+public\b',
            r'\btrading\s+window|blackout\s+period\b'
        ],
        PatternCategory.PRESSURE_MANIPULATION: [
            r'\bpressure|push|force|make\s+it\s+happen\b',
            r'\bfix|adjust|massage|tweak\s+the\s+numbers?\b',
            r'\bhit\s+the\s+target|meet\s+the\s+number\b',
            r'\bdo\s+whatever\s+it\s+takes|no\s+excuses\b',
            r'\bclose\s+the\s+gap|bridge\s+the\s+difference\b'
        ]
    }

    # 企业欺诈通用模式
    ENTERPRISE_FRAUD_PATTERNS = {
        PatternCategory.ENTERPRISE_FRAUD: [
            # 特殊目的实体
            r'\bSPE\b|special\s+purpose\s+entity',
            r'\boff[-\s]?balance[-\s]?sheet\b',

            # 会计操纵
            r'\bmark[-\s]?to[-\s]?market\b|\bMTM\b',
            r'\baggressive\s+accounting|creative\s+accounting\b',
            r'\brevenue\s+recognition|earnings\s+management\b',
            r'\bcook\s+the\s+books|financial\s+engineering\b',

            # 财务指标操纵
            r'\bEBITDA\b|\bcash\s+flow\b|\bpro\s+forma\b',
            r'\badjusted\s+earnings|non-GAAP\b',
            r'\bWall\s+Street\s+expectation|analyst\s+forecast\b',

            # 审计相关
            r'\bauditor\b|\baudit\s+committee|independent\s+audit\b'
        ]
    }

    # 语义模式 (隐晦表达)
    SEMANTIC_PATTERNS = {
        'zh': {
            PatternCategory.FINANCIAL_CORRUPTION: [
                '东西准备好了吗', '那个东西', '事情办得怎么样了',
                '表示一下', '心意', '意思一下', '感谢费'
            ],
            PatternCategory.POWER_ABUSE: [
                '帮忙看看', '关照一下', '照顾一下', '帮忙处理',
                '特事特办', '按惯例', '老规矩', '都知道的'
            ],
            PatternCategory.SECRET_MEETING: [
                '见面聊', '当面谈', '出来坐坐', '一起吃饭',
                '老地方见', '私下说', '不方便在这里说'
            ],
            PatternCategory.COLLUSION: [
                '保持一致', '这么说', '统一说法', '口径一致',
                '删除吧', '清理一下', '别留记录', '撤回消息'
            ]
        },
        'en': {
            PatternCategory.FINANCIAL_CORRUPTION: [
                'the package', 'the arrangement', 'our understanding',
                'mutual benefit', 'consideration', 'gratitude'
            ],
            PatternCategory.EVIDENCE_DESTRUCTION: [
                'clean house', 'spring cleaning', 'paperwork reduction',
                'document management', 'file organization'
            ],
            PatternCategory.PRESSURE_MANIPULATION: [
                'find a way', 'make it work', 'creative solution',
                'interpretation', 'flexibility', 'judgment call'
            ]
        }
    }

    def __init__(self):
        self.compiled_patterns = self._compile_patterns()

    def _compile_patterns(self) -> Dict:
        """编译所有正则表达式模式以提高性能"""
        compiled = {
            'zh': {},
            'en': {},
            'enterprise': {}
        }

        # 编译中文模式
        for category, patterns in self.CHINESE_DIRECT_PATTERNS.items():
            compiled['zh'][category] = [re.compile(p, re.IGNORECASE) for p in patterns]

        # 编译英文模式
        for category, patterns in self.ENGLISH_DIRECT_PATTERNS.items():
            compiled['en'][category] = [re.compile(p, re.IGNORECASE) for p in patterns]

        # 编译企业欺诈模式
        for category, patterns in self.ENTERPRISE_FRAUD_PATTERNS.items():
            compiled['enterprise'][category] = [re.compile(p, re.IGNORECASE) for p in patterns]

        return compiled

    def detect_language(self, text: str) -> str:
        """
        检测文本主要语言

        Returns:
            'zh', 'en', or 'mixed'
        """
        # 统计中文字符
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        # 统计英文单词
        english_words = len(re.findall(r'\b[a-zA-Z]+\b', text))

        total_chars = len(text)
        if total_chars == 0:
            return 'en'

        chinese_ratio = chinese_chars / total_chars
        english_ratio = english_words / total_chars

        if chinese_ratio > 0.3:
            return 'zh'
        elif english_ratio > 0.3:
            return 'en'
        else:
            return 'mixed'

    def match_patterns(self, content: str, context: str = '') -> List[PatternMatch]:
        """
        匹配内容中的所有腐败模式

        Args:
            content: 要分析的文本内容
            context: 上下文信息（如时间、发送者等）

        Returns:
            List[PatternMatch]: 匹配结果列表
        """
        matches = []
        lang = self.detect_language(content)

        # 匹配中文模式
        if lang in ('zh', 'mixed'):
            matches.extend(self._match_category_patterns(
                content, 'zh', context
            ))

        # 匹配英文模式
        if lang in ('en', 'mixed'):
            matches.extend(self._match_category_patterns(
                content, 'en', context
            ))

        # 始终匹配企业欺诈模式（适用于所有语言环境）
        matches.extend(self._match_category_patterns(
            content, 'enterprise', context
        ))

        # 匹配语义模式
        matches.extend(self._match_semantic_patterns(content, lang, context))

        return matches

    def _match_category_patterns(
        self,
        content: str,
        lang: str,
        context: str
    ) -> List[PatternMatch]:
        """匹配特定语言类别的模式"""
        matches = []

        if lang not in self.compiled_patterns:
            return matches

        for category, patterns in self.compiled_patterns[lang].items():
            for pattern in patterns:
                for match in pattern.finditer(content):
                    matches.append(PatternMatch(
                        category=category,
                        language=lang,
                        pattern=pattern.pattern,
                        matched_text=match.group(),
                        confidence=self._calculate_confidence(match, category),
                        context=context
                    ))

        return matches

    def _match_semantic_patterns(
        self,
        content: str,
        lang: str,
        context: str
    ) -> List[PatternMatch]:
        """匹配语义模式（隐晦表达）"""
        matches = []
        content_lower = content.lower()

        # 确定要检查的语言
        langs_to_check = ['zh', 'en'] if lang == 'mixed' else [lang]

        for check_lang in langs_to_check:
            if check_lang not in self.SEMANTIC_PATTERNS:
                continue

            for category, patterns in self.SEMANTIC_PATTERNS[check_lang].items():
                for pattern in patterns:
                    if pattern.lower() in content_lower:
                        matches.append(PatternMatch(
                            category=category,
                            language=check_lang,
                            pattern=f"semantic:{pattern}",
                            matched_text=pattern,
                            confidence=0.7,  # 语义模式置信度较低
                            context=context
                        ))

        return matches

    def _calculate_confidence(self, match: re.Match, category: PatternCategory) -> float:
        """计算匹配置信度"""
        base_confidence = 0.8

        # 根据匹配长度调整
        match_len = len(match.group())
        if match_len > 20:
            base_confidence += 0.1
        elif match_len < 5:
            base_confidence -= 0.1

        # 企业欺诈模式置信度更高（更具体）
        if category == PatternCategory.ENTERPRISE_FRAUD:
            base_confidence += 0.1

        return min(base_confidence, 1.0)

    def get_summary(self, matches: List[PatternMatch]) -> Dict[str, Any]:
        """获取匹配结果摘要"""
        if not matches:
            return {
                'total_matches': 0,
                'categories': {},
                'languages': {},
                'risk_score': 0.0
            }

        categories = {}
        languages = {}
        total_confidence = 0

        for match in matches:
            cat_name = match.category.value
            categories[cat_name] = categories.get(cat_name, 0) + 1

            lang = match.language
            languages[lang] = languages.get(lang, 0) + 1

            total_confidence += match.confidence

        avg_confidence = total_confidence / len(matches)

        # 计算风险分数 (0-10)
        risk_score = min(
            len(matches) * 0.5 +  # 匹配数量
            len(categories) * 1.0 +  # 类别多样性
            avg_confidence * 2,  # 置信度
            10.0
        )

        return {
            'total_matches': len(matches),
            'categories': categories,
            'languages': languages,
            'risk_score': round(risk_score, 2),
            'avg_confidence': round(avg_confidence, 2)
        }


class EnterpriseFraudDetector:
    """
    企业欺诈专用检测器
    针对企业腐败通用模式优化
    """

    # 高风险职位（通用）
    HIGH_RISK_ROLES = {
        'ceo': {'role': 'CEO', 'risk_level': 'CRITICAL'},
        r'chief\s+executive': {'role': 'CEO', 'risk_level': 'CRITICAL'},
        'cfo': {'role': 'CFO', 'risk_level': 'CRITICAL'},
        r'chief\s+financial': {'role': 'CFO', 'risk_level': 'CRITICAL'},
        'cao': {'role': 'CAO', 'risk_level': 'HIGH'},
        r'chief\s+accounting': {'role': 'CAO', 'risk_level': 'HIGH'},
        'president': {'role': 'President', 'risk_level': 'HIGH'},
        r'vice\s+president': {'role': 'VP', 'risk_level': 'MEDIUM'},
        'director': {'role': 'Director', 'risk_level': 'MEDIUM'},
        'auditor': {'role': 'Auditor', 'risk_level': 'MEDIUM'},
    }

    def __init__(self):
        self.pattern_matcher = MultiLangPatternMatcher()

    def detect_high_risk_role(self, email: str, title: str = '') -> Tuple[bool, Dict]:
        """检测是否是高风险职位"""
        text = f"{email} {title}".lower()

        for pattern, info in self.HIGH_RISK_ROLES.items():
            if re.search(pattern, text, re.IGNORECASE):
                return True, info

        return False, {}

    def analyze_email(self, email_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        分析单封邮件

        Args:
            email_data: {
                'sender': str,
                'receiver': str,
                'timestamp': str,
                'content': str,
                'subject': str,
                'title': str  # 可选：职位信息
            }

        Returns:
            分析结果字典
        """
        content = email_data.get('content', '')
        subject = email_data.get('subject', '')
        sender = email_data.get('sender', '')
        title = email_data.get('title', '')

        # 合并主题和内容进行分析
        full_text = f"{subject} {content}"

        # 模式匹配
        matches = self.pattern_matcher.match_patterns(
            full_text,
            context=f"From: {sender}"
        )

        # 获取摘要
        summary = self.pattern_matcher.get_summary(matches)

        # 检查高风险职位
        is_high_risk_role, role_info = self.detect_high_risk_role(sender, title)

        # 调整风险分数
        risk_score = summary['risk_score']
        if is_high_risk_role:
            risk_score += 2.0

        summary['risk_score'] = min(risk_score, 10.0)

        return {
            'matches': matches,
            'summary': summary,
            'is_high_risk_role': is_high_risk_role,
            'role_info': role_info,
            'risk_level': self._get_risk_level(summary['risk_score'])
        }

    def _get_risk_level(self, score: float) -> str:
        """获取风险等级"""
        if score >= 7:
            return "🔴 高风险"
        elif score >= 4:
            return "🟠 中风险"
        else:
            return "🟢 低风险"


# 便捷函数
def analyze_text(text: str, context: str = '') -> Dict[str, Any]:
    """快速分析文本"""
    matcher = MultiLangPatternMatcher()
    matches = matcher.match_patterns(text, context)
    return matcher.get_summary(matches)


def analyze_email(email_data: Dict[str, Any]) -> Dict[str, Any]:
    """快速分析邮件"""
    detector = EnterpriseFraudDetector()
    return detector.analyze_email(email_data)


if __name__ == '__main__':
    # 测试示例
    test_cases = [
        {
            'name': '中文腐败',
            'text': '那笔钱已经准备好了，我们老地方见，不要告诉别人'
        },
        {
            'name': '英文销毁证据',
            'text': 'We need to delete all the documents before the audit. Keep it confidential.'
        },
        {
            'name': '企业SPE检测',
            'text': 'The SPE structure needs to be off-balance sheet for accounting purposes.'
        },
        {
            'name': '压力操纵',
            'text': 'We need to hit the target number. Find a creative way to bridge the gap.'
        }
    ]

    matcher = MultiLangPatternMatcher()

    for case in test_cases:
        print(f"\n{'='*60}")
        print(f"测试: {case['name']}")
        print(f"文本: {case['text'][:50]}...")

        matches = matcher.match_patterns(case['text'])
        summary = matcher.get_summary(matches)

        print(f"语言: {matcher.detect_language(case['text'])}")
        print(f"匹配数: {summary['total_matches']}")
        print(f"风险分: {summary['risk_score']}")
        print(f"类别: {summary['categories']}")

        for m in matches[:3]:
            print(f"  - {m.category.value}: {m.matched_text}")
