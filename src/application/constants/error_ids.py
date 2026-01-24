"""Error ID constants for tracking and monitoring.

These error IDs are used for:
- Sentry error tracking
- Log aggregation
- Customer support debugging
- Production monitoring

Error IDs should be stable and never change once deployed.
"""

# ============================================================================
# Agent Service Error IDs
# ============================================================================

AGENT_CONVERSATION_CREATE_FAILED = "agent_conversation_create_failed"
AGENT_CONVERSATION_NOT_FOUND = "agent_conversation_not_found"
AGENT_CONVERSATION_UNAUTHORIZED = "agent_conversation_unauthorized"
AGENT_CHAT_STREAM_ERROR = "agent_chat_stream_error"
AGENT_CHAT_CONVERSATION_NOT_FOUND = "agent_chat_conversation_not_found"
AGENT_CHAT_UNAUTHORIZED = "agent_chat_unAUTHORIZED"
AGENT_DELETE_CONVERSATION_FAILED = "agent_delete_conversation_failed"
AGENT_DELETE_UNAUTHORIZED = "agent_delete_unauthorized"
AGENT_GET_MESSAGES_UNAUTHORIZED = "agent_get_messages_unAUTHORIZED"

# ============================================================================
# LLM/Agent Execution Error IDs
# ============================================================================

AGENT_LLM_API_ERROR = "agent_llm_api_error"
AGENT_LLM_TIMEOUT = "agent_llm_timeout"
AGENT_LLM_RATE_LIMIT = "agent_llm_rate_limit"
AGENT_LLM_CONNECTION_ERROR = "agent_llm_connection_error"
AGENT_EXECUTION_FAILED = "agent_execution_failed"
AGENT_EXECUTION_STATE_INCONSISTENT = "agent_execution_state_inconsistent"
AGENT_TOOL_EXECUTION_FAILED = "agent_tool_execution_FAILED"

# ============================================================================
# Tool Error IDs
# ============================================================================

TOOL_MEMORY_SEARCH_FAILED = "tool_memory_search_failed"
TOOL_ENTITY_LOOKUP_FAILED = "tool_entity_lookup_failed"
TOOL_EPISODE_RETRIEVAL_FAILED = "tool_episode_retrieval_failed"
TOOL_GRAPH_QUERY_FAILED = "tool_graph_query_failed"
TOOL_SUMMARY_FAILED = "tool_summary_failed"
TOOL_MEMORY_CREATE_FAILED = "tool_memory_create_failed"
TOOL_SERIALIZATION_ERROR = "tool_serialization_error"

# ============================================================================
# Repository Error IDs
# ============================================================================

REPO_CONVERSATION_SAVE_FAILED = "repo_conversation_save_failed"
REPO_MESSAGE_SAVE_FAILED = "repo_message_save_failed"
REPO_EXECUTION_SAVE_FAILED = "repo_execution_save_failed"
REPO_DATABASE_ERROR = "repo_database_error"
REPO_NOT_FOUND = "repo_not_found"

# ============================================================================
# API Error IDs
# ============================================================================

API_REQUEST_VALIDATION_FAILED = "api_request_validation_failed"
API_CONTAINER_NOT_INITIALIZED = "api_container_not_initialized"
API_SSE_SERIALIZATION_ERROR = "api_sse_serialization_error"
API_INTERNAL_ERROR = "api_internal_error"
