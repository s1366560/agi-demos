# llm/ -- LLM Client & Resilience Layer

## Purpose
Unified LLM client abstraction over LiteLLM, multi-tenant provider resolution, and resilience patterns.

## Key Files
- `litellm/unified_llm_client.py` -- `UnifiedLLMClient` wraps `LiteLLMClient` through domain `LLMClient` interface
- `litellm/litellm_client.py` -- raw LiteLLM SDK calls (completion, embedding)
- `litellm/litellm_embedder.py` -- embedding-specific client
- `litellm/litellm_reranker.py` -- reranking client
- `provider_factory.py` -- `AIServiceFactory` resolves provider config from DB per tenant
- `resilience/circuit_breaker.py` -- CLOSED/OPEN/HALF_OPEN state machine
- `resilience/rate_limiter.py` -- token bucket rate limiting
- `resilience/health_checker.py` -- periodic provider health probes

## Architecture Flow
```
Endpoint -> AIServiceFactory -> ProviderResolutionService (DB lookup)
         -> UnifiedLLMClient(LiteLLMClient) -> LiteLLM SDK -> Provider API
         -> CircuitBreaker wraps calls
```

## AIServiceFactory (provider_factory.py)
- Resolves LLM provider config per tenant from database
- `ProviderResolutionService` handles multi-tenant isolation
- Creates appropriate client (LLM, embedder, reranker) based on provider type
- Supported providers: gemini, dashscope, openai, deepseek, anthropic

## Circuit Breaker Config
| Parameter | Default |
|-----------|---------|
| `failure_threshold` | 5 consecutive failures to OPEN |
| `success_threshold` | 2 successes in HALF_OPEN to CLOSE |
| `recovery_timeout` | 60 seconds before OPEN -> HALF_OPEN |

- State transitions: CLOSED -> OPEN (on failures) -> HALF_OPEN (after timeout) -> CLOSED (on success)
- OPEN state: all calls rejected immediately (fail-fast)
- HALF_OPEN: allows limited probe calls

## Other Modules
| File | Purpose |
|------|---------|
| `cache.py` | LLM response caching |
| `metrics.py` | Token usage, latency tracking |
| `model_registry.py` | Available model catalog |
| `token_estimator.py` | Pre-call token count estimation |
| `validated_embedder.py` | Embedding with dimension validation |
| `validation.py` | Request/response validation |

## Gotchas
- `UnifiedLLMClient` is the domain boundary -- never import `LiteLLMClient` directly in application layer
- Provider config is per-tenant in DB -- env vars (`GEMINI_API_KEY` etc.) are fallback only
- Circuit breaker state is in-memory -- resets on app restart
- Rate limiter is per-process -- not distributed across workers
- Token estimation is approximate -- actual usage may differ from estimate
- LiteLLM silently falls back to env vars if provider config missing -- can cause cross-tenant leakage if env vars set
