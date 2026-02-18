"""Query expansion with stop-word filtering for EN and ZH.

Ported from Moltbot's query-expansion.ts.
Extracts keywords from conversational queries and filters noise.
"""

from __future__ import annotations

import re
import unicodedata

STOP_WORDS_EN = frozenset(
    {
        "a",
        "an",
        "the",
        "this",
        "that",
        "these",
        "those",
        "i",
        "me",
        "my",
        "mine",
        "myself",
        "we",
        "us",
        "our",
        "ours",
        "you",
        "your",
        "yours",
        "yourself",
        "he",
        "him",
        "his",
        "she",
        "her",
        "it",
        "its",
        "they",
        "them",
        "their",
        "theirs",
        "what",
        "which",
        "who",
        "whom",
        "whose",
        "where",
        "when",
        "how",
        "why",
        "is",
        "am",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "having",
        "do",
        "does",
        "did",
        "doing",
        "will",
        "would",
        "shall",
        "should",
        "may",
        "might",
        "must",
        "can",
        "could",
        "not",
        "no",
        "nor",
        "don",
        "doesn",
        "didn",
        "won",
        "wouldn",
        "shouldn",
        "and",
        "but",
        "or",
        "so",
        "if",
        "then",
        "else",
        "than",
        "because",
        "since",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "by",
        "from",
        "up",
        "out",
        "about",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "between",
        "under",
        "again",
        "further",
        "once",
        "here",
        "there",
        "all",
        "each",
        "every",
        "both",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "any",
        "only",
        "own",
        "same",
        "very",
        "just",
        "also",
        "now",
        "too",
        "already",
        "always",
        "never",
        "often",
        "still",
        "even",
        "much",
        "many",
        "well",
        "back",
        "tell",
        "show",
        "find",
        "get",
        "give",
        "go",
        "know",
        "let",
        "make",
        "say",
        "see",
        "take",
        "think",
        "want",
        "look",
        "use",
        "try",
        "come",
        "need",
        "like",
        "help",
        "please",
        "thanks",
        "thank",
        "hi",
        "hello",
        "ok",
        "okay",
        "yes",
        "yeah",
        "sure",
        "right",
    }
)

STOP_WORDS_ZH = frozenset(
    {
        "的",
        "了",
        "着",
        "过",
        "是",
        "有",
        "在",
        "和",
        "与",
        "或",
        "不",
        "没",
        "也",
        "都",
        "就",
        "而",
        "但",
        "可",
        "要",
        "会",
        "能",
        "把",
        "被",
        "让",
        "给",
        "向",
        "从",
        "到",
        "对",
        "为",
        "以",
        "用",
        "按",
        "因",
        "如",
        "虽",
        "然",
        "所",
        "此",
        "那",
        "这",
        "我",
        "你",
        "他",
        "她",
        "它",
        "们",
        "自己",
        "什么",
        "怎么",
        "哪",
        "谁",
        "多",
        "少",
        "几",
        "些",
        "每",
        "各",
        "很",
        "太",
        "更",
        "最",
        "非常",
        "真",
        "好",
        "大",
        "小",
        "又",
        "再",
        "还",
        "已",
        "正",
        "刚",
        "才",
        "将",
        "曾",
        "吗",
        "吧",
        "呢",
        "啊",
        "呀",
        "嗯",
        "哦",
        "嘛",
        "一",
        "二",
        "三",
        "个",
        "只",
        "次",
        "种",
        "点",
        "上",
        "下",
        "中",
        "前",
        "后",
        "里",
        "外",
        "间",
        "内",
        "说",
        "看",
        "想",
        "知道",
        "觉得",
        "认为",
        "可以",
        "应该",
        "需要",
        "希望",
        "请",
        "谢谢",
        "你好",
    }
)


def _is_cjk(char: str) -> bool:
    """Check if a character is CJK (Chinese/Japanese/Korean)."""
    try:
        name = unicodedata.name(char, "")
        return "CJK" in name or "HANGUL" in name or "HIRAGANA" in name or "KATAKANA" in name
    except ValueError:
        return False


def _has_cjk(text: str) -> bool:
    """Check if text contains any CJK characters."""
    return any(_is_cjk(c) for c in text)


def _tokenize_mixed(text: str) -> list[str]:
    """Tokenize mixed CJK + Latin text.

    Latin text: split on whitespace/punctuation.
    CJK text: extract unigrams and bigrams.
    """
    tokens: list[str] = []
    # Extract Latin tokens
    latin_tokens = re.findall(r"[a-zA-Z0-9_]+", text)
    tokens.extend(t.lower() for t in latin_tokens)

    # Extract CJK characters
    cjk_chars = [c for c in text if _is_cjk(c)]
    # Unigrams
    tokens.extend(cjk_chars)
    # Bigrams
    for i in range(len(cjk_chars) - 1):
        tokens.append(cjk_chars[i] + cjk_chars[i + 1])

    return tokens


def _is_valid_keyword(token: str) -> bool:
    """Check if a token is a valid keyword."""
    if len(token) < 2:
        return False
    if token.isdigit():
        return False
    if all(not c.isalnum() for c in token):
        return False
    return True


def extract_keywords(query: str) -> list[str]:
    """Extract keywords from a conversational query.

    Filters stop words for both English and Chinese, removes
    short tokens and pure numbers.

    Args:
        query: User's search query.

    Returns:
        List of unique keywords suitable for FTS.
    """
    if not query or not query.strip():
        return []

    tokens = _tokenize_mixed(query)
    seen: set[str] = set()
    keywords: list[str] = []

    for token in tokens:
        if token in STOP_WORDS_EN or token in STOP_WORDS_ZH:
            continue
        if not _is_valid_keyword(token):
            continue
        if token in seen:
            continue
        seen.add(token)
        keywords.append(token)

    return keywords


def expand_query_for_fts(query: str) -> str:
    """Expand a query into an OR-joined keyword string for FTS.

    Args:
        query: User's search query.

    Returns:
        FTS-friendly query string: "original | kw1 | kw2 | ..."
    """
    keywords = extract_keywords(query)
    if not keywords:
        return query.strip()

    parts = [query.strip()] + keywords
    return " | ".join(parts)
