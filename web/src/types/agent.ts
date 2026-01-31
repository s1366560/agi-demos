/**
 * Agent types for React-mode Agent functionality.
 *
 * This module contains TypeScript types for the ReAct agent,
 * conversations, messages, and agent execution tracking.
 *
 * Multi-Level Thinking Support:
 * - Work-level planning for complex queries
 * - Task-level execution with detailed thinking
 * - SSE events for work_plan, step_start, step_end
 */

/**
 * HITL request type
 */
export type HITLRequestType = "clarification" | "decision" | "env_var";

/**
 * HITL request status
 */
export type HITLRequestStatus = "pending" | "answered" | "timeout" | "cancelled";

/**
 * Pending HITL request from backend
 */
export interface PendingHITLRequest {
    id: string;
    request_type: HITLRequestType;
    conversation_id: string;
    message_id?: string;
    question: string;
    options?: Array<Record<string, unknown>>;
    context?: Record<string, unknown>;
    metadata?: Record<string, unknown>;
    status: HITLRequestStatus;
    created_at: string;
    expires_at: string;
}

/**
 * Response for pending HITL requests query
 */
export interface PendingHITLResponse {
    requests: PendingHITLRequest[];
    total: number;
}

/**
 * Conversation status
 */
export type ConversationStatus = "active" | "archived" | "deleted";

/**
 * Message role
 */
export type MessageRole = "user" | "assistant" | "system";

/**
 * Message type (extended for multi-level thinking)
 */
export type MessageType =
    | "text"
    | "thought"
    | "tool_call"
    | "tool_result"
    | "error"
    | "work_plan"
    | "step_start"
    | "step_end";

/**
 * Agent execution status (extended for multi-level thinking)
 */
export type ExecutionStatus =
    | "thinking"
    | "acting"
    | "observing"
    | "completed"
    | "failed"
    | "work_planning"
    | "planning"
    | "step_executing";

/**
 * Thought level for multi-level thinking
 */
export type ThoughtLevel = "work" | "task";

/**
 * Plan status
 */
export type PlanStatus = "planning" | "in_progress" | "completed" | "failed";

/**
 * Plan step in a work plan
 */
export interface PlanStep {
    step_number: number;
    description: string;
    thought_prompt: string;
    required_tools: string[];
    expected_output: string;
    dependencies: number[];
}

/**
 * Work plan for multi-level thinking
 */
export interface WorkPlan {
    id: string;
    conversation_id: string;
    status: PlanStatus;
    steps: PlanStep[];
    current_step_index: number;
    workflow_pattern_id?: string;
    created_at: string;
    updated_at?: string;
}

/**
 * Tool call information
 */
export interface ToolCall {
    name: string;
    arguments: Record<string, unknown>;
    result?: string;
}

/**
 * Tool result information
 */
export interface ToolResult {
    tool_name: string;
    result?: string;
    error?: string;
}

/**
 * Artifact reference (externalized payload)
 */
export interface ArtifactReference {
    object_key?: string;
    url: string;
    mime_type?: string;
    size_bytes?: number;
    source?: string;
}

/**
 * Message in a conversation
 */
export interface Message {
    id: string;
    conversation_id: string;
    role: MessageRole;
    content: string;
    message_type: MessageType;
    tool_calls?: ToolCall[];
    tool_results?: ToolResult[];
    artifacts?: ArtifactReference[];
    metadata?: Record<string, unknown>;
    created_at: string;
    traceUrl?: string; // Langfuse trace URL for observability
}

/**
 * Conversation entity
 */
export interface Conversation {
    id: string;
    project_id: string;
    tenant_id: string;
    user_id: string;
    title: string;
    status: ConversationStatus;
    agent_config?: Record<string, unknown>;
    metadata?: Record<string, unknown>;
    message_count: number;
    created_at: string;
    updated_at?: string;
}

/**
 * Agent execution tracking
 */
export interface AgentExecution {
    id: string;
    conversation_id: string;
    message_id: string;
    status: ExecutionStatus;
    thought?: string;
    action?: string;
    observation?: string;
    tool_name?: string;
    tool_input?: Record<string, unknown>;
    tool_output?: string;
    metadata?: Record<string, unknown>;
    started_at: string;
    completed_at?: string;
}

/**
 * SSE event types from agent (extended for multi-level thinking and typewriter effect)
 */
export type AgentEventType =
    | "message" // User/assistant message
    | "thought" // Agent's reasoning (work or task level)
    | "thought_delta" // Incremental thought update
    | "work_plan" // Work-level plan generated
    | "pattern_match" // Pattern matched from workflow memory (T079)
    | "step_start" // Step execution started
    | "step_end" // Step execution completed
    | "step_finish" // Step finished (alias)
    | "act" // Tool execution (tool name and input)
    | "observe" // Tool results
    | "tool_start" // Tool execution started
    | "tool_result" // Tool execution result
    | "text_start" // Text streaming started (typewriter effect)
    | "text_delta" // Text chunk (typewriter effect)
    | "text_end" // Text streaming ended (typewriter effect)
    | "clarification_asked" // Agent asks for clarification
    | "clarification_answered" // User responds to clarification
    | "decision_asked" // Agent asks for decision
    | "decision_answered" // User makes decision
    | "doom_loop_detected" // Doom loop detected
    | "doom_loop_intervened" // Doom loop intervention
    // Environment variable events
    | "env_var_requested" // Agent requests environment variable from user
    | "env_var_provided" // User provides environment variable
    // Skill execution events (L2 layer)
    | "skill_matched" // Skill matched for execution
    | "skill_execution_start" // Skill execution started
    | "skill_tool_start" // Skill tool execution started
    | "skill_tool_result" // Skill tool execution result
    | "skill_execution_complete" // Skill execution completed
    | "skill_fallback" // Skill execution fallback to LLM
    // Context management events
    | "context_compressed" // Context window compression occurred
    // Plan mode events
    | "plan_mode_enter" // Entered plan mode
    | "plan_mode_exit" // Exited plan mode
    | "plan_created" // Plan created
    | "plan_updated" // Plan updated
    | "plan_status_changed" // Plan status changed
    | "plan_execution_start" // Plan execution started
    | "plan_step_complete" // Plan step completed
    | "plan_execution_complete" // Plan execution completed
    | "reflection_complete" // Reflection completed
    | "adjustment_applied" // Adjustment applied
    // Permission events
    | "permission_asked" // Permission asked
    | "permission_replied" // Permission replied
    // Sandbox events (desktop and terminal)
    | "sandbox_created" // Sandbox container created
    | "sandbox_terminated" // Sandbox container terminated
    | "sandbox_status" // Sandbox status update
    | "desktop_started" // Remote desktop started
    | "desktop_stopped" // Remote desktop stopped
    | "desktop_status" // Remote desktop status update
    | "terminal_started" // Web terminal started
    | "terminal_stopped" // Web terminal stopped
    | "terminal_status" // Web terminal status update
    | "screenshot_update" // Desktop screenshot update
    // System events
    | "start" // Stream started
    | "status" // Status update
    | "cost_update" // Cost tracking update
    | "retry" // Retry attempt
    | "compact_needed" // Context compaction needed
    | "complete" // Final assistant response
    | "title_generated" // Conversation title generated
    | "error"; // Error messages

/**
 * Base SSE event from agent
 */
export interface AgentEvent<T = Record<string, unknown>> {
    type: AgentEventType;
    data: T;
}

/**
 * Message event data
 */
export interface MessageEventData {
    id?: string;
    role: MessageRole;
    content: string;
    created_at?: string;
    artifacts?: ArtifactReference[];
}

/**
 * Thought event data (extended with thought level)
 */
export interface ThoughtEventData {
    thought: string;
    thought_level?: ThoughtLevel;
    step_number?: number;
}

/**
 * Work plan event data
 */
export interface WorkPlanEventData {
    plan_id: string;
    conversation_id: string;
    steps: Array<{
        step_number: number;
        description: string;
        expected_output: string;
    }>;
    total_steps: number;
    current_step: number;
    status: PlanStatus;
    workflow_pattern_id?: string;
    thought_level: ThoughtLevel;
}

/**
 * Step start event data
 */
export interface StepStartEventData {
    plan_id: string;
    step_number: number;
    description: string;
    required_tools: string[];
    current_step: number;
    total_steps: number;
}

/**
 * Step end event data
 */
export interface StepEndEventData {
    plan_id: string;
    step_number: number;
    description: string;
    success: boolean;
    is_plan_complete: boolean;
    current_step: number;
    total_steps: number;
}

/**
 * Act event data (tool execution)
 */
export interface ActEventData {
    tool_name: string;
    tool_input: Record<string, unknown>;
    step_number?: number;
    execution_id?: string;  // New: unique ID for act/observe matching
}

/**
 * Observe event data (tool result)
 */
export interface ObserveEventData {
    observation: string;
    tool_name?: string;       // New: tool name
    execution_id?: string;  // New: matches act event's execution_id
}

/**
 * Complete event data (final response)
 */
export interface CompleteEventData {
    content: string;
    trace_url?: string;
    id?: string;
    message_id?: string;
    assistant_message_id?: string;
    artifacts?: ArtifactReference[];
}

/**
 * Error event data
 */
export interface ErrorEventData {
    message: string;
    isReconnectable?: boolean;
    code?: string;
}

/**
 * Title generated event data
 */
export interface TitleGeneratedEventData {
    conversation_id: string;
    title: string;
    generated_at: string;
    message_id?: string;
    generated_by?: string;
}

/**
 * Clarification type
 */
export type ClarificationType =
    | "scope"
    | "approach"
    | "prerequisite"
    | "priority"
    | "custom";

/**
 * Clarification option
 */
export interface ClarificationOption {
    id: string;
    label: string;
    description?: string;
    recommended?: boolean;
}

/**
 * Clarification asked event data
 */
export interface ClarificationAskedEventData {
    request_id: string;
    question: string;
    clarification_type: ClarificationType;
    options: ClarificationOption[];
    allow_custom: boolean;
    context: Record<string, unknown>;
}

/**
 * Clarification answered event data
 */
export interface ClarificationAnsweredEventData {
    request_id: string;
    answer: string;
}

/**
 * Decision type
 */
export type DecisionType =
    | "branch"
    | "method"
    | "confirmation"
    | "risk"
    | "custom";

/**
 * Decision option
 */
export interface DecisionOption {
    id: string;
    label: string;
    description?: string;
    recommended?: boolean;
    estimated_time?: string;
    estimated_cost?: string;
    risks?: string[];
}

/**
 * Decision asked event data
 */
export interface DecisionAskedEventData {
    request_id: string;
    question: string;
    decision_type: DecisionType;
    options: DecisionOption[];
    allow_custom: boolean;
    context: Record<string, unknown>;
    default_option?: string;
}

/**
 * Decision answered event data
 */
export interface DecisionAnsweredEventData {
    request_id: string;
    decision: string;
}

/**
 * Environment variable input type
 */
export type EnvVarInputType = "text" | "password" | "textarea";

/**
 * Environment variable field definition
 */
export interface EnvVarField {
    name: string;
    label: string;
    description?: string;
    required: boolean;
    input_type: EnvVarInputType;
    default_value?: string;
    placeholder?: string;
}

/**
 * Environment variable requested event data
 */
export interface EnvVarRequestedEventData {
    request_id: string;
    tool_name: string;
    fields: EnvVarField[];
    message?: string;
    context?: Record<string, unknown>;
}

/**
 * Environment variable provided event data
 */
export interface EnvVarProvidedEventData {
    request_id: string;
    tool_name: string;
    variable_names: string[];
}

/**
 * Doom loop detected event data
 */
export interface DoomLoopDetectedEventData {
    request_id: string;
    tool_name: string;
    call_count: number;
    last_calls: Array<{
        tool: string;
        input: Record<string, unknown>;
        timestamp: string;
    }>;
    context?: Record<string, unknown>;
}

/**
 * Doom loop intervened event data
 */
export interface DoomLoopIntervenedEventData {
    request_id: string;
    action: string;
}

/**
 * Thought delta event data (streaming thought)
 */
export interface ThoughtDeltaEventData {
    delta: string;
    thought_level?: ThoughtLevel;
    step_number?: number;
}

/**
 * Text delta event data (typewriter effect)
 */
export interface TextDeltaEventData {
    delta: string;
}

/**
 * Text end event data (typewriter effect)
 */
export interface TextEndEventData {
    full_text?: string;
}

/**
 * Create conversation request
 */
export interface CreateConversationRequest {
    project_id: string;
    title?: string;
    agent_config?: Record<string, unknown>;
}

/**
 * Create conversation response
 */
export type CreateConversationResponse = Conversation;

/**
 * Chat request
 */
export interface ChatRequest {
    conversation_id: string;
    message: string;
    project_id?: string;
}

/**
 * Tool information
 */
export interface ToolInfo {
    name: string;
    description: string;
}

/**
 * Tools list response
 */
export interface ToolsListResponse {
    tools: ToolInfo[];
}

/**
 * Conversation messages response (unified timeline format)
 */
export interface ConversationMessagesResponse {
    conversationId: string;
    timeline: TimelineEvent[];
    total: number;
    // Pagination metadata
    has_more: boolean;
    first_sequence: number | null;
    last_sequence: number | null;
}

/**
 * Agent execution with multi-level thinking details
 */
export interface AgentExecutionWithDetails {
    id: string;
    message_id: string;
    status: ExecutionStatus;
    started_at: string;
    completed_at?: string;
    thought?: string;
    action?: string;
    tool_name?: string;
    tool_input?: Record<string, unknown>;
    tool_output?: string;
    observation?: string;
    // Multi-level thinking fields
    work_level_thought?: string;
    task_level_thought?: string;
    plan_steps?: PlanStep[];
    current_step_index?: number;
    workflow_pattern_id?: string;
    work_plan_id?: string;
    current_step?: number;
    metadata?: Record<string, unknown>;
}

/**
 * Execution history response
 */
export interface ExecutionHistoryResponse {
    conversation_id: string;
    executions: AgentExecutionWithDetails[];
    total: number;
}

/**
 * Execution statistics response
 */
export interface ExecutionStatsResponse {
    total_executions: number;
    completed_count: number;
    failed_count: number;
    average_duration_ms: number;
    tool_usage: Record<string, number>;
    status_distribution: Record<string, number>;
    timeline_data: Array<{
        time: string;
        count: number;
        completed: number;
        failed: number;
    }>;
}

/**
 * Tool execution record from database
 */
export interface ToolExecutionRecord {
    id: string;
    conversation_id: string;
    message_id: string;
    call_id: string;
    tool_name: string;
    tool_input: Record<string, unknown>;
    tool_output?: string | null;
    status: "running" | "success" | "failed";
    error?: string | null;
    step_number?: number | null;
    sequence_number: number;
    started_at: string;
    completed_at?: string | null;
    duration_ms?: number | null;
}

/**
 * Tool executions response from API
 */
export interface ToolExecutionsResponse {
    conversation_id: string;
    tool_executions: ToolExecutionRecord[];
    total: number;
}

/**
 * Agent SSE stream handler (extended for multi-level thinking and typewriter effect)
 */
export interface AgentStreamHandler {
    onMessage?: (event: AgentEvent<MessageEventData>) => void;
    onThought?: (event: AgentEvent<ThoughtEventData>) => void;
    onThoughtDelta?: (event: AgentEvent<ThoughtDeltaEventData>) => void; // Streaming thought
    onWorkPlan?: (event: AgentEvent<WorkPlanEventData>) => void;
    onPatternMatch?: (event: AgentEvent<PatternMatchEventData>) => void; // T079
    onStepStart?: (event: AgentEvent<StepStartEventData>) => void;
    onStepEnd?: (event: AgentEvent<StepEndEventData>) => void;
    onAct?: (event: AgentEvent<ActEventData>) => void;
    onObserve?: (event: AgentEvent<ObserveEventData>) => void;
    onTextStart?: () => void; // Typewriter effect
    onTextDelta?: (event: AgentEvent<TextDeltaEventData>) => void; // Typewriter effect
    onTextEnd?: (event: AgentEvent<TextEndEventData>) => void; // Typewriter effect
    onClarificationAsked?: (
        event: AgentEvent<ClarificationAskedEventData>
    ) => void;
    onClarificationAnswered?: (
        event: AgentEvent<ClarificationAnsweredEventData>
    ) => void;
    onDecisionAsked?: (event: AgentEvent<DecisionAskedEventData>) => void;
    onDecisionAnswered?: (event: AgentEvent<DecisionAnsweredEventData>) => void;
    onDoomLoopDetected?: (event: AgentEvent<DoomLoopDetectedEventData>) => void;
    onDoomLoopIntervened?: (
        event: AgentEvent<DoomLoopIntervenedEventData>
    ) => void;
    // Environment variable handlers
    onEnvVarRequested?: (event: AgentEvent<EnvVarRequestedEventData>) => void;
    onEnvVarProvided?: (event: AgentEvent<EnvVarProvidedEventData>) => void;
    // Skill execution handlers (L2 layer)
    onSkillMatched?: (event: AgentEvent<SkillMatchedEventData>) => void;
    onSkillExecutionStart?: (
        event: AgentEvent<SkillExecutionStartEventData>
    ) => void;
    onSkillToolStart?: (event: AgentEvent<SkillToolStartEventData>) => void;
    onSkillToolResult?: (event: AgentEvent<SkillToolResultEventData>) => void;
    onSkillExecutionComplete?: (
        event: AgentEvent<SkillExecutionCompleteEventData>
    ) => void;
    onSkillFallback?: (event: AgentEvent<SkillFallbackEventData>) => void;
    // Context management handlers
    onContextCompressed?: (event: AgentEvent<ContextCompressedEventData>) => void;
    // Title generation handlers
    onTitleGenerated?: (event: AgentEvent<TitleGeneratedEventData>) => void;
    // Plan Mode handlers
    onPlanModeEnter?: (event: AgentEvent<PlanModeEnterEventData>) => void;
    onPlanModeExit?: (event: AgentEvent<PlanModeExitEventData>) => void;
    onPlanCreated?: (event: AgentEvent<PlanCreatedEventData>) => void;
    onPlanUpdated?: (event: AgentEvent<PlanUpdatedEventData>) => void;
    // Plan Mode execution handlers
    onPlanExecutionStart?: (event: AgentEvent<PlanExecutionStartEvent>) => void;
    onPlanExecutionComplete?: (event: AgentEvent<PlanExecutionCompleteEvent>) => void;
    onReflectionComplete?: (event: AgentEvent<ReflectionCompleteEvent>) => void;
    onComplete?: (event: AgentEvent<CompleteEventData>) => void;
    onError?: (event: AgentEvent<ErrorEventData>) => void;
    onClose?: () => void;
}

/**
 * Agent service interface (extended for multi-level thinking)
 */
export interface AgentService {
    createConversation(
        request: CreateConversationRequest
    ): Promise<CreateConversationResponse>;
    listConversations(
        projectId: string,
        status?: ConversationStatus,
        limit?: number
    ): Promise<Conversation[]>;
    getConversation(
        conversationId: string,
        projectId: string
    ): Promise<Conversation | null>;
    chat(request: ChatRequest, handler: AgentStreamHandler): Promise<void>;
    stopChat(conversationId: string): void;
    deleteConversation(conversationId: string, projectId: string): Promise<void>;
    getConversationMessages(
        conversationId: string,
        projectId: string,
        limit?: number
    ): Promise<ConversationMessagesResponse>;
    getExecutionHistory(
        conversationId: string,
        projectId: string,
        limit?: number,
        statusFilter?: string,
        toolFilter?: string
    ): Promise<ExecutionHistoryResponse>;
    getExecutionStats(
        conversationId: string,
        projectId: string
    ): Promise<ExecutionStatsResponse>;
    getToolExecutions(
        conversationId: string,
        projectId: string,
        messageId?: string,
        limit?: number
    ): Promise<ToolExecutionsResponse>;
    listTools(): Promise<ToolsListResponse>;
}

// ============================================
// Workflow Pattern Types (T074, T085)
// ============================================

/**
 * Pattern step in a workflow pattern
 */
export interface PatternStep {
    step_number: number;
    description: string;
    tool_name: string;
    expected_output_format: string;
    similarity_threshold: number;
    tool_parameters?: Record<string, unknown>;
}

/**
 * Workflow pattern for learned workflows (FR-019, FR-020)
 *
 * Patterns are tenant-scoped - shared across all projects within
 * a tenant but isolated between tenants.
 */
export interface WorkflowPattern {
    id: string;
    tenant_id: string;
    name: string;
    description: string;
    steps: PatternStep[];
    success_rate: number;
    usage_count: number;
    created_at: string;
    updated_at: string;
    metadata?: Record<string, unknown>;
}

/**
 * Pattern match SSE event data (T079)
 */
export interface PatternMatchEventData {
    pattern_id: string;
    similarity_score: number;
    query: string;
}

/**
 * Workflow patterns list response
 */
export interface PatternsListResponse {
    patterns: WorkflowPattern[];
    total: number;
    page: number;
    page_size: number;
}

/**
 * Reset patterns response
 */
export interface ResetPatternsResponse {
    deleted_count: number;
    tenant_id: string;
}

// ============================================
// Tenant Agent Configuration Types (T093, T102)
// ============================================

/**
 * Configuration type (T089)
 */
export type ConfigType = "default" | "custom";

/**
 * Tenant agent configuration (FR-021, FR-022)
 *
 * Represents tenant-level agent configuration that controls
 * agent behavior at the tenant level.
 *
 * Access Control:
 * - All authenticated users can READ config
 * - Only tenant admins can MODIFY config
 */
export interface TenantAgentConfig {
    id: string;
    tenant_id: string;
    config_type: ConfigType;
    llm_model: string;
    llm_temperature: number;
    pattern_learning_enabled: boolean;
    multi_level_thinking_enabled: boolean;
    max_work_plan_steps: number;
    tool_timeout_seconds: number;
    enabled_tools: string[];
    disabled_tools: string[];
    created_at: string;
    updated_at: string;
}

/**
 * Update tenant agent configuration request (T089)
 *
 * All fields are optional - only provided fields will be updated.
 * Validation occurs on the backend.
 */
export interface UpdateTenantAgentConfigRequest {
    llm_model?: string;
    llm_temperature?: number;
    pattern_learning_enabled?: boolean;
    multi_level_thinking_enabled?: boolean;
    max_work_plan_steps?: number;
    tool_timeout_seconds?: number;
    enabled_tools?: string[];
    disabled_tools?: string[];
}

/**
 * Tenant agent configuration service interface (T089, T103)
 */
export interface TenantAgentConfigService {
    /**
     * Get tenant agent configuration
     * Returns default config if no custom config exists (FR-021)
     */
    getConfig(tenantId: string): Promise<TenantAgentConfig>;

    /**
     * Update tenant agent configuration (FR-022)
     * Only accessible to tenant admins
     */
    updateConfig(
        tenantId: string,
        request: UpdateTenantAgentConfigRequest
    ): Promise<TenantAgentConfig>;

    /**
     * Check if current user can modify tenant config
     * Used to conditionally show edit UI
     */
    canModifyConfig(tenantId: string): Promise<boolean>;
}

// ============================================
// Tool Composition Types (T108, T115)
// ============================================

/**
 * Tool composition execution template (T108)
 *
 * Defines how tools are composed together.
 */
export interface ToolCompositionTemplate {
    type: "sequential" | "parallel" | "conditional";
    aggregation?: "merge" | "concatenate" | "prioritize"; // For parallel compositions
    condition?: string; // For conditional compositions
    fallback_alternatives: string[];
}

/**
 * Tool composition (T108)
 *
 * Represents a composition of multiple tools that work together
 * to accomplish complex tasks through intelligent chaining.
 */
export interface ToolComposition {
    id: string;
    name: string;
    description: string;
    tools: string[];
    execution_template: ToolCompositionTemplate;
    success_rate: number;
    success_count: number;
    failure_count: number;
    usage_count: number;
    created_at: string;
    updated_at: string;
}

/**
 * Tool compositions list response (T114)
 */
export interface ToolCompositionsListResponse {
    compositions: ToolComposition[];
    total: number;
}

// ============================================
// SubAgent Types (L3 - Specialized Agent System)
// ============================================

/**
 * SubAgent trigger configuration
 */
export interface SubAgentTrigger {
    description: string;
    examples: string[];
    keywords: string[];
}

/**
 * SubAgent response from API
 */
export interface SubAgentResponse {
    id: string;
    tenant_id: string;
    project_id: string | null;
    name: string;
    display_name: string;
    system_prompt: string;
    trigger: SubAgentTrigger;
    model: string;
    color: string;
    allowed_tools: string[];
    allowed_skills: string[];
    allowed_mcp_servers: string[];
    max_tokens: number;
    temperature: number;
    max_iterations: number;
    enabled: boolean;
    total_invocations: number;
    avg_execution_time_ms: number;
    success_rate: number;
    created_at: string;
    updated_at: string;
    metadata?: Record<string, unknown>;
}

/**
 * SubAgent create request
 */
export interface SubAgentCreate {
    name: string;
    display_name: string;
    system_prompt: string;
    trigger_description: string;
    trigger_examples?: string[];
    trigger_keywords?: string[];
    model?: string;
    color?: string;
    allowed_tools?: string[];
    allowed_skills?: string[];
    allowed_mcp_servers?: string[];
    max_tokens?: number;
    temperature?: number;
    max_iterations?: number;
    project_id?: string;
    metadata?: Record<string, unknown>;
}

/**
 * SubAgent update request
 */
export interface SubAgentUpdate {
    name?: string;
    display_name?: string;
    system_prompt?: string;
    trigger_description?: string;
    trigger_examples?: string[];
    trigger_keywords?: string[];
    model?: string;
    color?: string;
    allowed_tools?: string[];
    allowed_skills?: string[];
    allowed_mcp_servers?: string[];
    max_tokens?: number;
    temperature?: number;
    max_iterations?: number;
    metadata?: Record<string, unknown>;
}

/**
 * SubAgent template for quick creation
 */
export interface SubAgentTemplate {
    name: string;
    display_name: string;
    description: string;
    category?: string;
}

/**
 * SubAgent templates list response
 */
export interface SubAgentTemplatesResponse {
    templates: SubAgentTemplate[];
}

/**
 * SubAgent list response
 */
export interface SubAgentsListResponse {
    subagents: SubAgentResponse[];
    total: number;
}

/**
 * SubAgent stats response
 */
export interface SubAgentStatsResponse {
    id: string;
    total_invocations: number;
    success_rate: number;
    avg_execution_time_ms: number;
    last_invoked_at: string | null;
}

/**
 * SubAgent match response
 */
export interface SubAgentMatchResponse {
    subagent: SubAgentResponse | null;
    confidence: number;
}

// ============================================
// Skill Types (L2 - Agent Skill System)
// ============================================

/**
 * Trigger pattern for skill matching
 */
export interface TriggerPattern {
    pattern: string;
    weight: number;
    examples?: string[];
}

/**
 * Skill response from API
 */
export interface SkillResponse {
    id: string;
    tenant_id: string;
    project_id: string | null;
    name: string;
    description: string;
    trigger_type: "keyword" | "semantic" | "hybrid";
    trigger_patterns: TriggerPattern[];
    tools: string[];
    prompt_template: string | null;
    full_content: string | null;
    status: "active" | "disabled" | "deprecated";
    scope: "system" | "tenant" | "project";
    is_system_skill: boolean;
    success_rate: number;
    success_count: number;
    failure_count: number;
    usage_count: number;
    created_at: string;
    updated_at: string;
    metadata?: Record<string, unknown>;
}

/**
 * Skill create request
 */
export interface SkillCreate {
    name: string;
    description: string;
    trigger_type: "keyword" | "semantic" | "hybrid";
    trigger_patterns: TriggerPattern[];
    tools: string[];
    prompt_template?: string;
    full_content?: string;
    project_id?: string;
    scope?: "tenant" | "project";
    metadata?: Record<string, unknown>;
}

/**
 * Skill update request
 */
export interface SkillUpdate {
    name?: string;
    description?: string;
    trigger_type?: "keyword" | "semantic" | "hybrid";
    trigger_patterns?: TriggerPattern[];
    tools?: string[];
    prompt_template?: string;
    full_content?: string;
    status?: "active" | "disabled" | "deprecated";
    metadata?: Record<string, unknown>;
}

/**
 * Skill list response
 */
export interface SkillsListResponse {
    skills: SkillResponse[];
    total: number;
}

/**
 * Skill match response
 */
export interface SkillMatchResponse {
    skills: SkillResponse[];
}

/**
 * Skill content response
 */
export interface SkillContentResponse {
    skill_id: string;
    name: string;
    full_content: string | null;
    scope: "system" | "tenant" | "project";
    is_system_skill: boolean;
}

/**
 * Tenant skill config response
 */
export interface TenantSkillConfigResponse {
    id: string;
    tenant_id: string;
    system_skill_name: string;
    action: "disable" | "override";
    override_skill_id: string | null;
    created_at: string;
    updated_at: string;
}

/**
 * Tenant skill config list response
 */
export interface TenantSkillConfigListResponse {
    configs: TenantSkillConfigResponse[];
    total: number;
}

/**
 * Skill status for a system skill
 */
export interface SystemSkillStatus {
    system_skill_name: string;
    status: "enabled" | "disabled" | "overridden";
    action: "disable" | "override" | null;
    override_skill_id: string | null;
}

// ============================================
// Skill Execution Event Types (L2 Direct Execution)
// ============================================

/**
 * Skill execution mode
 */
export type SkillExecutionMode = "direct" | "prompt";

/**
 * Skill matched event data
 */
export interface SkillMatchedEventData {
    skill_id: string;
    skill_name: string;
    tools: string[];
    match_score: number;
    execution_mode: SkillExecutionMode;
}

/**
 * Skill execution start event data
 */
export interface SkillExecutionStartEventData {
    skill_id: string;
    skill_name: string;
    tools: string[];
    total_steps: number;
}

/**
 * Skill tool start event data
 */
export interface SkillToolStartEventData {
    skill_id: string;
    skill_name: string;
    tool_name: string;
    tool_input: Record<string, unknown>;
    step_index: number;
    total_steps: number;
    status: "running";
}

/**
 * Skill tool result event data
 */
export interface SkillToolResultEventData {
    skill_id: string;
    skill_name: string;
    tool_name: string;
    result?: unknown;
    error?: string;
    duration_ms: number;
    step_index: number;
    total_steps: number;
    status: "completed" | "error";
}

/**
 * Skill tool execution for UI state
 */
export interface SkillToolExecution {
    tool_name: string;
    tool_input: Record<string, unknown>;
    result?: unknown;
    error?: string;
    status: "running" | "completed" | "error";
    duration_ms?: number;
    step_index: number;
}

/**
 * Skill execution complete event data
 */
export interface SkillExecutionCompleteEventData {
    skill_id: string;
    skill_name: string;
    success: boolean;
    summary: string;
    tool_results: SkillToolExecution[];
    execution_time_ms: number;
    error?: string;
}

/**
 * Skill fallback event data
 */
export interface SkillFallbackEventData {
    skill_name: string;
    reason: "execution_failed" | "execution_error";
    error?: string;
}

/**
 * Context compressed event data
 * Emitted when context window compression occurs during a conversation
 */
export interface ContextCompressedEventData {
    was_compressed: boolean;
    compression_strategy: "none" | "truncate" | "summarize";
    original_message_count: number;
    final_message_count: number;
    estimated_tokens: number;
    token_budget: number;
    budget_utilization_pct: number;
    summarized_message_count: number;
}

/**
 * Skill execution state for UI
 */
export interface SkillExecutionState {
    skill_id: string;
    skill_name: string;
    execution_mode: SkillExecutionMode;
    match_score: number;
    status: "matched" | "executing" | "completed" | "failed" | "fallback";
    tools: string[];
    tool_executions: SkillToolExecution[];
    current_step: number;
    total_steps: number;
    summary?: string;
    error?: string;
    execution_time_ms?: number;
    started_at?: string;
    completed_at?: string;
}

// ============================================
// Execution Timeline Types (UI State)
// ============================================

/**
 * Tool execution status
 */
export type ToolExecutionStatus = "running" | "success" | "failed";

/**
 * Timeline step status
 */
export type TimelineStepStatus = "pending" | "running" | "completed" | "failed";

/**
 * Tool execution record for timeline
 */
export interface ToolExecution {
    id: string;
    toolName: string;
    input: Record<string, unknown>;
    status: ToolExecutionStatus;
    result?: string;
    error?: string;
    startTime: string;
    endTime?: string;
    duration?: number;
    stepNumber?: number;
}

/**
 * Timeline step for execution visualization
 */
export interface TimelineStep {
    stepNumber: number;
    description: string;
    status: TimelineStepStatus;
    startTime?: string;
    endTime?: string;
    duration?: number;
    thoughts: string[];
    toolExecutions: ToolExecution[];
}

/**
 * Display mode for assistant response
 */
export type DisplayMode = "timeline" | "simple-timeline" | "direct";

// ============================================
// MCP (Model Context Protocol) Types
// ============================================

/**
 * MCP server transport types
 */
export type MCPServerType = "stdio" | "sse" | "http" | "websocket";

/**
 * MCP tool information discovered from server
 */
export interface MCPToolInfo {
    name: string;
    description?: string;
    input_schema?: Record<string, unknown>;
}

/**
 * MCP server response from API
 */
export interface MCPServerResponse {
    id: string;
    tenant_id: string;
    name: string;
    description?: string;
    server_type: MCPServerType;
    transport_config: Record<string, unknown>;
    enabled: boolean;
    discovered_tools: MCPToolInfo[];
    last_sync_at?: string;
    created_at: string;
    updated_at: string;
}

/**
 * MCP server create request
 */
export interface MCPServerCreate {
    name: string;
    description?: string;
    server_type: MCPServerType;
    transport_config: Record<string, unknown>;
    enabled?: boolean;
}

/**
 * MCP server update request
 */
export interface MCPServerUpdate {
    name?: string;
    description?: string;
    server_type?: MCPServerType;
    transport_config?: Record<string, unknown>;
    enabled?: boolean;
}

/**
 * MCP servers list response
 */
export interface MCPServersListResponse {
    servers: MCPServerResponse[];
    total: number;
}

/**
 * MCP server sync response (after discovering tools)
 */
export interface MCPServerSyncResponse {
    server: MCPServerResponse;
    tools_count: number;
    message: string;
}

/**
 * MCP server test connection response
 */
export interface MCPServerTestResponse {
    success: boolean;
    message: string;
    latency_ms?: number;
}

/**
 * MCP tool call request
 */
export interface MCPToolCallRequest {
    server_id: string;
    tool_name: string;
    arguments: Record<string, unknown>;
}

/**
 * MCP tool call response
 */
export interface MCPToolCallResponse {
    success: boolean;
    result?: unknown;
    error?: string;
    execution_time_ms: number;
}

/**
 * Transport config for stdio type
 */
export interface StdioTransportConfig {
    command: string;
    args?: string[];
    env?: Record<string, string>;
}

/**
 * Transport config for HTTP/SSE type
 */
export interface HttpTransportConfig {
    url: string;
    headers?: Record<string, string>;
}

/**
 * Transport config for WebSocket type
 */
export interface WebSocketTransportConfig {
    url: string;
}

// ============================================
// Plan Mode Types (Plan Document System)
// ============================================

/**
 * Plan document status
 */
export type PlanDocumentStatus =
    | "draft"
    | "reviewing"
    | "approved"
    | "archived";

/**
 * Agent mode for plan mode switching
 */
export type AgentMode = "build" | "plan" | "explore";

/**
 * Plan document
 */
export interface PlanDocument {
    id: string;
    conversation_id: string;
    title: string;
    content: string;
    status: PlanDocumentStatus;
    version: number;
    metadata: Record<string, unknown>;
    created_at: string;
    updated_at: string;
}

/**
 * Plan mode status response
 */
export interface PlanModeStatus {
    is_in_plan_mode: boolean;
    current_mode: AgentMode;
    current_plan_id: string | null;
    plan: PlanDocument | null;
}

/**
 * Enter plan mode request
 */
export interface EnterPlanModeRequest {
    conversation_id: string;
    title: string;
    description?: string;
}

/**
 * Exit plan mode request
 */
export interface ExitPlanModeRequest {
    conversation_id: string;
    plan_id: string;
    approve?: boolean;
    summary?: string;
}

/**
 * Update plan request
 */
export interface UpdatePlanRequest {
    content?: string;
    title?: string;
    explored_files?: string[];
    critical_files?: Array<{
        path: string;
        type: "create" | "modify" | "delete";
    }>;
    metadata?: Record<string, unknown>;
}

/**
 * Plan Mode SSE event data types
 */
export interface PlanModeEnterEventData {
    conversation_id: string;
    plan_id: string;
    plan_title: string;
}

export interface PlanModeExitEventData {
    conversation_id: string;
    plan_id: string;
    plan_status: PlanDocumentStatus;
    approved: boolean;
}

export interface PlanCreatedEventData {
    plan_id: string;
    title: string;
    conversation_id: string;
}

export interface PlanUpdatedEventData {
    plan_id: string;
    content: string;
    version: number;
}

export interface PlanStatusChangedEventData {
    plan_id: string;
    old_status: PlanDocumentStatus;
    new_status: PlanDocumentStatus;
}

// ============================================
// Timeline Event Types (Unified Event Stream)
// ============================================

/**
 * All possible timeline event types from unified event stream
 */
export type TimelineEventType =
    | "user_message"
    | "assistant_message"
    | "thought"
    | "act"
    | "observe"
    | "work_plan"
    | "step_start"
    | "step_end"
    | "text_delta"
    | "text_start"
    | "text_end"
    // Human-in-the-loop event types
    | "clarification_asked"
    | "clarification_answered"
    | "decision_asked"
    | "decision_answered"
    | "env_var_requested"
    | "env_var_provided"
    // Sandbox event types
    | "sandbox_created"
    | "sandbox_terminated"
    | "sandbox_status"
    | "desktop_started"
    | "desktop_stopped"
    | "desktop_status"
    | "terminal_started"
    | "terminal_stopped"
    | "terminal_status"
    | "screenshot_update";

/**
 * Base timeline event (all events share these fields)
 */
export interface BaseTimelineEvent {
    id: string;
    type: TimelineEventType;
    sequenceNumber: number;
    timestamp: number; // Unix timestamp in milliseconds
    metadata?: Record<string, unknown>;
}

/**
 * User message event
 */
export interface UserMessageEvent extends BaseTimelineEvent {
    type: "user_message";
    content: string;
    role: "user";
}

/**
 * Assistant message event
 */
export interface AssistantMessageEvent extends BaseTimelineEvent {
    type: "assistant_message";
    content: string;
    role: "assistant";
    artifacts?: ArtifactReference[];
}

/**
 * Thought event (agent reasoning)
 */
export interface ThoughtEvent extends BaseTimelineEvent {
    type: "thought";
    content: string;
}

/**
 * Act event (tool call)
 */
export interface ActEvent extends BaseTimelineEvent {
    type: "act";
    toolName: string;
    toolInput: Record<string, unknown>;
    execution_id?: string;  // New: unique ID for act/observe matching
    execution?: {
        startTime: number;
        endTime: number;
        duration: number;
    };
}

/**
 * Observe event (tool result)
 */
export interface ObserveEvent extends BaseTimelineEvent {
    type: "observe";
    toolName: string;
    toolOutput: string;
    isError: boolean;
    execution_id?: string;  // New: matches act event's execution_id
}

/**
 * Work plan event
 */
export interface WorkPlanTimelineEvent extends BaseTimelineEvent {
    type: "work_plan";
    steps: Array<{
        step_number: number;
        description: string;
        expected_output: string;
    }>;
    status: string;
}

/**
 * Step start event
 */
export interface StepStartEvent extends BaseTimelineEvent {
    type: "step_start";
    stepIndex: number;
    stepDescription: string;
}

/**
 * Step end event
 */
export interface StepEndEvent extends BaseTimelineEvent {
    type: "step_end";
    stepIndex: number;
    status: string;
}

/**
 * Text delta event (typewriter effect - incremental text)
 */
export interface TextDeltaEvent extends BaseTimelineEvent {
    type: "text_delta";
    content: string;
}

/**
 * Text start event (typewriter effect - marks beginning)
 */
export interface TextStartEvent extends BaseTimelineEvent {
    type: "text_start";
}

/**
 * Text end event (typewriter effect - marks completion)
 */
export interface TextEndEvent extends BaseTimelineEvent {
    type: "text_end";
    fullText?: string;
}

// ============================================
// Human-in-the-Loop Timeline Event Types
// ============================================

/**
 * Clarification asked event (agent asks user for clarification)
 */
export interface ClarificationAskedTimelineEvent extends BaseTimelineEvent {
    type: "clarification_asked";
    requestId: string;
    question: string;
    clarificationType: ClarificationType;
    options: ClarificationOption[];
    allowCustom: boolean;
    context?: Record<string, unknown>;
    answered?: boolean;
    answer?: string;
}

/**
 * Clarification answered event (user responded to clarification)
 */
export interface ClarificationAnsweredTimelineEvent extends BaseTimelineEvent {
    type: "clarification_answered";
    requestId: string;
    answer: string;
}

/**
 * Decision asked event (agent asks user for decision)
 */
export interface DecisionAskedTimelineEvent extends BaseTimelineEvent {
    type: "decision_asked";
    requestId: string;
    question: string;
    decisionType: DecisionType;
    options: DecisionOption[];
    allowCustom: boolean;
    context?: Record<string, unknown>;
    defaultOption?: string;
    answered?: boolean;
    decision?: string;
}

/**
 * Decision answered event (user made a decision)
 */
export interface DecisionAnsweredTimelineEvent extends BaseTimelineEvent {
    type: "decision_answered";
    requestId: string;
    decision: string;
}

/**
 * Environment variable requested event (agent requests env vars from user)
 */
export interface EnvVarRequestedTimelineEvent extends BaseTimelineEvent {
    type: "env_var_requested";
    requestId: string;
    toolName: string;
    fields: EnvVarField[];
    message?: string;
    context?: Record<string, unknown>;
    answered?: boolean;
    providedVariables?: string[];
}

/**
 * Environment variable provided event (user provided env vars)
 */
export interface EnvVarProvidedTimelineEvent extends BaseTimelineEvent {
    type: "env_var_provided";
    requestId: string;
    toolName: string;
    variableNames: string[];
}

/**
 * Union type for all timeline events
 */
export type TimelineEvent =
    | UserMessageEvent
    | AssistantMessageEvent
    | ThoughtEvent
    | ActEvent
    | ObserveEvent
    | WorkPlanTimelineEvent
    | StepStartEvent
    | StepEndEvent
    | TextDeltaEvent
    | TextStartEvent
    | TextEndEvent
    // Human-in-the-loop events
    | ClarificationAskedTimelineEvent
    | ClarificationAnsweredTimelineEvent
    | DecisionAskedTimelineEvent
    | DecisionAnsweredTimelineEvent
    | EnvVarRequestedTimelineEvent
    | EnvVarProvidedTimelineEvent
    // Sandbox events
    | DesktopStartedEvent
    | DesktopStoppedEvent
    | DesktopStatusEvent
    | TerminalStartedEvent
    | TerminalStoppedEvent
    | TerminalStatusEvent
    | ScreenshotUpdateEvent
    | SandboxCreatedEvent
    | SandboxTerminatedEvent
    | SandboxStatusEvent;

/**
 * Timeline response from API (unified event stream)
 */
export interface TimelineResponse {
    conversationId: string;
    timeline: TimelineEvent[];
    total: number;
}

// ============================================
// Sandbox Types (Desktop and Terminal)
// ============================================

/**
 * Desktop status for remote desktop sessions
 */
export interface DesktopStatus {
    running: boolean;
    url: string | null;
    display: string;
    resolution: string;
    port: number;
    xvfbPid?: number | null;
    xvncPid?: number | null;
}

/**
 * Terminal status for web terminal sessions
 */
export interface TerminalStatus {
    running: boolean;
    url: string | null;
    port: number;
    pid?: number | null;
    sessionId?: string | null;
}

/**
 * Desktop started event data
 */
export interface DesktopStartedEventData {
    sandbox_id: string;
    url: string;
    display: string;
    resolution: string;
    port: number;
}

/**
 * Desktop stopped event data
 */
export interface DesktopStoppedEventData {
    sandbox_id: string;
}

/**
 * Desktop status event data
 */
export interface DesktopStatusEventData extends DesktopStatus {
    sandbox_id: string;
}

/**
 * Terminal started event data
 */
export interface TerminalStartedEventData {
    sandbox_id: string;
    url: string;
    port: number;
    sessionId: string;
}

/**
 * Terminal stopped event data
 */
export interface TerminalStoppedEventData {
    sandbox_id: string;
    sessionId?: string;
}

/**
 * Terminal status event data
 */
export interface TerminalStatusEventData extends TerminalStatus {
    sandbox_id: string;
}

/**
 * Screenshot update event data
 */
export interface ScreenshotUpdateEventData {
    sandbox_id: string;
    imageUrl: string;
    timestamp: number;
}

/**
 * Sandbox created event data
 */
export interface SandboxCreatedEventData {
    sandbox_id: string;
    project_id: string;
    status: string;
    endpoint?: string;
    websocket_url?: string;
}

/**
 * Sandbox terminated event data
 */
export interface SandboxTerminatedEventData {
    sandbox_id: string;
}

/**
 * Sandbox status event data
 */
export interface SandboxStatusEventData {
    sandbox_id: string;
    status: string;
}

/**
 * Desktop started timeline event
 */
export interface DesktopStartedEvent extends BaseTimelineEvent {
    type: "desktop_started";
    sandboxId: string;
    url: string;
    display: string;
    resolution: string;
    port: number;
}

/**
 * Desktop stopped timeline event
 */
export interface DesktopStoppedEvent extends BaseTimelineEvent {
    type: "desktop_stopped";
    sandboxId: string;
}

/**
 * Desktop status timeline event
 */
export interface DesktopStatusEvent extends BaseTimelineEvent {
    type: "desktop_status";
    sandboxId: string;
    running: boolean;
    url: string | null;
    display: string;
    resolution: string;
    port: number;
}

/**
 * Terminal started timeline event
 */
export interface TerminalStartedEvent extends BaseTimelineEvent {
    type: "terminal_started";
    sandboxId: string;
    url: string;
    port: number;
    sessionId: string;
}

/**
 * Terminal stopped timeline event
 */
export interface TerminalStoppedEvent extends BaseTimelineEvent {
    type: "terminal_stopped";
    sandboxId: string;
    sessionId?: string;
}

/**
 * Terminal status timeline event
 */
export interface TerminalStatusEvent extends BaseTimelineEvent {
    type: "terminal_status";
    sandboxId: string;
    running: boolean;
    url: string | null;
    port: number;
    sessionId?: string;
}

/**
 * Screenshot update timeline event
 */
export interface ScreenshotUpdateEvent extends BaseTimelineEvent {
    type: "screenshot_update";
    sandboxId: string;
    imageUrl: string;
}

/**
 * Sandbox created timeline event
 */
export interface SandboxCreatedEvent extends BaseTimelineEvent {
    type: "sandbox_created";
    sandboxId: string;
    projectId: string;
    status: string;
    endpoint?: string;
    websocketUrl?: string;
}

/**
 * Sandbox terminated timeline event
 */
export interface SandboxTerminatedEvent extends BaseTimelineEvent {
    type: "sandbox_terminated";
    sandboxId: string;
}

/**
 * Sandbox status timeline event
 */
export interface SandboxStatusEvent extends BaseTimelineEvent {
    type: "sandbox_status";
    sandboxId: string;
    status: string;
}

// ===========================================================================
// Plan Mode Types
// ===========================================================================

/**
 * Execution plan step status
 */
export type ExecutionStepStatus =
    | "pending"
    | "running"
    | "completed"
    | "failed"
    | "skipped"
    | "cancelled";

/**
 * Execution plan status
 */
export type ExecutionPlanStatus =
    | "draft"
    | "approved"
    | "executing"
    | "paused"
    | "completed"
    | "failed"
    | "cancelled";

/**
 * Reflection assessment
 */
export type ReflectionAssessment =
    | "on_track"
    | "needs_adjustment"
    | "off_track"
    | "complete"
    | "failed";

/**
 * Adjustment type for plan steps
 */
export type AdjustmentType =
    | "modify"
    | "retry"
    | "skip"
    | "add_before"
    | "add_after"
    | "replace";

/**
 * Single execution step in a plan
 */
export interface ExecutionStep {
    step_id: string;
    description: string;
    tool_name: string;
    tool_input: Record<string, unknown>;
    dependencies: string[];
    status: ExecutionStepStatus;
    result?: string;
    error?: string;
    started_at?: string;
    completed_at?: string;
}

/**
 * Step adjustment for reflection
 */
export interface StepAdjustment {
    step_id: string;
    adjustment_type: AdjustmentType;
    reason: string;
    new_tool_input?: Record<string, unknown>;
    new_tool_name?: string;
    new_step?: ExecutionStep;
}

/**
 * Reflection result from plan execution
 */
export interface ReflectionResult {
    assessment: ReflectionAssessment;
    reasoning: string;
    adjustments: StepAdjustment[];
    suggested_next_steps?: string[];
    confidence?: number;
    final_summary?: string;
    error_type?: string;
    reflection_metadata: Record<string, unknown>;
    is_terminal: boolean;
}

/**
 * Plan snapshot for rollback functionality
 */
export interface StepState {
    step_id: string;
    status: string;
    result?: string;
    error?: string;
    started_at?: string;
    completed_at?: string;
    tool_input: Record<string, unknown>;
}

/**
 * Plan snapshot for rollback
 */
export interface PlanSnapshot {
    id: string;
    plan_id: string;
    name: string;
    description?: string;
    step_states: Record<string, StepState>;
    auto_created: boolean;
    snapshot_type: string;
    created_at: string;
}

/**
 * Execution plan for Plan Mode
 */
export interface ExecutionPlan {
    id: string;
    conversation_id: string;
    user_query: string;
    steps: ExecutionStep[];
    status: ExecutionPlanStatus;
    reflection_enabled: boolean;
    max_reflection_cycles: number;
    completed_steps: string[];
    failed_steps: string[];
    snapshot?: PlanSnapshot;
    started_at?: string;
    completed_at?: string;
    error?: string;
    progress_percentage: number;
    is_complete: boolean;
}

// ===========================================================================
// Plan Mode SSE Event Types
// ===========================================================================

/**
 * Plan execution start event
 */
export interface PlanExecutionStartEvent {
    type: "plan_execution_start";
    data: {
        plan_id: string;
        total_steps: number;
        user_query: string;
    };
    timestamp: string;
}

/**
 * Plan execution complete event
 */
export interface PlanExecutionCompleteEvent {
    type: "plan_execution_complete";
    data: {
        plan_id: string;
        status: ExecutionPlanStatus;
        completed_steps: number;
        failed_steps: number;
    };
    timestamp: string;
}

/**
 * Plan step ready event
 */
export interface PlanStepReadyEvent {
    type: "plan_step_ready";
    data: {
        plan_id: string;
        step_id: string;
        step_number: number;
        description: string;
        tool_name: string;
    };
    timestamp: string;
}

/**
 * Plan step complete event
 */
export interface PlanStepCompleteEvent {
    type: "plan_step_complete";
    data: {
        plan_id: string;
        step_id: string;
        status: ExecutionStepStatus;
        result?: string;
    };
    timestamp: string;
}

/**
 * Plan step skipped event
 */
export interface PlanStepSkippedEvent {
    type: "plan_step_skipped";
    data: {
        plan_id: string;
        step_id: string;
        reason: string;
    };
    timestamp: string;
}

/**
 * Plan snapshot created event
 */
export interface PlanSnapshotCreatedEvent {
    type: "plan_snapshot_created";
    data: {
        plan_id: string;
        snapshot_id: string;
        snapshot_name: string;
        snapshot_type: string;
    };
    timestamp: string;
}

/**
 * Plan rollback event
 */
export interface PlanRollbackEvent {
    type: "plan_rollback";
    data: {
        plan_id: string;
        snapshot_id: string;
        reason: string;
    };
    timestamp: string;
}

/**
 * Reflection complete event
 */
export interface ReflectionCompleteEvent {
    type: "reflection_complete";
    data: {
        plan_id: string;
        assessment: ReflectionAssessment;
        reasoning: string;
        has_adjustments: boolean;
        adjustment_count: number;
    };
    timestamp: string;
}

/**
 * Adjustment applied event
 */
export interface AdjustmentAppliedEvent {
    type: "adjustment_applied";
    data: {
        plan_id: string;
        adjustment_count: number;
        adjustments: StepAdjustment[];
    };
    timestamp: string;
}

/**
 * Union type for all Plan Mode events
 */
export type PlanModeEvent =
    | PlanExecutionStartEvent
    | PlanExecutionCompleteEvent
    | PlanStepReadyEvent
    | PlanStepCompleteEvent
    | PlanStepSkippedEvent
    | PlanSnapshotCreatedEvent
    | PlanRollbackEvent
    | ReflectionCompleteEvent
    | AdjustmentAppliedEvent;

// ============================================
// Lifecycle State Types (Agent Lifecycle Monitoring)
// ============================================

/**
 * Lifecycle states for ProjectReActAgent
 */
export type LifecycleState =
    | "initializing"
    | "ready"
    | "executing"
    | "paused"
    | "shutting_down"
    | "error";

/**
 * Lifecycle state data from WebSocket
 */
export interface LifecycleStateData {
    lifecycleState: LifecycleState | null;
    isInitialized: boolean;
    isActive: boolean;
    toolCount?: number;
    skillCount?: number;
    subagentCount?: number;
    conversationId?: string;
    errorMessage?: string;
}

/**
 * Lifecycle status for UI display
 */
export interface LifecycleStatus {
    label: string;
    color: string;
    icon: string;
    description: string;
}
