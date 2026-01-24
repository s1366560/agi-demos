"""
Qwen (通义千问) Reranker Client

基于 CrossEncoderClient 接口实现 Qwen 重排序支持
使用阿里云 DashScope SDK 的 rerank API（qwen3-rerank模型）
"""

import asyncio
import logging
import os
import typing
from http import HTTPStatus

import dashscope
from dashscope import TextReRank

from src.domain.llm_providers.llm_types import (
    CrossEncoderClient,
    LLMConfig,
    RateLimitError,
)

logger = logging.getLogger(__name__)

# Qwen Rerank 模型（使用官方 rerank API）
DEFAULT_RERANK_MODEL = "qwen3-rerank"
TOP_N_DEFAULT = 5


class QwenRerankerClient(CrossEncoderClient):
    """
    Qwen Reranker Client

    使用 DashScope 的 TextReRank API（qwen3-rerank模型）对段落进行相关性重排序。

    相比使用 LLM 直接评分的方式，rerank API 提供了：
    - 更好的性能（单次 API 调用）
    - 更准确的相关性评分
    - 更低的成本
    """

    def __init__(
        self,
        config: LLMConfig | None = None,
        client: typing.Any = None,
    ):
        """
        使用提供的配置和客户端初始化 QwenRerankerClient。

        Args:
            config (LLMConfig | None): LLM 客户端配置，包括 API 密钥、模型等
            client (Any | None): 保留此参数以保持兼容性，但不再使用
        """
        if config is None:
            config = LLMConfig()

        self.config = config

        # 设置 API 密钥
        if config.api_key:
            dashscope.api_key = config.api_key
        else:
            api_key = os.environ.get("DASHSCOPE_API_KEY")
            if not api_key:
                logger.warning(
                    "API key not provided and DASHSCOPE_API_KEY environment variable not set"
                )

        # 设置默认模型
        if not config.model:
            config.model = DEFAULT_RERANK_MODEL

        self.model = config.model or DEFAULT_RERANK_MODEL

    async def rank(
        self, query: str, passages: list[str], top_n: int = None
    ) -> list[tuple[str, float]]:
        """
        基于段落与查询的相关性对段落进行排序。

        使用 DashScope 的 TextReRank API 进行重排序。

        Args:
            query (str): 查询字符串
            passages (list[str]): 要排序的段落列表
            top_n (int | None): 返回前 N 个结果，None 表示返回全部

        Returns:
            list[tuple[str, float]]: 包含段落和分数的元组列表，按相关性降序排序
        """
        if len(passages) <= 1:
            return [(passage, 1.0) for passage in passages]

        if top_n is None:
            top_n = len(passages)

        try:
            # DashScope SDK 是同步的，使用 asyncio.to_thread 包装
            response = await asyncio.to_thread(
                TextReRank.call,
                model=self.model,
                query=query,
                documents=passages,
                top_n=top_n,
            )

            # 检查响应状态
            if response.status_code != HTTPStatus.OK:
                error_msg = f"DashScope Rerank API error: {response.code} - {response.message}"
                logger.error(error_msg)

                # 检查是否是速率限制错误
                if response.code in ("RequestDenied", "QuotaExceeded", "InvalidDataRequest"):
                    if response.code == "QuotaExceeded":
                        raise RateLimitError(error_msg)
                    raise Exception(error_msg)

                # 出错时返回原始顺序（所有分数为 1.0）
                logger.warning(f"Rerank failed, returning original order: {error_msg}")
                return [(passage, 1.0 / (i + 1)) for i, passage in enumerate(passages)]

            # 提取结果
            results = []
            if response.output and response.output.results:
                for idx, result_item in enumerate(response.output.results):
                    passage_index = result_item.index
                    relevance_score = result_item.relevance_score

                    # 确保索引有效
                    if 0 <= passage_index < len(passages):
                        passage = passages[passage_index]
                        # DashScope rerank 返回的分数已经是归一化的 [0, 1] 范围
                        # 但为了保险，我们再次限制
                        normalized_score = max(0.0, min(1.0, float(relevance_score)))
                        results.append((passage, normalized_score))

                # DashScope API 已经返回排序后的结果（按相关性降序）
                # 但我们需要确保所有段落都有结果
                if len(results) < len(passages):
                    logger.warning(
                        f"Rerank returned only {len(results)} of {len(passages)} results. "
                        f"Adding missing passages with low scores."
                    )
                    # 为未返回的段落添加低分
                    returned_indices = set()
                    for passage, _ in results:
                        try:
                            returned_indices.add(passages.index(passage))
                        except ValueError:
                            pass

                    for i, passage in enumerate(passages):
                        if i not in returned_indices:
                            # 给未返回的段落一个递减的低分
                            low_score = 0.01 / (len(results) + 1)
                            results.append((passage, low_score))

                logger.info(f"Reranked {len(passages)} passages, top_n={top_n}")
                return results
            else:
                logger.warning("Empty rerank results, returning original order")
                return [(passage, 1.0 / (i + 1)) for i, passage in enumerate(passages)]

        except RateLimitError:
            raise
        except Exception as e:
            error_message = str(e).lower()
            # 检查是否是速率限制错误
            if (
                "rate limit" in error_message
                or "quota" in error_message
                or "throttling" in error_message
                or "request denied" in error_message
                or "429" in str(e)
            ):
                raise RateLimitError from e

            logger.error(f"Error in Qwen reranker: {e}")
            # 出错时返回原始顺序
            return [(passage, 1.0 / (i + 1)) for i, passage in enumerate(passages)]

    async def score(self, query: str, passage: str) -> float:
        """
        计算单个段落与查询的相关性分数。

        Args:
            query (str): 查询字符串
            passage (str): 要评分的段落

        Returns:
            float: 相关性分数 [0, 1]
        """
        results = await self.rank(query, [passage], top_n=1)
        if results:
            return results[0][1]
        return 0.0
