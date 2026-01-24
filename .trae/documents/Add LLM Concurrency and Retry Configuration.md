I will add configuration for LLM concurrency control and retry logic to address the `RateLimitError`.

1.  **Add Configuration to `src/configuration/config.py`**:
    *   `LLM_CONCURRENCY_LIMIT`: Limits the number of simultaneous requests to the LLM provider (default: 8).
    *   `LLM_MAX_RETRIES`: Configures the number of retries for failed requests (default: 3).

2.  **Update `src/infrastructure/llm/litellm/litellm_client.py`**:
    *   Implement a global `asyncio.Semaphore` using the configured limit to throttle parallel requests.
    *   Pass `num_retries` to `litellm.acompletion` to handle transient errors automatically.
    *   Wrap LLM calls (`generate` and `generate_stream`) with the semaphore.

This will allow you to control the concurrency level via environment variables (`LLM_CONCURRENCY_LIMIT`) and prevent "concurrency too high" errors from the provider.