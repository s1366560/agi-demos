"""
Qwen (通义千问) LLM Client

基于 LLMClient 接口实现 Qwen API 支持
使用阿里云官方 DashScope SDK
"""

import json
import logging
import os
import typing
from http import HTTPStatus

import dashscope
from dashscope import Generation
from pydantic import BaseModel

from src.domain.llm_providers.llm_types import (
    DEFAULT_MAX_TOKENS,
    LLMClient,
    LLMConfig,
    Message,
    ModelSize,
    RateLimitError,
)

logger = logging.getLogger(__name__)

# Qwen 模型配置
DEFAULT_MODEL = "qwen-plus"  # 支持结构化输出的模型
DEFAULT_SMALL_MODEL = "qwen-turbo"  # 不支持结构化输出的快速模型

# 支持结构化输出的模型列表
STRUCTURED_OUTPUT_MODELS = [
    "qwen-plus",
    "qwen-max",
    "qwen-turbo-latest",
    "qwen2.5",
]

# 不支持结构化输出的模型
NON_STRUCTURED_MODELS = [
    "qwen-turbo",
]


class QwenClient(LLMClient):
    """
    QwenClient 是用于与阿里云通义千问 (Qwen) 模型交互的客户端类。

    使用官方 DashScope SDK，支持结构化输出和非结构化输出模型。

    Attributes:
        model (str): 用于生成响应的模型名称（支持结构化输出）
        small_model (str): 用于小型任务的模型名称（可能不支持结构化输出）
        temperature (float): 生成响应时使用的温度参数
        max_tokens (int): 响应中生成的最大 token 数
    """

    def __init__(
        self,
        config: LLMConfig | None = None,
        cache: bool = False,
        client: typing.Any = None,
    ):
        """
        使用提供的配置、缓存设置和客户端初始化 QwenClient。

        Args:
            config (LLMConfig | None): LLM 客户端的配置，包括 API 密钥、模型、温度和最大 token 数
            cache (bool): 是否对响应使用缓存。默认为 False
            client (Any | None): 保留此参数以保持兼容性，但不再使用
        """
        if config is None:
            config = LLMConfig()

        super().__init__(config, cache)

        # 设置 API 密钥
        if config.api_key:
            dashscope.api_key = config.api_key
        else:
            api_key = os.environ.get("DASHSCOPE_API_KEY")
            if not api_key:
                logger.warning(
                    "API key not provided and DASHSCOPE_API_KEY environment variable not set"
                )

        # 设置默认值
        if not config.model:
            config.model = DEFAULT_MODEL
        if not config.small_model:
            config.small_model = DEFAULT_SMALL_MODEL

        self.model = config.model
        self.small_model = config.small_model

    def _get_model_for_size(self, model_size: ModelSize) -> str:
        """
        根据请求的大小获取适当的模型名称。

        Args:
            model_size: 模型大小（small 或 medium）

        Returns:
            str: 模型名称
        """
        if model_size == ModelSize.small:
            return self.small_model or DEFAULT_SMALL_MODEL
        else:
            return self.model or DEFAULT_MODEL

    def _supports_structured_output(self, model: str) -> bool:
        """
        检查模型是否支持结构化输出（JSON 模式）。

        Args:
            model: 模型名称

        Returns:
            bool: 是否支持结构化输出
        """
        # 检查模型名称是否在支持列表中
        for supported_model in STRUCTURED_OUTPUT_MODELS:
            if model.lower().startswith(supported_model.lower()):
                return True
        return False

    def _is_actual_content(self, text: str, field_name: str) -> bool:
        """
        判断文本是否是实际内容而不是schema元描述。

        Args:
            text: 要检查的文本
            field_name: 字段名称

        Returns:
            bool: True表示是实际内容，False表示是schema元描述
        """
        if not text or not isinstance(text, str):
            return False

        text_lower = text.lower().strip()

        # Schema元描述的特征（这些不是实际内容）
        schema_patterns = [
            "summary containing",
            "name of the",
            "id of the",
            "list of",
            "must be one of",
            "should be",
            "under 250 characters",
            "under 500 characters",
            "under 1000 characters",
            "optional field",
            "required field",
            "type of the",
        ]

        # 检查是否包含schema模式
        for pattern in schema_patterns:
            if pattern in text_lower:
                logger.debug(
                    f"Field '{field_name}': description contains schema pattern '{pattern}', treating as metadata"
                )
                return False

        # 如果描述完全是指导性语言，不是内容
        if text_lower.startswith(("the ", "a ", "an ")) and len(text.split()) < 5:
            return False

        # 如果text看起来像具体内容（有足够的长度和多样性），认为是实际内容
        if len(text) > 20 and not text_lower.endswith((".", "...", "description")):
            return True

        # 默认谨慎起见，如果不是明显的schema描述，可能是内容
        return True

    def _clean_parsed_json(
        self, data: dict[str, typing.Any], response_model: type[BaseModel] | None
    ) -> dict[str, typing.Any]:
        """
        清理解析后的 JSON 数据，处理 null 值和无效数据。

        Args:
            data: 解析后的 JSON 数据
            response_model: Pydantic 响应模型

        Returns:
            清理后的数据
        """
        if not isinstance(data, dict):
            return data

        cleaned_data = {}

        for key, value in data.items():
            if value is None:
                # 对于 null 值，根据字段名提供默认值
                if key.lower() == "id" or key.lower().endswith("_id") or key == "duplicate_idx":
                    # ID 字段默认为 "0" (字符串格式)
                    cleaned_data[key] = "0"
                elif "facts" in key.lower() or "edges" in key.lower() or key == "duplicates":
                    # 列表字段默认为空列表
                    cleaned_data[key] = []
                else:
                    # 其他字段保持 None，让 Pydantic 验证器处理
                    cleaned_data[key] = value
            elif isinstance(value, list):
                # Special handling for duplicates list to ensure strings
                if key == "duplicates":
                    cleaned_list = [
                        str(item) if isinstance(item, (int, float)) else item for item in value
                    ]
                    cleaned_data[key] = cleaned_list
                else:
                    # 递归清理列表中的元素
                    cleaned_list = []
                    for item in value:
                        if isinstance(item, dict):
                            # Use recursive cleaning for dict items
                            cleaned_item = self._clean_parsed_json(item, None)
                            # 只添加有效的项（例如，如果所有 ID 都是 0，跳过该项）
                            if self._is_valid_item(cleaned_item):
                                cleaned_list.append(cleaned_item)
                        else:
                            cleaned_list.append(item)
                    cleaned_data[key] = cleaned_list
            elif isinstance(value, dict):
                # Check if it looks like a schema definition (Qwen artifact)
                # Qwen sometimes returns {"description": "actual text", "type": "string"} for string fields
                if (
                    "description" in value
                    and isinstance(value.get("description"), str)
                    and ("type" in value or "title" in value or len(value) == 1)
                ):
                    # 使用新的方法来判断description是否是实际内容
                    if self._is_actual_content(value["description"], key):
                        cleaned_data[key] = value["description"]
                    else:
                        # 如果是schema元描述，尝试使用default值
                        if "default" in value:
                            cleaned_data[key] = value["default"]
                        else:
                            logger.warning(
                                f"Field '{key}': description appears to be schema metadata, skipping"
                            )
                else:
                    # 递归清理嵌套字典
                    cleaned_data[key] = self._clean_parsed_json(value, None)
            else:
                # Handle timestamp fields that are 0 (Qwen sometimes returns 0 for null timestamps)
                if (
                    isinstance(value, (int, float))
                    and value == 0
                    and ("_at" in key.lower() or "time" in key.lower())
                ):
                    cleaned_data[key] = None
                # Ensure ID fields are strings for compatibility
                elif (
                    key.lower() == "id" or key.lower().endswith("_id") or key == "duplicate_idx"
                ) and isinstance(value, (int, float)):
                    cleaned_data[key] = str(int(value))
                else:
                    cleaned_data[key] = value

        # Map entity_type_id to entity_type if needed
        if "entity_type_id" in cleaned_data and (
            "entity_type" not in cleaned_data or not cleaned_data["entity_type"]
        ):
            type_id = cleaned_data["entity_type_id"]
            # Default entity type mapping
            mapping = [
                "Entity",
                "Person",
                "Organization",
                "Location",
                "Concept",
                "Event",
                "Artifact",
            ]
            if isinstance(type_id, int) and 0 <= type_id < len(mapping):
                cleaned_data["entity_type"] = mapping[type_id]
            else:
                cleaned_data["entity_type"] = "Entity"

        # Heuristic fix for Qwen's duplicate_idx behavior
        # If duplicate_idx points to self (id), but duplicates list has other IDs,
        # pick the first other ID as the duplicate target.
        current_id = cleaned_data.get("id")
        dup_idx = cleaned_data.get("duplicate_idx")
        duplicates = cleaned_data.get("duplicates", [])

        if current_id is not None and dup_idx is not None and duplicates:
            # Ensure types match for comparison (they should be strings now due to cleaning above)
            if str(dup_idx) == str(current_id):
                other_dups = [d for d in duplicates if str(d) != str(current_id)]
                if other_dups:
                    cleaned_data["duplicate_idx"] = str(other_dups[0])
                    logger.info(
                        f"Fixed duplicate_idx from {dup_idx} to {other_dups[0]} based on duplicates list {duplicates}"
                    )

        return cleaned_data

    def _is_valid_item(self, item: dict[str, typing.Any]) -> bool:
        """
        检查一个项是否有效。
        """
        # 如果有名称、内容或事实，无论 ID 如何都认为是有效的
        if item.get("name") or item.get("content") or item.get("fact"):
            return True

        # 如果是去重结果，包含 duplicates 字段，认为是有效的
        if "duplicates" in item or "duplicate_idx" in item:
            return True

        # 如果有非空的 id 字段，也认为是有效的（即使是 0 或 "0"）
        # 只有当 ID 为 None 且没有其他内容时才无效
        for key, value in item.items():
            if key.lower() == "id" or key.lower().endswith("_id"):
                if value is not None:
                    return True

        # 如果没有 ID 字段，认为有效
        return True

    async def _generate_response(
        self,
        messages: list[Message],
        response_model: type[BaseModel] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        model_size: ModelSize = ModelSize.medium,
        retry_count: int = 0,
    ) -> dict[str, typing.Any]:
        """
        从 Qwen 语言模型生成响应。

        使用官方 DashScope SDK，支持结构化和非结构化输出。

        Args:
            messages (list[Message]): 要发送到语言模型的消息列表
            response_model (type[BaseModel] | None): 可选的 Pydantic 模型，用于解析响应
            max_tokens (int): 响应中生成的最大 token 数
            model_size (ModelSize): 要使用的模型大小（small 或 medium）

        Returns:
            dict[str, typing.Any]: 来自语言模型的响应

        Raises:
            RateLimitError: 如果超出 API 速率限制
            Exception: 如果生成响应时出错
        """
        import asyncio

        model = self._get_model_for_size(model_size)
        supports_structured = self._supports_structured_output(model)

        # 准备 DashScope 格式的消息
        dashscope_messages = []

        # 如果需要结构化输出但模型不支持，切换到支持的结构化模型
        if response_model and not supports_structured:
            logger.warning(
                f"Model {model} does not support structured output. "
                f"Switching to {DEFAULT_MODEL} for this request."
            )
            model = DEFAULT_MODEL

        # 添加 JSON 指令（如果需要结构化输出）
        json_instruction = "You must output valid JSON only."

        for m in messages:
            content = self._clean_input(m.content)
            if response_model and m.role == "system":
                content += f" {json_instruction}"
            dashscope_messages.append({"role": m.role, "content": content})

        try:
            # 构建请求参数
            kwargs = {
                "model": model,
                "messages": dashscope_messages,
                "max_tokens": max_tokens,
                "result_format": "message",  # 使用 message 格式获取结构化响应
            }

            # DashScope SDK 的 JSON 模式
            if response_model:
                # 启用 JSON 模式
                kwargs["result_format"] = "message"

            # DashScope SDK 是同步的，使用 asyncio.to_thread 包装
            response = await asyncio.to_thread(Generation.call, **kwargs)

            # 检查响应状态
            if response.status_code != HTTPStatus.OK:
                error_msg = f"DashScope API error: {response.code} - {response.message}"
                logger.error(error_msg)

                # 检查是否是速率限制错误
                if response.code in ("RequestDenied", "QuotaExceeded"):
                    raise RateLimitError(error_msg)
                raise Exception(error_msg)

            # 获取响应内容
            if not response.output or not response.output.choices:
                raise ValueError("No choices in response")

            raw_output = response.output.choices[0].message.content

            if not raw_output:
                raise ValueError("Empty response content")

            logger.info(f"Qwen raw output: {raw_output}")

            # 如果需要结构化输出，解析 JSON
            if response_model:
                try:
                    # 尝试解析 JSON
                    try:
                        parsed_json = json.loads(raw_output)
                    except json.JSONDecodeError:
                        # 尝试清理 markdown
                        clean_output = raw_output.strip()
                        if clean_output.startswith("```json"):
                            clean_output = clean_output[7:]
                        elif clean_output.startswith("```"):
                            clean_output = clean_output[3:]
                        if clean_output.endswith("```"):
                            clean_output = clean_output[:-3]
                        parsed_json = json.loads(clean_output.strip())

                    # Check if returned JSON is a Schema (properties, type, etc.)
                    # and try to extract data from description or default fields
                    if isinstance(parsed_json, dict) and "properties" in parsed_json:
                        logger.warning(
                            "Qwen returned JSON Schema instead of data. Attempting heuristic extraction..."
                        )

                        extracted = {}
                        properties = parsed_json.get("properties", {})
                        for k, v in properties.items():
                            if isinstance(v, dict):
                                desc = v.get("description", "")
                                default = v.get("default")

                                # Try default first (most reliable)
                                if default is not None:
                                    extracted[k] = default
                                # Then try description, but filter out schema metadata
                                elif desc and self._is_actual_content(desc, k):
                                    extracted[k] = desc

                        if extracted:
                            logger.info(f"Heuristically extracted data: {extracted}")
                            # Merge with parsed_json to keep other fields if any
                            # But usually schema only has properties
                            parsed_json = extracted
                        else:
                            logger.warning("Failed to extract valid data from Schema.")
                            # Trigger retry logic below by raising error
                            raise ValueError("LLM returned JSON Schema instead of data")

                    # 清理数据
                    parsed_json = self._clean_parsed_json(parsed_json, response_model)

                    # 验证
                    validated = response_model.model_validate(parsed_json)
                    return validated.model_dump()
                except Exception as e:
                    logger.error(f"Failed to parse/validate JSON: {e}")
                    logger.error(f"Raw output: {raw_output}")

                    # Retry logic
                    if retry_count < 2:
                        logger.info(f"Retrying generation (attempt {retry_count + 1})...")

                        # Add error feedback to messages
                        # We need to construct new messages list carefully
                        # messages is list[Message]
                        new_messages = list(messages)

                        # Add assistant output (what it generated)
                        new_messages.append(Message(role="assistant", content=raw_output))

                        # Add user correction
                        correction = "You returned the JSON Schema definition instead of the actual data. Please output the JSON object containing the actual extracted data."
                        new_messages.append(Message(role="user", content=correction))

                        return await self._generate_response(
                            messages=new_messages,
                            response_model=response_model,
                            max_tokens=max_tokens,
                            model_size=model_size,
                            retry_count=retry_count + 1,
                        )
                    raise

            return {"content": raw_output}

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

            logger.error(f"Error in generating LLM response: {e}")
            raise

    def _get_provider_type(self) -> str:
        """获取提供商类型"""
        return "qwen"
