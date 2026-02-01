/**
 * Agent Service - Agent chat and conversation management
 *
 * Provides methods for interacting with the React-mode Agent backend API, including:
 * - Creating and managing conversations
 * - Sending messages and receiving streaming responses via WebSocket
 * - Getting conversation history and message lists
 * - Listing available tools and execution history
 *
 * @packageDocumentation
 *
 * @example
 * ```typescript
 * import { agentService } from '@/services/agentService';
 *
 * // Create a new conversation
 * const conversation = await agentService.createConversation({
 *   project_id: 'proj-123',
 *   title: 'My Conversation',
 *   mode: 'chat'
 * });
 *
 * // Chat with streaming responses
 * await agentService.chat({
 *   conversation_id: conversation.id,
 *   message: 'Hello, Agent!',
 *   project_id: 'proj-123'
 * }, {
 *   onMessage: (event) => console.log('Message:', event.data),
 *   onThought: (event) => console.log('Thought:', event.data),
 *   onComplete: (event) => console.log('Complete:', event.data),
 *   onError: (event) => console.error('Error:', event.data.message)
 * });
 * ```
 */

import { ApiError } from "./client/ApiError";
import { httpClient } from "./client/httpClient";
import { logger } from "../utils/logger";
import { getAuthToken } from "../utils/tokenResolver";
import { createWebSocketUrl } from "./client/urlUtils";
import type {
    AgentEvent,
    AgentEventType,
    AgentService,
    AgentStreamHandler,
    ChatRequest,
    Conversation,
    CreateConversationRequest,
    CreateConversationResponse,
    ConversationMessagesResponse,
    ExecutionHistoryResponse,
    ExecutionStatsResponse,
    ToolExecutionsResponse,
    ToolsListResponse,
    MessageEventData,
    ThoughtEventData,
    ThoughtDeltaEventData,
    WorkPlanEventData,
    PatternMatchEventData,
    StepStartEventData,
    StepEndEventData,
    ActEventData,
    ObserveEventData,
    TextDeltaEventData,
    TextEndEventData,
    ClarificationAskedEventData,
    ClarificationAnsweredEventData,
    DecisionAskedEventData,
    DecisionAnsweredEventData,
    EnvVarRequestedEventData,
    EnvVarProvidedEventData,
    CompleteEventData,
    TitleGeneratedEventData,
    ErrorEventData,
    SkillMatchedEventData,
    SkillExecutionStartEventData,
    SkillToolStartEventData,
    SkillToolResultEventData,
    SkillExecutionCompleteEventData,
    SkillFallbackEventData,
    ContextCompressedEventData,
    PlanModeEnterEventData,
    PlanModeExitEventData,
    PlanCreatedEventData,
    PlanUpdatedEventData,
    PlanExecutionStartEvent,
    PlanExecutionCompleteEvent,
    ReflectionCompleteEvent,
    LifecycleState,
    LifecycleStateData,
    PendingHITLResponse,
    ArtifactCreatedEventData,
} from "../types/agent";

// Use centralized HTTP client for REST API calls
const api = httpClient;

/**
 * Generate a unique session ID for this browser tab
 *
 * Uses crypto.randomUUID if available (modern browsers), falls back to
 * timestamp + random string for older browsers.
 *
 * @returns A unique session ID string
 *
 * @example
 * ```typescript
 * const sessionId = generateSessionId(); // "550e8400-e29b-41d4-a716-446655440000"
 * ```
 */
function generateSessionId(): string {
    if (typeof crypto !== "undefined" && crypto.randomUUID) {
        return crypto.randomUUID();
    }
    // Fallback for older browsers
    return `${Date.now()}-${Math.random().toString(36).substring(2, 15)}`;
}

/**
 * WebSocket connection status
 *
 * Represents the current state of the WebSocket connection to the Agent API.
 *
 * @example
 * ```typescript
 * const status: WebSocketStatus = agentService.getStatus();
 * if (status === 'connected') {
 *   // Safe to send messages
 * }
 * ```
 */
export type WebSocketStatus =
    | "connecting"
    | "connected"
    | "disconnected"
    | "error";

/**
 * WebSocket message from server
 *
 * Represents a message received from the Agent WebSocket server.
 * Messages contain event type, optional conversation ID, and associated data.
 *
 * @example
 * ```typescript
 * const message: ServerMessage = {
 *   type: 'text_delta',
 *   conversation_id: 'conv-123',
 *   data: { delta: 'Hello' },
 *   seq: 1,
 *   timestamp: '2024-01-01T00:00:00Z'
 * };
 * ```
 */
interface ServerMessage {
    type: string;
    conversation_id?: string;
    data?: unknown;
    seq?: number;
    timestamp?: string;
    action?: string;
}

/**
 * Agent service implementation with WebSocket support
 *
 * Each instance has a unique session_id to support multiple browser tabs.
 * Manages WebSocket connection lifecycle, event routing, and reconnection logic.
 *
 * @see AgentService - Interface this class implements
 */
class AgentServiceImpl implements AgentService {
    private ws: WebSocket | null = null;
    private status: WebSocketStatus = "disconnected";
    private reconnectAttempts = 0;
    private maxReconnectAttempts = 5;
    private reconnectDelay = 1000;
    private reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
    private isManualClose = false;

    // Unique session ID for this browser tab (generated once per page load)
    private sessionId: string = generateSessionId();

    // Heartbeat interval to keep WebSocket connection alive
    private heartbeatInterval: ReturnType<typeof setInterval> | null = null;
    private readonly HEARTBEAT_INTERVAL_MS = 30000; // 30 seconds

    // Handler maps by conversation_id
    private handlers: Map<string, AgentStreamHandler> = new Map();

    // Status change listeners
    private statusListeners: Set<(status: WebSocketStatus) => void> = new Set();

    // Pending subscriptions (to restore after reconnect)
    private subscriptions: Set<string> = new Set();

    // Status subscription for Agent session monitoring
    private statusSubscriber: { projectId: string; callback: (status: unknown) => void } | null = null;

    // Lifecycle state subscription for Agent lifecycle monitoring
    private lifecycleStateSubscriber: { projectId: string; tenantId: string; callback: (state: LifecycleStateData) => void } | null = null;

    // Connection lock to prevent parallel connection attempts
    private connectingPromise: Promise<void> | null = null;

    // Performance tracking: Track event receive times for diagnostics
    private performanceMetrics: Map<string, number[]> = new Map();
    private readonly MAX_METRICS_SAMPLES = 100;

    /**
     * Get the session ID for this instance
     *
     * Returns the unique session ID generated when the service was created.
     * This ID is used to support multiple browser tabs per user.
     *
     * @returns The unique session ID for this browser tab
     *
     * @example
     * ```typescript
     * const sessionId = agentService.getSessionId();
     * console.log(`Session ID: ${sessionId}`);
     * ```
     */
    getSessionId(): string {
        return this.sessionId;
    }

    /**
     * Connect to WebSocket server
     *
     * Establishes a WebSocket connection to the Agent API. Includes authentication
     * via Bearer token and automatic reconnection on disconnect.
     *
     * @returns Promise that resolves when connection is established
     * @throws {Error} If no authentication token is found in localStorage
     *
     * @example
     * ```typescript
     * await agentService.connect();
     * console.log('Connected to Agent WebSocket');
     * ```
     */
    connect(): Promise<void> {
        // Return existing connecting promise if already connecting
        if (this.connectingPromise) {
            logger.debug("[AgentWS] Connection already in progress, returning existing promise");
            return this.connectingPromise;
        }

        // Already connected
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            logger.debug("[AgentWS] Already connected");
            return Promise.resolve();
        }

        this.isManualClose = false;
        this.setStatus("connecting");

        // Create and store the connecting promise
        this.connectingPromise = this.doConnect();
        return this.connectingPromise;
    }

    private doConnect(): Promise<void> {
        return new Promise((resolve, reject) => {

            const token = getAuthToken();
            if (!token) {
                this.setStatus("error");
                reject(new Error("No authentication token"));
                return;
            }

            // Include session_id in WebSocket URL for multi-tab support
            const wsUrl = createWebSocketUrl('/agent/ws', {
                token,
                session_id: this.sessionId,
            });

            try {
                this.ws = new WebSocket(wsUrl);

                this.ws.onopen = () => {
                    logger.debug(`[AgentWS] Connected (session: ${this.sessionId.substring(0, 8)}...)`);
                    this.setStatus("connected");
                    this.reconnectAttempts = 0;
                    this.reconnectDelay = 1000;
                    this.connectingPromise = null; // Clear lock

                    // Start heartbeat to keep connection alive
                    this.startHeartbeat();

                    // Resubscribe to previous conversations
                    this.resubscribe();
                    resolve();
                };

                this.ws.onmessage = (event) => {
                    try {
                        const message: ServerMessage = JSON.parse(event.data);
                        this.handleMessage(message);
                    } catch (err) {
                        logger.error("[AgentWS] Failed to parse message:", err);
                    }
                };

                this.ws.onclose = (event) => {
                    logger.debug("[AgentWS] Disconnected", event.code, event.reason);
                    this.setStatus("disconnected");

                    if (
                        !this.isManualClose &&
                        this.reconnectAttempts < this.maxReconnectAttempts
                    ) {
                        this.scheduleReconnect();
                    }
                };

                this.ws.onerror = (error) => {
                    logger.error("[AgentWS] Error:", error);
                    this.setStatus("error");
                    this.stopHeartbeat();
                    this.connectingPromise = null; // Clear lock on error
                    reject(error);
                };
            } catch (err) {
                logger.error("[AgentWS] Connection error:", err);
                this.setStatus("error");
                this.connectingPromise = null; // Clear lock on error
                this.scheduleReconnect();
                reject(err);
            }
        });
    }

    /**
     * Disconnect from WebSocket server
     *
     * Manually closes the WebSocket connection and stops automatic reconnection.
     * Clears heartbeat interval and cleanup up reconnection timeout.
     *
     * @example
     * ```typescript
     * // When component unmounts
     * useEffect(() => {
     *   return () => agentService.disconnect();
     * }, []);
     * ```
     */
    disconnect(): void {
        this.isManualClose = true;

        // Stop heartbeat
        this.stopHeartbeat();

        if (this.reconnectTimeout) {
            clearTimeout(this.reconnectTimeout);
            this.reconnectTimeout = null;
        }

        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }

        this.setStatus("disconnected");
    }

    /**
     * Get current connection status
     *
     * Returns the current WebSocket connection status.
     *
     * @returns The current connection status
     *
     * @example
     * ```typescript
     * const status = agentService.getStatus();
     * if (status === 'connected') {
     *   // Can send messages
     * }
     * ```
     */
    getStatus(): WebSocketStatus {
        return this.status;
    }

    /**
     * Check if connected
     *
     * Convenience method to check if WebSocket is currently connected.
     *
     * @returns true if WebSocket is connected, false otherwise
     *
     * @example
     * ```typescript
     * if (agentService.isConnected()) {
     *   // Safe to send messages
     * }
     * ```
     */
    isConnected(): boolean {
        return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
    }

    /**
     * Register a status change listener
     *
     * Registers a callback function that will be invoked whenever the
     * WebSocket connection status changes.
     *
     * @param listener - Callback function invoked with the new status
     * @returns Unsubscribe function that removes the listener
     *
     * @example
     * ```typescript
     * const unsubscribe = agentService.onStatusChange((status) => {
     *   console.log('Status changed to:', status);
     * });
     *
     * // Later, to stop listening
     * unsubscribe();
     * ```
     */
    onStatusChange(listener: (status: WebSocketStatus) => void): () => void {
        this.statusListeners.add(listener);
        listener(this.status);
        return () => this.statusListeners.delete(listener);
    }

    /**
     * Send a message through WebSocket
     *
     * Internal method to send a message to the WebSocket server.
     *
     * @param message - The message object to send
     * @returns true if message was sent successfully, false otherwise
     * @private
     */
    private send(message: Record<string, unknown>): boolean {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(message));
            return true;
        }
        return false;
    }

    /**
     * Handle incoming WebSocket message
     *
     * Routes incoming messages to appropriate handlers based on event type.
     * Records performance metrics for monitoring event latency.
     *
     * @param message - The server message to handle
     * @private
     */
    private handleMessage(message: ServerMessage): void {
        const { type, conversation_id, data, seq } = message;

        // Performance tracking: Record event receive timestamp
        const receiveTime = performance.now();
        this.recordEventMetric(type, receiveTime);

        // Enhanced logging for debugging TEXT_DELTA issues
        if (type === "text_delta") {
            const delta = (data as { delta?: string } | undefined)?.delta || "";
            logger.debug(
                `[AgentWS] TEXT_DELTA: seq=${seq}, len=${delta.length}, preview="${delta.substring(0, 30)}..."`
            );
        } else if (type === "text_start" || type === "text_end" || type === "complete" || type === "error") {
            logger.debug(`[AgentWS] ${type.toUpperCase()}: seq=${seq}, conversation=${conversation_id}`);
        } else {
            logger.debug("[AgentWS] handleMessage:", { type, conversation_id, seq, hasData: !!data });
        }

        // Handle non-conversation-specific messages
        if (type === "connected") {
            logger.debug("[AgentWS] Connection confirmed:", data);
            return;
        }

        if (type === "pong") {
            // Heartbeat response
            return;
        }

        if (type === "ack") {
            logger.debug(`[AgentWS] Ack for ${message.action} on ${conversation_id}`);
            // Ack handling simplified - just log
            return;
        }

        // Handle status updates for session monitoring
        if (type === "status_update") {
            if (this.statusSubscriber && (data as { project_id?: string })?.project_id === this.statusSubscriber.projectId) {
                this.statusSubscriber.callback(data);
            }
            return;
        }

        // Handle lifecycle state changes
        if (type === "lifecycle_state_change") {
            const projectId = (message as { project_id?: string }).project_id;
            if (this.lifecycleStateSubscriber && projectId === this.lifecycleStateSubscriber.projectId) {
                this.lifecycleStateSubscriber.callback(this.parseLifecycleStateData(message));
            }
            return;
        }

        // Route conversation-specific messages to handlers
        if (conversation_id) {
            const handler = this.handlers.get(conversation_id);
            // DEBUG: Enhanced logging for recovery troubleshooting
            const isRecovery = (message as { is_recovery?: boolean }).is_recovery;
            logger.debug("[AgentWS] Looking for handler:", {
                conversation_id,
                hasHandler: !!handler,
                handlersSize: this.handlers.size,
                type,
                isRecovery,
            });
            if (handler) {
                this.routeToHandler(type as AgentEventType, data, handler);
            } else {
                logger.warn("[AgentWS] No handler found for conversation:", conversation_id);
            }
        }
    }

    /**
     * Parse lifecycle state data from WebSocket message
     * @private
     */
    private parseLifecycleStateData(message: ServerMessage): LifecycleStateData {
        const data = (message as { data?: Record<string, unknown> }).data || {};
        return {
            lifecycleState: data.lifecycle_state as LifecycleState | null,
            isInitialized: Boolean(data.is_initialized),
            isActive: Boolean(data.is_active),
            toolCount: typeof data.tool_count === "number" ? data.tool_count : undefined,
            skillCount: typeof data.skill_count === "number" ? data.skill_count : undefined,
            subagentCount: typeof data.subagent_count === "number" ? data.subagent_count : undefined,
            conversationId: typeof data.conversation_id === "string" ? data.conversation_id : undefined,
            errorMessage: typeof data.error_message === "string" ? data.error_message : undefined,
        };
    }

    /**
     * Route event to appropriate handler method
     *
     * Routes Agent events to their corresponding handler callbacks.
     * Type assertions are safe because the backend ensures data matches event type.
     *
     * @param eventType - The type of Agent event
     * @param data - The event data (shape depends on eventType)
     * @param handler - The handler containing callback methods
     * @private
     */
    private routeToHandler(
        eventType: AgentEventType,
        data: unknown,
        handler: AgentStreamHandler
    ): void {
        logger.debug("[AgentWS] routeToHandler:", { eventType, hasData: !!data });
        const event = { type: eventType, data };

        switch (eventType) {
            case "message":
                handler.onMessage?.(event as AgentEvent<MessageEventData>);
                break;
            case "thought":
                handler.onThought?.(event as AgentEvent<ThoughtEventData>);
                break;
            case "thought_delta":
                // Route thought_delta to onThoughtDelta handler for incremental thought updates
                handler.onThoughtDelta?.(event as AgentEvent<ThoughtDeltaEventData>);
                break;
            case "work_plan":
                handler.onWorkPlan?.(event as AgentEvent<WorkPlanEventData>);
                break;
            case "pattern_match":
                handler.onPatternMatch?.(event as AgentEvent<PatternMatchEventData>);
                break;
            case "step_start":
                handler.onStepStart?.(event as AgentEvent<StepStartEventData>);
                break;
            case "step_end":
                handler.onStepEnd?.(event as AgentEvent<StepEndEventData>);
                break;
            case "act":
                handler.onAct?.(event as AgentEvent<ActEventData>);
                break;
            case "observe":
                handler.onObserve?.(event as AgentEvent<ObserveEventData>);
                break;
            case "text_start":
                handler.onTextStart?.();
                break;
            case "text_delta":
                handler.onTextDelta?.(event as AgentEvent<TextDeltaEventData>);
                break;
            case "text_end":
                handler.onTextEnd?.(event as AgentEvent<TextEndEventData>);
                break;
            case "clarification_asked":
                handler.onClarificationAsked?.(event as AgentEvent<ClarificationAskedEventData>);
                break;
            case "clarification_answered":
                handler.onClarificationAnswered?.(event as AgentEvent<ClarificationAnsweredEventData>);
                break;
            case "decision_asked":
                handler.onDecisionAsked?.(event as AgentEvent<DecisionAskedEventData>);
                break;
            case "decision_answered":
                handler.onDecisionAnswered?.(event as AgentEvent<DecisionAnsweredEventData>);
                break;
            // Environment variable events
            case "env_var_requested":
                handler.onEnvVarRequested?.(event as AgentEvent<EnvVarRequestedEventData>);
                break;
            case "env_var_provided":
                handler.onEnvVarProvided?.(event as AgentEvent<EnvVarProvidedEventData>);
                break;
            case "complete":
                handler.onComplete?.(event as AgentEvent<CompleteEventData>);
                // Clean up handler after completion
                // Note: Don't remove immediately, some events might still come
                break;
            case "title_generated":
                handler.onTitleGenerated?.(event as AgentEvent<TitleGeneratedEventData>);
                break;
            case "error":
                handler.onError?.(event as AgentEvent<ErrorEventData>);
                break;
            // Skill execution events (L2 layer)
            case "skill_matched":
                handler.onSkillMatched?.(event as AgentEvent<SkillMatchedEventData>);
                break;
            case "skill_execution_start":
                handler.onSkillExecutionStart?.(event as AgentEvent<SkillExecutionStartEventData>);
                break;
            case "skill_tool_start":
                handler.onSkillToolStart?.(event as AgentEvent<SkillToolStartEventData>);
                break;
            case "skill_tool_result":
                handler.onSkillToolResult?.(event as AgentEvent<SkillToolResultEventData>);
                break;
            case "skill_execution_complete":
                handler.onSkillExecutionComplete?.(event as AgentEvent<SkillExecutionCompleteEventData>);
                break;
            case "skill_fallback":
                handler.onSkillFallback?.(event as AgentEvent<SkillFallbackEventData>);
                break;
            // Artifact events
            case "artifact_created":
                handler.onArtifactCreated?.(event as AgentEvent<ArtifactCreatedEventData>);
                break;
            // Context management events
            case "context_compressed":
                handler.onContextCompressed?.(event as AgentEvent<ContextCompressedEventData>);
                break;
            // Plan Mode events
            case "plan_mode_enter":
                handler.onPlanModeEnter?.(event as AgentEvent<PlanModeEnterEventData>);
                break;
            case "plan_mode_exit":
                handler.onPlanModeExit?.(event as AgentEvent<PlanModeExitEventData>);
                break;
            case "plan_created":
                handler.onPlanCreated?.(event as AgentEvent<PlanCreatedEventData>);
                break;
            case "plan_updated":
                handler.onPlanUpdated?.(event as AgentEvent<PlanUpdatedEventData>);
                break;
            // Plan Mode execution events
            case "plan_execution_start":
                handler.onPlanExecutionStart?.(event as AgentEvent<PlanExecutionStartEvent>);
                break;
            case "plan_execution_complete":
                handler.onPlanExecutionComplete?.(event as AgentEvent<PlanExecutionCompleteEvent>);
                break;
            case "reflection_complete":
                handler.onReflectionComplete?.(event as AgentEvent<ReflectionCompleteEvent>);
                break;
        }
    }

    private setStatus(status: WebSocketStatus): void {
        this.status = status;
        this.statusListeners.forEach((listener) => {
            try {
                listener(status);
            } catch (err) {
                logger.error("[AgentWS] Status listener error:", err);
            }
        });
    }

    private scheduleReconnect(): void {
        if (this.reconnectTimeout) {
            return;
        }

        this.reconnectAttempts++;
        const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);

        logger.debug(
            `[AgentWS] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`
        );

        this.reconnectTimeout = setTimeout(() => {
            this.reconnectTimeout = null;
            this.connect().catch((err) => {
                logger.error("[AgentWS] Reconnect failed:", err);
            });
        }, delay);
    }

    private resubscribe(): void {
        // Resubscribe to conversation streams
        this.subscriptions.forEach((conversationId) => {
            this.send({
                type: "subscribe",
                conversation_id: conversationId,
            });
        });

        // Resubscribe to status updates if active
        if (this.statusSubscriber) {
            this.send({
                type: "subscribe_status",
                project_id: this.statusSubscriber.projectId,
                polling_interval: 3000,
            });
        }

        // Resubscribe to lifecycle state updates if active
        if (this.lifecycleStateSubscriber) {
            this.send({
                type: "subscribe_lifecycle_state",
                project_id: this.lifecycleStateSubscriber.projectId,
            });
        }
    }

    private startHeartbeat(): void {
        // Clear any existing heartbeat
        this.stopHeartbeat();

        // Send heartbeat every 30 seconds to keep connection alive
        this.heartbeatInterval = setInterval(() => {
            if (this.isConnected()) {
                this.send({ type: "heartbeat" });
            }
        }, this.HEARTBEAT_INTERVAL_MS);

        logger.debug("[AgentWS] Heartbeat started");
    }

    private stopHeartbeat(): void {
        if (this.heartbeatInterval) {
            clearInterval(this.heartbeatInterval);
            this.heartbeatInterval = null;
        }
    }

    /**
     * Create a new conversation
     *
     * Creates a new Agent conversation with the specified project and configuration.
     *
     * @param request - The conversation creation request
     * @param request.project_id - The project ID to associate with the conversation
     * @param request.title - Optional title for the conversation
     * @param request.mode - Conversation mode ("chat" | "plan" | "execute")
     * @param request.config - Optional Agent configuration overrides
     * @returns Promise resolving to the created conversation
     * @throws {ApiError} If creation fails (e.g., invalid project_id)
     *
     * @example
     * ```typescript
     * const conversation = await agentService.createConversation({
     *   project_id: 'proj-123',
     *   title: 'Help with research',
     *   mode: 'chat'
     * });
     * console.log('Conversation ID:', conversation.id);
     * ```
     */
    async createConversation(
        request: CreateConversationRequest
    ): Promise<CreateConversationResponse> {
        const response = await api.post<CreateConversationResponse>(
            "/agent/conversations",
            request
        );
        return response;
    }

    /**
     * List conversations for a project
     *
     * Retrieves a list of conversations for a project, with optional status filtering.
     *
     * @param projectId - The project ID to list conversations for
     * @param status - Optional status filter ("active" | "archived" | "deleted")
     * @param limit - Maximum number of conversations to return (default: 50)
     * @returns Promise resolving to an array of conversations
     * @throws {ApiError} If the project doesn't exist or user lacks access
     *
     * @example
     * ```typescript
     * // Get all active conversations
     * const conversations = await agentService.listConversations('proj-123', 'active');
     *
     * // Get first 10 conversations (any status)
     * const recent = await agentService.listConversations('proj-123', undefined, 10);
     * ```
     */
    async listConversations(
        projectId: string,
        status?: "active" | "archived" | "deleted",
        limit = 50
    ): Promise<Conversation[]> {
        const params: Record<string, string | number> = {
            project_id: projectId,
            limit,
        };
        if (status) {
            params.status = status;
        }
        const response = await api.get<Conversation[]>(
            "/agent/conversations",
            { params }
        );
        return response;
    }

    /**
     * Get a conversation by ID
     *
     * Retrieves a single conversation by its ID. Returns null if not found (404).
     *
     * @param conversationId - The conversation ID to retrieve
     * @param projectId - The project ID for scoping
     * @returns Promise resolving to the conversation or null if not found
     * @throws {ApiError} For errors other than 404 (e.g., permission denied)
     *
     * @example
     * ```typescript
     * const conversation = await agentService.getConversation('conv-123', 'proj-123');
     * if (conversation) {
     *   console.log('Title:', conversation.title);
     * } else {
     *   console.log('Conversation not found');
     * }
     * ```
     */
    async getConversation(
        conversationId: string,
        projectId: string
    ): Promise<Conversation | null> {
        try {
            const response = await api.get<Conversation>(
                `/agent/conversations/${conversationId}`,
                {
                    params: { project_id: projectId },
                }
            );
            return response;
        } catch (error) {
            if (error instanceof ApiError && error.statusCode === 404) {
                return null;
            }
            throw error;
        }
    }

    /**
     * Stop the chat/agent execution for a conversation
     *
     * Sends a stop signal through WebSocket to halt ongoing Agent execution.
     * This is a key advantage of WebSocket - immediate bidirectional communication.
     *
     * @param conversationId - The conversation ID to stop
     *
     * @example
     * ```typescript
     * // User clicks "Stop" button during Agent execution
     * agentService.stopChat('conv-123');
     * ```
     */
    stopChat(conversationId: string): void {
        // Send stop signal through WebSocket
        const sent = this.send({
            type: "stop_session",
            conversation_id: conversationId,
        });

        if (sent) {
            logger.debug(
                `[AgentWS] Stop signal sent for conversation ${conversationId}`
            );
        }

        // Clean up handler
        this.handlers.delete(conversationId);
        this.subscriptions.delete(conversationId);
    }

    /**
     * Chat with the Agent using WebSocket
     *
     * Sends a message to the Agent and receives streaming responses through WebSocket.
     * Replaces the previous SSE-based implementation with bidirectional communication.
     *
     * Events are routed to the appropriate handler callbacks (onMessage, onThought, etc.).
     *
     * @param request - The chat request
     * @param request.conversation_id - The conversation ID
     * @param request.message - The message content to send
     * @param request.project_id - The project ID for scoping
     * @param handler - Event handler callbacks for streaming responses
     * @returns Promise that resolves when message is sent
     * @throws {Error} If WebSocket is not connected
     *
     * @example
     * ```typescript
     * await agentService.chat({
     *   conversation_id: 'conv-123',
     *   message: 'What is the capital of France?',
     *   project_id: 'proj-123'
     * }, {
     *   onMessage: (event) => updateUI(event.data),
     *   onThought: (event) => showThought(event.data.content),
     *   onComplete: (event) => markComplete(),
     *   onError: (event) => showError(event.data.message)
     * });
     * ```
     *
     * @see AgentStreamHandler - Handler interface for all available callbacks
     */
    async chat(request: ChatRequest, handler: AgentStreamHandler): Promise<void> {
        const { conversation_id, message, project_id } = request;

        // Ensure WebSocket is connected
        if (!this.isConnected()) {
            await this.connect();
        }

        // Register handler for this conversation
        this.handlers.set(conversation_id, handler);
        this.subscriptions.add(conversation_id);

        // Send message through WebSocket
        const sent = this.send({
            type: "send_message",
            conversation_id,
            message,
            project_id,
        });

        if (!sent) {
            handler.onError?.({
                type: "error",
                data: {
                    message: "Failed to send message - WebSocket not connected",
                    isReconnectable: true,
                },
            });
            throw new Error("WebSocket not connected");
        }
    }

    /**
     * Subscribe to a conversation's events
     *
     * Registers to receive events for a specific conversation.
     * Useful for reconnecting to an active conversation or monitoring background execution.
     *
     * @param conversationId - The conversation ID to subscribe to
     * @param handler - Event handler callbacks for this conversation
     *
     * @example
     * ```typescript
     * // Reconnect to an existing conversation
     * agentService.subscribe('conv-123', {
     *   onTextDelta: (event) => appendToOutput(event.data.delta),
     *   onComplete: (event) => saveResponse(event.data.content)
     * });
     * ```
     */
    subscribe(conversationId: string, handler: AgentStreamHandler): void {
        this.handlers.set(conversationId, handler);
        this.subscriptions.add(conversationId);

        if (this.isConnected()) {
            this.send({
                type: "subscribe",
                conversation_id: conversationId,
            });
        }
    }
    /**
     * Unsubscribe from a conversation's events
     *
     * Removes the event handler for a conversation and stops receiving its events.
     *
     * @param conversationId - The conversation ID to unsubscribe from
     *
     * @example
     * ```typescript
     * // When navigating away from conversation page
     * useEffect(() => {
     *   agentService.subscribe(conversationId, handler);
     *   return () => agentService.unsubscribe(conversationId);
     * }, [conversationId]);
     * ```
     */
    unsubscribe(conversationId: string): void {
        this.handlers.delete(conversationId);
        this.subscriptions.delete(conversationId);

        if (this.isConnected()) {
            this.send({
                type: "unsubscribe",
                conversation_id: conversationId,
            });
        }
    }

    /**
     * Send heartbeat to keep connection alive
     *
     * Manually sends a heartbeat message. Usually not needed as the service
     * automatically sends heartbeats every 30 seconds.
     *
     * @example
     * ```typescript
     * // Force a heartbeat (rarely needed)
     * agentService.sendHeartbeat();
     * ```
     */
    sendHeartbeat(): void {
        this.send({ type: "heartbeat" });
    }

    /**
     * Delete a conversation
     *
     * Permanently deletes a conversation and all its associated messages.
     *
     * @param conversationId - The conversation ID to delete
     * @param projectId - The project ID for scoping
     * @returns Promise that resolves when deletion is complete
     * @throws {ApiError} If conversation doesn't exist or user lacks permission
     *
     * @example
     * ```typescript
     * await agentService.deleteConversation('conv-123', 'proj-123');
     * console.log('Conversation deleted');
     * ```
     */
    async deleteConversation(
        conversationId: string,
        projectId: string
    ): Promise<void> {
        await api.delete(`/agent/conversations/${conversationId}`, {
            params: { project_id: projectId },
        });
    }

    /**
     * Update conversation title
     *
     * Manually update the title of a conversation.
     *
     * @param conversationId - The conversation ID to update
     * @param projectId - The project ID for scoping
     * @param title - The new title for the conversation
     * @returns Promise resolving to the updated conversation
     * @throws {ApiError} If conversation doesn't exist or update fails
     *
     * @example
     * ```typescript
     * const updated = await agentService.updateConversationTitle('conv-123', 'proj-123', 'New Title');
     * console.log('Updated title:', updated.title);
     * ```
     */
    async updateConversationTitle(
        conversationId: string,
        projectId: string,
        title: string
    ): Promise<Conversation> {
        const response = await api.patch<Conversation>(
            `/agent/conversations/${conversationId}`,
            { title },
            {
                params: { project_id: projectId },
            }
        );
        return response;
    }

    /**
     * Generate and update conversation title
     *
     * Uses the Agent to analyze the conversation and generate an appropriate title.
     * Useful for auto-titling conversations based on their content.
     *
     * @param conversationId - The conversation ID to generate a title for
     * @param projectId - The project ID for scoping
     * @returns Promise resolving to the updated conversation with new title
     * @throws {ApiError} If conversation doesn't exist or title generation fails
     *
     * @example
     * ```typescript
     * const updated = await agentService.generateConversationTitle('conv-123', 'proj-123');
     * console.log('New title:', updated.title);
     * ```
     */
    async generateConversationTitle(
        conversationId: string,
        projectId: string
    ): Promise<Conversation> {
        const response = await api.post<Conversation>(
            `/agent/conversations/${conversationId}/generate-title`,
            {},
            {
                params: { project_id: projectId },
            }
        );
        return response;
    }

    /**
     * Get messages in a conversation
     *
     * Retrieves paginated messages from a conversation, with optional sequence-based filtering.
     *
     * @param conversationId - The conversation ID
     * @param projectId - The project ID for scoping
     * @param limit - Maximum number of messages to return (default: 100)
     * @param fromSequence - Optional starting sequence number (for pagination)
     * @param beforeSequence - Optional ending sequence number (for pagination)
     * @returns Promise resolving to messages and pagination metadata
     * @throws {ApiError} If conversation doesn't exist or user lacks access
     *
     * @example
     * ```typescript
     * // Get first 100 messages
     * const result = await agentService.getConversationMessages('conv-123', 'proj-123');
     * console.log('Messages:', result.messages);
     * console.log('Has more:', result.has_more);
     *
     * // Get messages after a specific sequence
     * const more = await agentService.getConversationMessages(
     *   'conv-123',
     *   'proj-123',
     *   100,
     *   result.last_sequence
     * );
     * ```
     */
    async getConversationMessages(
        conversationId: string,
        projectId: string,
        limit = 100,
        fromSequence?: number,
        beforeSequence?: number
    ): Promise<ConversationMessagesResponse> {
        const params: Record<string, string | number> = {
            project_id: projectId,
            limit,
        };
        if (fromSequence !== undefined) {
            params.from_sequence = fromSequence;
        }
        if (beforeSequence !== undefined) {
            params.before_sequence = beforeSequence;
        }

        const response = await api.get<{
            has_more?: boolean;
            first_sequence?: number | null;
            last_sequence?: number | null;
        } & Omit<ConversationMessagesResponse, 'has_more' | 'first_sequence' | 'last_sequence'>>(
            `/agent/conversations/${conversationId}/messages`,
            { params }
        );
        // Normalize optional fields to required fields with defaults
        return {
            ...response,
            has_more: response.has_more ?? false,
            first_sequence: response.first_sequence ?? null,
            last_sequence: response.last_sequence ?? null,
        };
    }

    /**
     * List available tools
     *
     * Retrieves the list of tools available to the Agent.
     * Useful for displaying tool capabilities in the UI.
     *
     * @returns Promise resolving to the list of available tools
     * @throws {ApiError} If the request fails
     *
     * @example
     * ```typescript
     * const tools = await agentService.listTools();
     * console.log('Available tools:', tools.tools);
     * ```
     */
    async listTools(): Promise<ToolsListResponse> {
        const response = await api.get<ToolsListResponse>("/agent/tools");
        return response;
    }

    /**
     * Respond to an environment variable request from the Agent
     *
     * Submits user-provided environment variable values in response to an
     * env_var_requested event. Uses WebSocket when connected for lower latency,
     * with HTTP fallback. The values are stored encrypted for future use.
     *
     * @param requestId - The request ID from the env_var_requested event
     * @param values - Key-value pairs of environment variable names and their values
     * @returns Promise resolving when the response is submitted
     * @throws {ApiError} If the request fails or request_id is invalid
     *
     * @example
     * ```typescript
     * await agentService.respondToEnvVar('req-123', {
     *   API_KEY: 'sk-xxx',
     *   API_SECRET: 'secret123'
     * });
     * ```
     */
    async respondToEnvVar(
        requestId: string,
        values: Record<string, string>
    ): Promise<void> {
        // Try WebSocket first for lower latency
        if (this.isConnected()) {
            const sent = this.send({
                type: "env_var_respond",
                request_id: requestId,
                values,
            });
            if (sent) {
                logger.debug("[AgentWS] Sent env_var_respond via WebSocket");
                return;
            }
        }
        // Fallback to HTTP
        await api.post<{ status: string }>("/agent/env-var/respond", {
            request_id: requestId,
            values,
        });
    }

    /**
     * Respond to a clarification request from the Agent
     *
     * Submits user's answer to a clarification question during planning phase.
     * Uses WebSocket when connected for lower latency, with HTTP fallback.
     *
     * @param requestId - The request ID from the clarification_asked event
     * @param answer - The user's answer (option ID or custom text)
     * @returns Promise resolving when the response is submitted
     * @throws {ApiError} If the request fails or request_id is invalid
     *
     * @example
     * ```typescript
     * await agentService.respondToClarification('req-123', 'option_a');
     * ```
     */
    async respondToClarification(
        requestId: string,
        answer: string
    ): Promise<void> {
        // Try WebSocket first for lower latency
        if (this.isConnected()) {
            const sent = this.send({
                type: "clarification_respond",
                request_id: requestId,
                answer,
            });
            if (sent) {
                logger.debug("[AgentWS] Sent clarification_respond via WebSocket");
                return;
            }
        }
        // Fallback to HTTP
        await api.post<{ status: string }>("/agent/clarification/respond", {
            request_id: requestId,
            response: answer,
        });
    }

    /**
     * Respond to a decision request from the Agent
     *
     * Submits user's decision at critical execution points.
     * Uses WebSocket when connected for lower latency, with HTTP fallback.
     *
     * @param requestId - The request ID from the decision_asked event
     * @param decision - The user's decision (option ID or custom text)
     * @returns Promise resolving when the response is submitted
     * @throws {ApiError} If the request fails or request_id is invalid
     *
     * @example
     * ```typescript
     * await agentService.respondToDecision('req-123', 'approved');
     * ```
     */
    async respondToDecision(
        requestId: string,
        decision: string
    ): Promise<void> {
        // Try WebSocket first for lower latency
        if (this.isConnected()) {
            const sent = this.send({
                type: "decision_respond",
                request_id: requestId,
                decision,
            });
            if (sent) {
                logger.debug("[AgentWS] Sent decision_respond via WebSocket");
                return;
            }
        }
        // Fallback to HTTP
        await api.post<{ status: string }>("/agent/decision/respond", {
            request_id: requestId,
            decision,
        });
    }

    /**
     * Get pending HITL (Human-In-The-Loop) requests for a conversation
     *
     * Retrieves any pending clarification, decision, or environment variable
     * requests that haven't been answered yet. This is useful for recovering
     * dialog state after page refresh.
     *
     * @param conversationId - The conversation ID
     * @param requestType - Optional filter by request type
     * @returns Promise resolving to pending HITL requests
     * @throws {ApiError} If conversation doesn't exist or user lacks access
     *
     * @example
     * ```typescript
     * // Get all pending requests
     * const pending = await agentService.getPendingHITLRequests('conv-123');
     *
     * // Get only clarification requests
     * const clarifications = await agentService.getPendingHITLRequests(
     *   'conv-123',
     *   'clarification'
     * );
     * ```
     */
    async getPendingHITLRequests(
        conversationId: string,
        requestType?: "clarification" | "decision" | "env_var"
    ): Promise<PendingHITLResponse> {
        const params = new URLSearchParams();
        if (requestType) {
            params.append("request_type", requestType);
        }
        const queryString = params.toString();
        const url = `/agent/conversations/${conversationId}/hitl/pending${queryString ? `?${queryString}` : ""}`;
        return await api.get<PendingHITLResponse>(url);
    }

    /**
     * Get execution history for a conversation
     *
     * Retrieves the execution history (plan steps) for a conversation,
     * with optional filtering by status and tool.
     *
     * @param conversationId - The conversation ID
     * @param projectId - The project ID for scoping
     * @param limit - Maximum number of execution records to return (default: 50)
     * @param statusFilter - Optional filter by execution status
     * @param toolFilter - Optional filter by tool name
     * @returns Promise resolving to execution history
     * @throws {ApiError} If conversation doesn't exist or user lacks access
     *
     * @example
     * ```typescript
     * // Get all execution history
     * const history = await agentService.getExecutionHistory('conv-123', 'proj-123');
     *
     * // Get only failed executions
     * const failed = await agentService.getExecutionHistory(
     *   'conv-123',
     *   'proj-123',
     *   50,
     *   'failed'
     * );
     * ```
     */
    async getExecutionHistory(
        conversationId: string,
        projectId: string,
        limit = 50,
        statusFilter?: string,
        toolFilter?: string
    ): Promise<ExecutionHistoryResponse> {
        const response = await api.get<ExecutionHistoryResponse>(
            `/agent/conversations/${conversationId}/execution`,
            {
                params: {
                    project_id: projectId,
                    limit,
                    status_filter: statusFilter,
                    tool_filter: toolFilter,
                },
            }
        );
        return response;
    }

    /**
     * Get execution statistics for a conversation
     *
     * Retrieves aggregated statistics about Agent execution in a conversation,
     * including step counts, success rates, and tool usage.
     *
     * @param conversationId - The conversation ID
     * @param projectId - The project ID for scoping
     * @returns Promise resolving to execution statistics
     * @throws {ApiError} If conversation doesn't exist or user lacks access
     *
     * @example
     * ```typescript
     * const stats = await agentService.getExecutionStats('conv-123', 'proj-123');
     * console.log('Total steps:', stats.total_steps);
     * console.log('Success rate:', stats.success_rate);
     * ```
     */
    async getExecutionStats(
        conversationId: string,
        projectId: string
    ): Promise<ExecutionStatsResponse> {
        const response = await api.get<ExecutionStatsResponse>(
            `/agent/conversations/${conversationId}/execution/stats`,
            {
                params: { project_id: projectId },
            }
        );
        return response;
    }

    /**
     * Get tool execution records for a conversation
     *
     * Retrieves detailed tool execution records for a conversation.
     *
     * @param conversationId - The conversation ID
     * @param projectId - The project ID for scoping
     * @param messageId - Optional filter by message ID
     * @param limit - Maximum number of records to return (default: 100)
     * @returns Promise resolving to tool execution records
     * @throws {ApiError} If conversation doesn't exist or user lacks access
     *
     * @example
     * ```typescript
     * // Get all tool executions
     * const executions = await agentService.getToolExecutions('conv-123', 'proj-123');
     *
     * // Get executions for a specific message
     * const messageExecutions = await agentService.getToolExecutions(
     *   'conv-123',
     *   'proj-123',
     *   'msg-456'
     * );
     * ```
     */
    async getToolExecutions(
        conversationId: string,
        projectId: string,
        messageId?: string,
        limit = 100
    ): Promise<ToolExecutionsResponse> {
        const params: Record<string, string | number> = {
            project_id: projectId,
            limit,
        };
        if (messageId) {
            params.message_id = messageId;
        }
        const response = await api.get<ToolExecutionsResponse>(
            `/agent/conversations/${conversationId}/tool-executions`,
            { params }
        );
        return response;
    }

    /**
     * Get conversation events for replay
     *
     * Retrieves raw conversation events for replay or debugging purposes.
     * Useful for reconstructing conversation state or analyzing execution flow.
     *
     * @param conversationId - The conversation ID
     * @param fromSequence - Starting sequence number (default: 0)
     * @param limit - Maximum events to return (default: 1000)
     * @returns Promise resolving to events array and pagination flag
     * @throws {ApiError} If conversation doesn't exist or user lacks access
     *
     * @example
     * ```typescript
     * // Get first 1000 events
     * const result = await agentService.getConversationEvents('conv-123');
     * console.log('Events:', result.events);
     * console.log('Has more:', result.has_more);
     * ```
     */
    async getConversationEvents(
        conversationId: string,
        fromSequence = 0,
        limit = 1000
    ): Promise<{
        events: Array<{ type: string; data: unknown; timestamp: string | null }>;
        has_more: boolean;
    }> {
        const response = await api.get<{
            events: Array<{ type: string; data: unknown; timestamp: string | null }>;
            has_more: boolean;
        }>(`/agent/conversations/${conversationId}/events`, {
            params: {
                from_sequence: fromSequence,
                limit,
            },
        });
        return response;
    }

    /**
     * Get execution status for a conversation
     *
     * Retrieves the current execution status of a conversation.
     * Useful for checking if the Agent is still running.
     *
     * @param conversationId - The conversation ID
     * @returns Promise resolving to execution status
     * @throws {ApiError} If conversation doesn't exist or user lacks access
     *
     * @example
     * ```typescript
     * const status = await agentService.getExecutionStatus('conv-123');
     * if (status.is_running) {
     *   console.log('Agent is still running');
     * } else {
     *   console.log('Last sequence:', status.last_sequence);
     * }
     *
     * // With recovery info
     * const statusWithRecovery = await agentService.getExecutionStatus('conv-123', true, 100);
     * if (statusWithRecovery.recovery?.can_recover) {
     *   console.log('Can recover', statusWithRecovery.recovery.missed_events_count, 'events');
     * }
     * ```
     */
    async getExecutionStatus(
        conversationId: string,
        includeRecovery: boolean = false,
        fromSequence: number = 0
    ): Promise<{
        is_running: boolean;
        last_sequence: number;
        current_message_id: string | null;
        conversation_id: string;
        recovery?: {
            can_recover: boolean;
            stream_exists: boolean;
            recovery_source: string;
            missed_events_count: number;
        };
    }> {
        const response = await api.get<{
            is_running: boolean;
            last_sequence: number;
            current_message_id: string | null;
            conversation_id: string;
            recovery?: {
                can_recover: boolean;
                stream_exists: boolean;
                recovery_source: string;
                missed_events_count: number;
            };
        }>(`/agent/conversations/${conversationId}/execution-status`, {
            params: {
                include_recovery: includeRecovery,
                from_sequence: fromSequence,
            },
        });
        return response;
    }

    /**
     * Record performance metric for an event type
     * @private
     */
    private recordEventMetric(eventType: string, timestamp: number): void {
        if (!this.performanceMetrics.has(eventType)) {
            this.performanceMetrics.set(eventType, []);
        }
        const metrics = this.performanceMetrics.get(eventType)!;
        metrics.push(timestamp);

        // Keep only the most recent samples
        if (metrics.length > this.MAX_METRICS_SAMPLES) {
            metrics.shift();
        }
    }

    /**
     * Get performance metrics for diagnostics
     *
     * Returns event timing statistics for monitoring WebSocket event latency.
     * Useful for debugging performance issues.
     *
     * @returns Record mapping event types to their count and last seen timestamp
     *
     * @example
     * ```typescript
     * const metrics = agentService.getPerformanceMetrics();
     * console.log('text_delta count:', metrics.text_delta.count);
     * console.log('text_delta last seen:', metrics.text_delta.lastSeen);
     * ```
     */
    getPerformanceMetrics(): Record<string, { count: number; lastSeen: number }> {
        const result: Record<string, { count: number; lastSeen: number }> = {};
        for (const [eventType, timestamps] of this.performanceMetrics.entries()) {
            result[eventType] = {
                count: timestamps.length,
                lastSeen: timestamps[timestamps.length - 1] || 0,
            };
        }
        return result;
    }

    /**
     * Clear performance metrics
     *
     * Resets all recorded performance metrics.
     *
     * @example
     * ```typescript
     * agentService.clearPerformanceMetrics();
     * console.log('Metrics cleared');
     * ```
     */
    clearPerformanceMetrics(): void {
        this.performanceMetrics.clear();
    }

    /**
     * Subscribe to Agent session status updates
     *
     * Registers a callback to receive real-time status updates for a project.
     * Only one status subscription is active at a time (new subscription replaces old).
     *
     * @param projectId - The project ID to monitor
     * @param callback - Function called when status updates arrive
     *
     * @example
     * ```typescript
     * agentService.subscribeStatus('proj-123', (status) => {
     *   console.log('Agent initialized:', status.is_initialized);
     *   console.log('Active chats:', status.active_chats);
     * });
     * ```
     */
    subscribeStatus(projectId: string, callback: (status: unknown) => void): void {
        // Unsubscribe from previous project if different
        if (this.statusSubscriber && this.statusSubscriber.projectId !== projectId) {
            this.unsubscribeStatus();
        }

        this.statusSubscriber = { projectId, callback };

        if (this.isConnected()) {
            this.send({
                type: "subscribe_status",
                project_id: projectId,
                polling_interval: 3000,
            });
            logger.debug(`[AgentWS] Subscribed to status updates for project: ${projectId}`);
        }
    }

    /**
     * Unsubscribe from Agent session status updates
     *
     * Stops receiving status updates and notifies the server.
     *
     * @example
     * ```typescript
     * agentService.unsubscribeStatus();
     * console.log('Status updates stopped');
     * ```
     */
    unsubscribeStatus(): void {
        if (this.statusSubscriber && this.isConnected()) {
            this.send({
                type: "unsubscribe_status",
                project_id: this.statusSubscriber.projectId,
            });
            logger.debug(`[AgentWS] Unsubscribed from status updates for project: ${this.statusSubscriber.projectId}`);
        }
        this.statusSubscriber = null;
    }

    /**
     * Subscribe to Agent lifecycle state changes for a project
     *
     * Registers a callback to receive real-time lifecycle state updates for a project.
     * Only one lifecycle subscription is active at a time (new subscription replaces old).
     *
     * @param projectId - The project ID to monitor
     * @param tenantId - The tenant ID for the project
     * @param callback - Function called when lifecycle state updates arrive
     *
     * @example
     * ```typescript
     * agentService.subscribeLifecycleState('proj-123', 'tenant-456', (state) => {
     *   console.log('Agent lifecycle state:', state.lifecycleState);
     *   console.log('Is initialized:', state.isInitialized);
     *   console.log('Tool count:', state.toolCount);
     * });
     * ```
     */
    subscribeLifecycleState(
        projectId: string,
        tenantId: string,
        callback: (state: LifecycleStateData) => void
    ): void {
        // Unsubscribe from previous project if different
        if (this.lifecycleStateSubscriber && this.lifecycleStateSubscriber.projectId !== projectId) {
            this.unsubscribeLifecycleState();
        }

        this.lifecycleStateSubscriber = { projectId, tenantId, callback };

        if (this.isConnected()) {
            this.send({
                type: "subscribe_lifecycle_state",
                project_id: projectId,
            });
            logger.debug(`[AgentWS] Subscribed to lifecycle state for project: ${projectId}`);
        }
    }

    /**
     * Unsubscribe from Agent lifecycle state changes
     *
     * Stops receiving lifecycle state updates and notifies the server.
     *
     * @example
     * ```typescript
     * agentService.unsubscribeLifecycleState();
     * console.log('Lifecycle state updates stopped');
     * ```
     */
    unsubscribeLifecycleState(): void {
        if (this.lifecycleStateSubscriber && this.isConnected()) {
            this.send({
                type: "unsubscribe_lifecycle_state",
                project_id: this.lifecycleStateSubscriber.projectId,
            });
            logger.debug(`[AgentWS] Unsubscribed from lifecycle state for project: ${this.lifecycleStateSubscriber.projectId}`);
        }
        this.lifecycleStateSubscriber = null;
    }
}

// Export singleton instance
export const agentService = new AgentServiceImpl();

// Export type for convenience
export type { AgentService };
