"""
Qwen (通义千问) Embedder

基于 EmbedderClient 接口实现 Qwen Embedding API 支持
使用阿里云百炼官方的 DashScope SDK
"""

import logging
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from http import HTTPStatus

import dashscope  # type: ignore[import-untyped]
from dashscope import TextEmbedding

from src.domain.llm_providers.llm_types import EmbedderClient

logger = logging.getLogger(__name__)

# Qwen Embedding 默认模型
DEFAULT_EMBEDDING_MODEL = "text-embedding-v3"

# 默认批处理大小
DEFAULT_BATCH_SIZE = 10  # text-embedding-v3 的批次大小限制为 10


@dataclass
class QwenEmbedderConfig:
    """Qwen Embedder 配置"""

    embedding_model: str = field(default=DEFAULT_EMBEDDING_MODEL)
    embedding_dim: int = field(default=1024)
    api_key: str | None = None


class QwenEmbedder(EmbedderClient):
    """
    Qwen Embedder 客户端

    使用阿里云百炼官方 DashScope SDK 生成文本向量嵌入。

    Attributes:
        config (QwenEmbedderConfig): Embedder 配置
        batch_size (int): 批处理大小
    """

    def __init__(
        self,
        config: QwenEmbedderConfig | None = None,
        batch_size: int | None = None,
    ):
        """
        使用提供的配置初始化 QwenEmbedder。

        Args:
            config (QwenEmbedderConfig | None): Embedder 配置，包括 API 密钥、模型等
            batch_size (int | None): 可选的批处理大小。
                如果未提供，将使用默认批处理大小
        """
        if config is None:
            config = QwenEmbedderConfig()

        self.config = config

        # 设置 API 密钥
        if config.api_key:
            dashscope.api_key = config.api_key
        elif not os.environ.get("DASHSCOPE_API_KEY"):
            logger.warning(
                "API key not provided and DASHSCOPE_API_KEY environment variable not set"
            )

        self.batch_size = batch_size or DEFAULT_BATCH_SIZE

    async def create(
        self, input_data: str | list[str] | Iterable[int] | Iterable[Iterable[int]]
    ) -> list[float]:
        """
        使用 Qwen 的 embedding 模型为给定的输入数据创建嵌入向量。

        Args:
            input_data: 要创建嵌入的输入数据。可以是字符串、字符串列表、
                       整数的可迭代对象或可迭代对象的可迭代对象。

        Returns:
            表示嵌入向量的浮点数列表。

        Raises:
            ValueError: 如果 API 未返回嵌入向量
        """
        # 确保输入是字符串
        if isinstance(input_data, str):
            text_input = input_data
        elif (
            isinstance(input_data, list) and len(input_data) > 0 and isinstance(input_data[0], str)
        ):
            text_input = input_data[0]  # 取第一个字符串
        else:
            # 如果是其他类型，转换为字符串
            text_input = str(input_data)

        # 调用 DashScope TextEmbedding API
        try:
            resp = TextEmbedding.call(
                model=self.config.embedding_model or DEFAULT_EMBEDDING_MODEL,
                input=text_input,
            )

            if resp.status_code != HTTPStatus.OK:
                raise ValueError(f"DashScope API error: {resp.code} - {resp.message}")

            if not resp.output or not resp.output.get("embeddings"):
                raise ValueError("No embeddings returned from DashScope API in create()")

            embeddings = resp.output["embeddings"]
            if not embeddings or len(embeddings) == 0:
                raise ValueError("Empty embeddings array returned from DashScope API")

            # 获取第一个 embedding 的向量
            embedding_values = embeddings[0].get("embedding")
            if not embedding_values:
                raise ValueError("Empty embedding values returned from DashScope API")

            # 如果配置了 embedding_dim，截断或填充向量
            if self.config.embedding_dim and len(embedding_values) > self.config.embedding_dim:
                return embedding_values[: self.config.embedding_dim]

            return embedding_values

        except Exception as e:
            logger.error(f"Error calling DashScope TextEmbedding API: {e}")
            raise

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        """
        使用 Qwen 的 embedding 模型为一批输入数据创建嵌入向量。

        此方法处理批处理以遵守 DashScope API 对单个请求中可以处理的
        实例数量的限制。

        Args:
            input_data_list: 要创建嵌入的字符串列表。

        Returns:
            嵌入向量列表（每个向量是浮点数列表）。

        Raises:
            ValueError: 如果批处理失败
        """
        if not input_data_list:
            return []

        batch_size = self.batch_size
        all_embeddings = []

        # 分批处理输入
        for i in range(0, len(input_data_list), batch_size):
            batch = input_data_list[i : i + batch_size]

            try:
                # 为此批次生成嵌入
                resp = TextEmbedding.call(
                    model=self.config.embedding_model or DEFAULT_EMBEDDING_MODEL,
                    input=batch,
                )

                if resp.status_code != HTTPStatus.OK:
                    raise ValueError(f"DashScope API error: {resp.code} - {resp.message}")

                if not resp.output or not resp.output.get("embeddings"):
                    raise ValueError("No embeddings returned from DashScope API")

                embeddings = resp.output["embeddings"]

                # 处理此批次的嵌入
                for embedding_obj in embeddings:
                    embedding_values = embedding_obj.get("embedding")

                    if not embedding_values:
                        raise ValueError("Empty embedding values returned")

                    # 如果配置了 embedding_dim，截断向量
                    if (
                        self.config.embedding_dim
                        and len(embedding_values) > self.config.embedding_dim
                    ):
                        embedding_values = embedding_values[: self.config.embedding_dim]

                    all_embeddings.append(embedding_values)

            except Exception as e:
                # 如果批处理失败，回退到逐个处理
                logger.warning(
                    f"Batch embedding failed for batch {i // batch_size + 1}, "
                    f"falling back to individual processing: {e}"
                )

                for item in batch:
                    try:
                        # 逐个处理每个项目
                        resp = TextEmbedding.call(
                            model=self.config.embedding_model or DEFAULT_EMBEDDING_MODEL,
                            input=item,
                        )

                        if resp.status_code != HTTPStatus.OK:
                            raise ValueError(f"DashScope API error: {resp.code} - {resp.message}")

                        if not resp.output or not resp.output.get("embeddings"):
                            raise ValueError("No embeddings returned from DashScope API")

                        embeddings = resp.output["embeddings"]
                        embedding_values = embeddings[0].get("embedding")

                        if not embedding_values:
                            raise ValueError("Empty embedding values returned")

                        # 如果配置了 embedding_dim，截断向量
                        if (
                            self.config.embedding_dim
                            and len(embedding_values) > self.config.embedding_dim
                        ):
                            embedding_values = embedding_values[: self.config.embedding_dim]

                        all_embeddings.append(embedding_values)

                    except Exception as individual_error:
                        logger.error(f"Failed to embed individual item: {individual_error}")
                        raise individual_error

        return all_embeddings
