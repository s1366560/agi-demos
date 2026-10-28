"""Request-local HTTP clients capture LiteLLM's serialized provider input."""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Protocol, TypedDict, cast

import httpx

from .runtime import RuntimeV2Error

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from .model_request_log import ModelRequestRecorderV2

# These are transport contracts in the installed LiteLLM adapter, not semantic
# routing rules. Each listed adapter accepts a request-local AsyncHTTPHandler.
_HTTP_ADAPTERS = frozenset(
    {
        "anthropic",
        "gemini",
        "vertex_ai",
        "vertex_ai_beta",
        "deepseek",
        "groq",
        "mistral",
        "openrouter",
        "cohere",
        "cohere_chat",
        "minimax",
        "bedrock",
        "ollama",
        "ollama_chat",
        "xai",
        "hosted_vllm",
        "azure_ai",
    }
)
_SDK_ADAPTERS = frozenset(
    {
        "openai",
        "custom_openai",
        "deepinfra",
        "perplexity",
        "nvidia_nim",
        "cerebras",
        "baseten",
        "sambanova",
        "volcengine",
        "anyscale",
        "together_ai",
        "nebius",
        "wandb",
        "clarifai",
    }
)


class _DeferredStreamingResponse(Protocol):
    make_call: Callable[..., Awaitable[object]]


class _AzureEndpointKwargs(TypedDict, total=False):
    azure_endpoint: str


class RequestCaptureV2:
    """Await durable preparation inside the HTTP hook, before transport.send."""

    def __init__(self, recorder: ModelRequestRecorderV2 | None, provider: str, model: str) -> None:
        self.recorder = recorder
        self.provider = provider
        self.model = model
        self.attempts: list[str] = []
        self.http_status: dict[str, int] = {}
        self.responses: list[httpx.Response] = []
        self.client: Any = None

    def bind_response(self, response: object) -> None:
        # LiteLLM's lazy streaming wrapper passes its module-level client to
        # make_call(), overriding the partial's request-local client (Gemini).
        # Rebind this response instance only; never mutate LiteLLM globals.
        make_call = getattr(response, "make_call", None)
        if make_call is not None:

            async def bound_call(*args: object, **kwargs: object) -> object:
                return await make_call(*args, **{**kwargs, "client": self.client})

            cast(_DeferredStreamingResponse, response).make_call = bound_call

    async def before_request(self, request: httpx.Request) -> None:
        if self.recorder is None:
            return
        from .model_request_log import MODEL_REQUEST_PREPARED_EVENT_V2, prepared_model_request_v2

        try:
            body = prepared_model_request_v2(json.loads(await request.aread()))
        except (ValueError, TypeError) as error:
            raise RuntimeV2Error(
                "invalid_prepared_model_request", "Provider request must contain JSON"
            ) from error
        attempt_id = uuid.uuid4().hex
        await self.recorder.append(
            MODEL_REQUEST_PREPARED_EVENT_V2,
            {
                "attempt_id": attempt_id,
                "schema_version": 1,
                "format": "provider.http.json/v1",
                "provider": self.provider,
                "model": self.model,
                "request": body,
            },
        )
        self.attempts.append(attempt_id)
        request.extensions["memstack_model_attempt_id"] = attempt_id

    async def after_response(self, response: httpx.Response) -> None:
        self.responses.append(response)
        attempt_id = response.request.extensions.get("memstack_model_attempt_id")
        if isinstance(attempt_id, str):
            self.http_status[attempt_id] = response.status_code

    async def settle(self, status: str, error_type: str | None) -> None:
        from .model_request_log import MODEL_REQUEST_SETTLED_EVENT_V2

        for response in self.responses:
            await response.aclose()
        if self.recorder is None:
            return
        for attempt_id in self.attempts:
            await self.recorder.append(
                MODEL_REQUEST_SETTLED_EVENT_V2,
                {
                    "attempt_id": attempt_id,
                    "schema_version": 1,
                    "status": "failed" if self.http_status.get(attempt_id, 0) >= 400 else status,
                    "error_type": error_type,
                },
            )


@asynccontextmanager
async def recording_client_v2(
    kwargs: dict[str, Any],
    recorder: ModelRequestRecorderV2 | None,
) -> AsyncIterator[tuple[dict[str, Any], RequestCaptureV2]]:
    """No global clients or callbacks: concurrent tenants cannot share hooks."""
    import litellm
    from litellm.constants import openai_compatible_providers
    from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler
    from openai import AsyncAzureOpenAI, AsyncOpenAI

    if kwargs.get("client") is not None:
        raise RuntimeV2Error("model_request_client_unsupported", "Custom client cannot be recorded")
    model, provider, dynamic_key, api_base = litellm.get_llm_provider(
        model=kwargs["model"],
        custom_llm_provider=kwargs.get("custom_llm_provider"),
        api_base=kwargs.get("api_base"),
        api_key=kwargs.get("api_key"),
    )
    if provider == "azure_ai":
        from litellm.llms.azure_ai.common_utils import AzureFoundryModelInfo

        # The Agents transport does not accept the request-local HTTP client.
        if AzureFoundryModelInfo.get_azure_ai_route(model) == "agents":
            raise RuntimeV2Error(
                "model_request_transport_unsupported",
                "Azure Agents transport has no request recording adapter",
            )
    is_sdk = provider in _SDK_ADAPTERS or provider in openai_compatible_providers
    if provider not in _HTTP_ADAPTERS and not is_sdk and provider != "azure":
        raise RuntimeV2Error(
            "model_request_transport_unsupported",
            "Provider transport has no request recording adapter",
        )
    capture = RequestCaptureV2(recorder, provider, model)
    handler = AsyncHTTPHandler(
        timeout=kwargs.get("timeout"),
        ssl_verify=kwargs.get("ssl_verify"),
        event_hooks={"request": [capture.before_request], "response": [capture.after_response]},
    )
    try:
        client: Any = handler
        if provider == "azure":
            endpoint_kwargs: _AzureEndpointKwargs = (
                {"azure_endpoint": api_base} if api_base is not None else {}
            )
            client = AsyncAzureOpenAI(
                api_key=dynamic_key or kwargs.get("api_key"),
                api_version=kwargs.get("api_version"),
                azure_ad_token=kwargs.get("azure_ad_token"),
                http_client=handler.client,
                max_retries=0,
                **endpoint_kwargs,
            )
        elif provider not in _HTTP_ADAPTERS:
            client = AsyncOpenAI(
                api_key=dynamic_key or kwargs.get("api_key") or litellm.api_key,
                base_url=api_base or litellm.api_base,
                organization=kwargs.get("organization") or litellm.organization,
                http_client=handler.client,
                max_retries=0,
            )
        capture.client = client
        yield {**kwargs, "num_retries": 0, "client": client}, capture
    finally:
        await handler.client.aclose()
