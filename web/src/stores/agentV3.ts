import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";
import {
  Message,
  WorkPlan,
  Conversation,
  AgentStreamHandler,
  ToolCall,
  TimelineEvent,
  AgentEvent,
  ActEventData,
  ObserveEventData,
  UserMessageEvent,
  MessageEventData,
  ThoughtEventData,
  WorkPlanEventData,
  StepStartEventData,
  CompleteEventData,
} from "../types/agent";
import type { RenderMode } from "../components/agent/VirtualTimelineEventList";
import { agentService } from "../services/agentService";
import { agentEventReplayService } from "../services/agentEventReplayService";
import { planService } from "../services/planService";
import { v4 as uuidv4 } from "uuid";
import { appendSSEEventToTimeline } from "../utils/sseEventAdapter";

/**
 * Additional handlers that can be injected into sendMessage
 * for external integrations (e.g., sandbox tool detection)
 */
export interface AdditionalAgentHandlers {
  onAct?: (event: AgentEvent<ActEventData>) => void;
  onObserve?: (event: AgentEvent<ObserveEventData>) => void;
}

/**
 * Convert TimelineEvent[] to Message[] with execution details
 * Processes thought, act, observe events and attaches them to assistant messages
 */
function timelineToMessages(timeline: TimelineEvent[]): Message[] {
  const messages: Message[] = [];
  let pendingTimeline: TimelineItem[] = [];
  let pendingThoughts: string[] = [];
  let pendingToolCalls: ToolCall[] = [];
  let pendingToolResults: { tool_name: string; result?: any; error?: string }[] = [];

  for (const event of timeline) {
    switch (event.type) {
      case "user_message":
        // Flush any pending items (shouldn't happen normally)
        pendingTimeline = [];
        pendingThoughts = [];
        pendingToolCalls = [];
        pendingToolResults = [];
        
        messages.push({
          id: event.id,
          conversation_id: "",
          role: "user",
          content: (event as any).content || "",
          message_type: "text" as const,
          created_at: new Date(event.timestamp).toISOString(),
        });
        break;

      case "thought": {
        const thoughtContent = (event as any).content || (event as any).thought || "";
        if (thoughtContent) {
          pendingThoughts.push(thoughtContent);
          pendingTimeline.push({
            type: "thought",
            id: event.id,
            content: thoughtContent,
            timestamp: event.timestamp,
          });
        }
        break;
      }

      case "act": {
        const toolName = (event as any).toolName || (event as any).tool || "";
        const toolInput = (event as any).toolInput || (event as any).input || {};
        if (toolName) {
          pendingToolCalls.push({
            name: toolName,
            arguments: toolInput,
          });
          pendingTimeline.push({
            type: "tool_call",
            id: event.id,
            toolName: toolName,
            toolInput: toolInput,
            timestamp: event.timestamp,
          });
        }
        break;
      }

      case "observe": {
        const observeToolName = (event as any).toolName || (event as any).tool || "";
        const observeResult = (event as any).toolOutput || (event as any).result || "";
        const observeError = (event as any).isError ? (event as any).toolOutput : undefined;
        if (observeToolName) {
          pendingToolResults.push({
            tool_name: observeToolName,
            result: observeError ? undefined : observeResult,
            error: observeError,
          });
        }
        break;
      }

      case "assistant_message":
        // Create assistant message with accumulated execution data
        messages.push({
          id: event.id,
          conversation_id: "",
          role: "assistant",
          content: (event as any).content || "",
          message_type: "text" as const,
          created_at: new Date(event.timestamp).toISOString(),
          tool_calls: pendingToolCalls.length > 0 ? [...pendingToolCalls] : undefined,
          tool_results: pendingToolResults.length > 0 ? [...pendingToolResults] : undefined,
          metadata: {
            thoughts: pendingThoughts.length > 0 ? [...pendingThoughts] : undefined,
            timeline: pendingTimeline.length > 0 ? [...pendingTimeline] : undefined,
          },
        });
        // Reset pending items
        pendingTimeline = [];
        pendingThoughts = [];
        pendingToolCalls = [];
        pendingToolResults = [];
        break;

      // Ignore step_start, step_end, and other events for message display
      default:
        break;
    }
  }

  return messages;
}

interface TimelineItem {
  type: "thought" | "tool_call";
  id: string;
  content?: string;
  toolName?: string;
  toolInput?: any;
  timestamp: number;
}

interface AgentV3State {
  // Conversation State
  conversations: Conversation[];
  activeConversationId: string | null;

  // Timeline State (NEW: Primary data source for consistency)
  timeline: TimelineEvent[];

  // Messages State (Derived from timeline for backward compatibility)
  messages: Message[];
  isLoadingHistory: boolean;

  // Stream State
  isStreaming: boolean;
  streamStatus: "idle" | "connecting" | "streaming" | "error";
  error: string | null;

  // Agent Execution State
  agentState: "idle" | "thinking" | "acting" | "observing" | "awaiting_input";
  currentThought: string;
  activeToolCalls: Map<
    string,
    ToolCall & { status: "running" | "success" | "failed"; startTime: number }
  >;
  pendingToolsStack: string[]; // Track order of tool executions

  // Plan State
  workPlan: WorkPlan | null;
  isPlanMode: boolean;

  // UI State
  showPlanPanel: boolean;
  showHistorySidebar: boolean;
  renderMode: RenderMode;
  leftSidebarWidth: number;
  rightPanelWidth: number;

  // Interactivity
  pendingDecision: any; // Using any for brevity in this update
  doomLoopDetected: any;

  // Actions
  setActiveConversation: (id: string | null) => void;
  loadConversations: (projectId: string) => Promise<void>;
  loadMessages: (conversationId: string, projectId: string) => Promise<void>;
  createNewConversation: (projectId: string) => Promise<string | null>;
  sendMessage: (
    content: string,
    projectId: string,
    additionalHandlers?: AdditionalAgentHandlers
  ) => Promise<string | null>;
  deleteConversation: (
    conversationId: string,
    projectId: string
  ) => Promise<void>;
  abortStream: () => void;
  togglePlanPanel: () => void;
  toggleHistorySidebar: () => void;
  setRenderMode: (mode: RenderMode) => void;
  setLeftSidebarWidth: (width: number) => void;
  setRightPanelWidth: (width: number) => void;
  respondToDecision: (requestId: string, decision: string) => Promise<void>;
  togglePlanMode: () => Promise<void>;
  clearError: () => void;
}

// Helper to merge history messages
const processHistory = (messages: Message[]): Message[] => {
  const processed: Message[] = [];
  let currentAssistantMsg: Message | null = null;

  for (const msg of messages) {
    if (msg.role === "user") {
      if (currentAssistantMsg) {
        processed.push(currentAssistantMsg);
        currentAssistantMsg = null;
      }
      processed.push(msg);
    } else {
      // It's an assistant or system message, or a special type
      if (!currentAssistantMsg) {
        // Create new assistant message container
        currentAssistantMsg = {
          ...msg,
          role: "assistant",
          content: msg.message_type === "text" ? msg.content : "",
          tool_calls: msg.tool_calls || [],
          tool_results: msg.tool_results || [],
          metadata: {
            ...msg.metadata,
            thoughts: (msg.metadata?.thoughts as string[]) || [],
            timeline: (msg.metadata?.timeline as TimelineItem[]) || [],
          },
        };
      } else {
        // Merge into current
        if (msg.message_type === "text") {
          currentAssistantMsg.content += msg.content;
        }
        if (msg.tool_calls) {
          currentAssistantMsg.tool_calls = [
            ...(currentAssistantMsg.tool_calls || []),
            ...msg.tool_calls,
          ];
        }
        if (msg.tool_results) {
          currentAssistantMsg.tool_results = [
            ...(currentAssistantMsg.tool_results || []),
            ...msg.tool_results,
          ];
        }
      }

      // Handle specific types and build timeline
      const timeline =
        (currentAssistantMsg.metadata?.timeline as TimelineItem[]) || [];

      if (msg.message_type === "thought") {
        // Skip empty thoughts (REASONING_START events)
        if (!msg.content || msg.content.trim() === "") {
          continue;
        }
        const thoughts =
          (currentAssistantMsg.metadata?.thoughts as string[]) || [];
        currentAssistantMsg.metadata = {
          ...currentAssistantMsg.metadata,
          thoughts: [...thoughts, msg.content],
          timeline: [
            ...timeline,
            {
              type: "thought",
              id: msg.id,
              content: msg.content,
              timestamp: new Date(msg.created_at).getTime(),
            },
          ],
        };
      } else if (msg.message_type === "tool_call" && msg.tool_calls) {
        // Add tool calls to timeline
        const newTimelineItems = msg.tool_calls.map((call) => ({
          type: "tool_call" as const,
          id: uuidv4(), // We might not have ID here, generate one
          toolName: call.name,
          toolInput: call.arguments,
          timestamp: new Date(msg.created_at).getTime(),
        }));

        currentAssistantMsg.metadata = {
          ...currentAssistantMsg.metadata,
          timeline: [...timeline, ...newTimelineItems],
        };
      }
    }
  }
  if (currentAssistantMsg) {
    processed.push(currentAssistantMsg);
  }
  return processed;
};

export const useAgentV3Store = create<AgentV3State>()(
  devtools(
    persist(
      (set, get) => ({
        conversations: [],
        activeConversationId: null,

        // Timeline: Primary data source (stores raw events from API and streaming)
        timeline: [],

        // Messages: Derived from timeline (for backward compatibility)
        messages: [],
        isLoadingHistory: false,

        isStreaming: false,
        streamStatus: "idle",
        error: null,

        agentState: "idle",
        currentThought: "",
        activeToolCalls: new Map(),
        pendingToolsStack: [],

        workPlan: null,
        isPlanMode: false,

        showPlanPanel: false,
        showHistorySidebar: false,
        renderMode: "grouped",
        leftSidebarWidth: 280,
        rightPanelWidth: 400,

        pendingDecision: null,
        doomLoopDetected: null,

    setActiveConversation: (id) => set({ activeConversationId: id }),

    loadConversations: async (projectId) => {
      try {
        const conversations = await agentService.listConversations(projectId);
        set({ conversations });
      } catch (error) {
        console.error("Failed to list conversations", error);
      }
    },

    deleteConversation: async (conversationId, projectId) => {
      try {
        await agentService.deleteConversation(conversationId, projectId);
        // Remove from local state
        set((state) => ({
          conversations: state.conversations.filter(
            (c) => c.id !== conversationId
          ),
          // Clear active conversation if it was the deleted one
          activeConversationId:
            state.activeConversationId === conversationId
              ? null
              : state.activeConversationId,
          // Clear messages and timeline if the deleted conversation was active
          messages:
            state.activeConversationId === conversationId ? [] : state.messages,
          timeline:
            state.activeConversationId === conversationId ? [] : state.timeline,
        }));
      } catch (error) {
        console.error("Failed to delete conversation", error);
        set({ error: "Failed to delete conversation" });
      }
    },

    createNewConversation: async (projectId) => {
      try {
        const newConv = await agentService.createConversation({
          project_id: projectId,
          title: "New Conversation",
        });
        // Add to conversations list and set as active
        set((state) => ({
          conversations: [newConv, ...state.conversations],
          activeConversationId: newConv.id,
          // Clear messages and timeline for new conversation
          messages: [],
          timeline: [],
          currentThought: "",
          workPlan: null,
          agentState: "idle",
          isStreaming: false,
          error: null,
        }));
        return newConv.id;
      } catch (error) {
        console.error("Failed to create conversation", error);
        set({ error: "Failed to create conversation" });
        return null;
      }
    },

    loadMessages: async (conversationId, projectId) => {
      set({
        isLoadingHistory: true,
        timeline: [],      // Clear timeline
        messages: [],
        currentThought: "",
        workPlan: null,
        agentState: "idle",
      });
      try {
        const response = await agentService.getConversationMessages(
          conversationId,
          projectId
        );

        if (get().activeConversationId !== conversationId) {
          console.log("Conversation changed during load, ignoring result");
          return;
        }

        // Store the raw timeline (NEW)
        const processedMessages = processHistory(timelineToMessages(response.timeline));
        set({
          timeline: response.timeline,
          messages: processedMessages,
          isLoadingHistory: false,
        });

        try {
          const planStatus = await planService.getPlanModeStatus(
            conversationId
          );
          if (get().activeConversationId !== conversationId) return;
          set({ isPlanMode: planStatus.is_in_plan_mode });
        } catch (e) {
          console.warn("Failed to load plan status", e);
        }

        // Check execution status and replay events if needed
        try {
          const execStatus = await agentService.getExecutionStatus(
            conversationId
          );

          if (get().activeConversationId !== conversationId) return;

          if (execStatus.is_running && execStatus.last_sequence > 0) {
            console.log(
              `Conversation ${conversationId} is running, replaying events...`
            );

            // Create a temporary handler for replay
            const replayHandler: AgentStreamHandler = {
              onThought: (event) => {
                const thought = event.data.thought;
                // Skip empty thoughts (REASONING_START events)
                if (!thought || thought.trim() === "") return;
                set((state) => {
                  const lastMsg = state.messages[state.messages.length - 1];
                  if (!lastMsg || lastMsg.role !== "assistant") return state;
                  const thoughts =
                    (lastMsg.metadata?.thoughts as string[]) || [];
                  return {
                    currentThought: state.currentThought + "\n" + thought,
                    messages: state.messages.map((m, i) =>
                      i === state.messages.length - 1
                        ? {
                            ...m,
                            metadata: {
                              ...m.metadata,
                              thoughts: [...thoughts, thought],
                            },
                          }
                        : m
                    ),
                  };
                });
              },
              onWorkPlan: (event) => {
                set({
                  workPlan: {
                    id: event.data.plan_id,
                    conversation_id: event.data.conversation_id,
                    status: event.data.status,
                    steps: event.data.steps.map((s: any) => ({
                      step_number: s.step_number,
                      description: s.description,
                      thought_prompt: "",
                      required_tools: [],
                      expected_output: s.expected_output,
                      dependencies: [],
                    })),
                    current_step_index: event.data.current_step,
                    created_at: new Date().toISOString(),
                  },
                });
              },
              onStepStart: (event) => {
                set((state) => ({
                  workPlan: state.workPlan
                    ? {
                        ...state.workPlan,
                        current_step_index: event.data.current_step,
                      }
                    : null,
                  agentState: "acting",
                }));
              },
              onAct: (event) => {
                set((state) => {
                  const toolName = event.data.tool_name;
                  const startTime = Date.now();
                  const newCall: ToolCall & {
                    status: "running";
                    startTime: number;
                  } = {
                    name: toolName,
                    arguments: event.data.tool_input,
                    status: "running",
                    startTime,
                  };
                  const newMap = new Map(state.activeToolCalls);
                  newMap.set(toolName, newCall);
                  return { activeToolCalls: newMap, agentState: "acting" };
                });
              },
              onObserve: (_event) => {
                set((state) => {
                  const stack = [...state.pendingToolsStack];
                  stack.pop(); // Remove processed tool from stack
                  return { pendingToolsStack: stack, agentState: "observing" };
                });
              },
              onComplete: () => {
                set({
                  isStreaming: false,
                  agentState: "idle",
                  activeToolCalls: new Map(),
                });
              },
              onError: (event) => {
                set({ error: event.data.message });
              },
            };

            // Replay events
            await agentEventReplayService.replayEvents(
              conversationId,
              replayHandler,
              0
            );

            set({ isStreaming: true, agentState: "thinking" });
          }
        } catch (e) {
          console.warn("Failed to check execution status or replay events", e);
        }

        set({ isLoadingHistory: false });
      } catch (error) {
        if (get().activeConversationId !== conversationId) return;
        console.error("Failed to load messages", error);
        set({ isLoadingHistory: false });
      }
    },

    sendMessage: async (content, projectId, additionalHandlers) => {
      const { activeConversationId, messages, timeline } = get();

      let conversationId = activeConversationId;
      let isNewConversation = false;

      if (!conversationId) {
        try {
          const newConv = await agentService.createConversation({
            project_id: projectId,
            title: content.slice(0, 30) + "...",
          });
          conversationId = newConv.id;
          isNewConversation = true;
          set({
            activeConversationId: conversationId,
            conversations: [newConv, ...get().conversations],
          });
        } catch (_error) {
          set({ error: "Failed to create conversation" });
          return null;
        }
      }

      const userMsgId = uuidv4();
      const userMsg: Message = {
        id: userMsgId,
        conversation_id: conversationId!,
        role: "user",
        content,
        message_type: "text",
        created_at: new Date().toISOString(),
      };

      const assistantMsgId = uuidv4();
      const assistantMsg: Message = {
        id: assistantMsgId,
        conversation_id: conversationId!,
        role: "assistant",
        content: "",
        message_type: "text",
        created_at: new Date().toISOString(),
        metadata: { thoughts: [], tool_executions: {}, timeline: [] }, // Initialize metadata
      };

      // Create user message TimelineEvent and append to timeline
      const userMessageEvent: UserMessageEvent = {
        id: userMsgId,
        type: "user_message",
        sequenceNumber: timeline.length > 0 ? timeline[timeline.length - 1].sequenceNumber + 1 : 1,
        timestamp: Date.now(),
        content,
        role: "user",
      };

      set({
        messages: [...messages, userMsg, assistantMsg],
        timeline: [...timeline, userMessageEvent],
        isStreaming: true,
        streamStatus: "connecting",
        error: null,
        currentThought: "",
        activeToolCalls: new Map(),
        pendingToolsStack: [],
        agentState: "thinking",
      });

      // Define handler first (needed for both new and existing conversations)
      const handler: AgentStreamHandler = {
        onMessage: (_event) => {},
        onThought: (event) => {
          set((state) => {
            // Append thought event to timeline using SSE adapter
            const thoughtEvent: AgentEvent<ThoughtEventData> = event as AgentEvent<ThoughtEventData>;
            const updatedTimeline = appendSSEEventToTimeline(state.timeline, thoughtEvent);

            const newThought = event.data.thought;
            // Skip empty thoughts (REASONING_START events) - only process complete thoughts
            if (!newThought || newThought.trim() === "") {
              return { agentState: "thinking", timeline: updatedTimeline };
            }
            const newMessages = state.messages.map((m) => {
              if (m.id === assistantMsgId) {
                const thoughts = (m.metadata?.thoughts as string[]) || [];
                const msgTimeline = (m.metadata?.timeline as TimelineItem[]) || [];
                return {
                  ...m,
                  metadata: {
                    ...m.metadata,
                    thoughts: [...thoughts, newThought],
                    timeline: [
                      ...msgTimeline,
                      {
                        type: "thought",
                        id: uuidv4(),
                        content: newThought,
                        timestamp: Date.now(),
                      },
                    ],
                  },
                };
              }
              return m;
            });
            return {
              currentThought: state.currentThought + "\n" + newThought,
              agentState: "thinking",
              messages: newMessages,
              timeline: updatedTimeline,
            };
          });
        },
        onWorkPlan: (event) => {
          set((state) => {
            // Append work_plan event to timeline using SSE adapter
            const workPlanEvent: AgentEvent<WorkPlanEventData> = event as AgentEvent<WorkPlanEventData>;
            const updatedTimeline = appendSSEEventToTimeline(state.timeline, workPlanEvent);

            return {
              workPlan: {
                id: event.data.plan_id,
                conversation_id: event.data.conversation_id,
                status: event.data.status,
                steps: event.data.steps.map((s) => ({
                  step_number: s.step_number,
                  description: s.description,
                  thought_prompt: "",
                  required_tools: [],
                  expected_output: s.expected_output,
                  dependencies: [],
                })),
                current_step_index: event.data.current_step,
                created_at: new Date().toISOString(),
              },
              timeline: updatedTimeline,
            };
          });
        },
        onStepStart: (event) => {
          set((state) => {
            // Append step_start event to timeline using SSE adapter
            const stepStartEvent: AgentEvent<StepStartEventData> = event as AgentEvent<StepStartEventData>;
            const updatedTimeline = appendSSEEventToTimeline(state.timeline, stepStartEvent);

            if (!state.workPlan) {
              return { timeline: updatedTimeline };
            }
            const newPlan = { ...state.workPlan };
            newPlan.current_step_index = event.data.current_step;
            return { workPlan: newPlan, agentState: "acting", timeline: updatedTimeline };
          });
        },
        onStepEnd: (_event) => {},
        onAct: (event) => {
          set((state) => {
            // Append act event to timeline using SSE adapter
            const updatedTimeline = appendSSEEventToTimeline(state.timeline, event);

            const toolName = event.data.tool_name;
            const startTime = Date.now();

            const newCall: ToolCall & { status: "running"; startTime: number } =
              {
                name: toolName,
                arguments: event.data.tool_input,
                status: "running",
                startTime,
              };

            const newMap = new Map(state.activeToolCalls);
            newMap.set(toolName, newCall);

            const newStack = [...state.pendingToolsStack, toolName];

            const newMessages = state.messages.map((m) => {
              if (m.id === assistantMsgId) {
                const executions = (m.metadata?.tool_executions ||
                  {}) as Record<
                  string,
                  { startTime?: number; endTime?: number; duration?: number }
                >;
                const msgTimeline = (m.metadata?.timeline as TimelineItem[]) || [];
                return {
                  ...m,
                  tool_calls: [
                    ...(m.tool_calls || []),
                    { name: toolName, arguments: event.data.tool_input },
                  ],
                  metadata: {
                    ...m.metadata,
                    tool_executions: {
                      ...executions,
                      [toolName]: { startTime },
                    },
                    timeline: [
                      ...msgTimeline,
                      {
                        type: "tool_call",
                        id: uuidv4(),
                        toolName: toolName,
                        toolInput: event.data.tool_input,
                        timestamp: startTime,
                      },
                    ],
                  },
                };
              }
              return m;
            });

            return {
              activeToolCalls: newMap,
              pendingToolsStack: newStack,
              messages: newMessages,
              agentState: "acting",
              timeline: updatedTimeline,
            };
          });

          // Call additional handler if provided
          additionalHandlers?.onAct?.(event);
        },
        onObserve: (event) => {
          set((state) => {
            // Append observe event to timeline using SSE adapter
            const updatedTimeline = appendSSEEventToTimeline(state.timeline, event);

            const stack = [...state.pendingToolsStack];
            const toolName = stack.pop() || "unknown";
            const endTime = Date.now();

            const newMessages = state.messages.map((m) => {
              if (m.id === assistantMsgId) {
                const executions = (m.metadata?.tool_executions ||
                  {}) as Record<
                  string,
                  { startTime?: number; endTime?: number; duration?: number }
                >;
                const startInfo = executions[toolName] || {};

                return {
                  ...m,
                  tool_results: [
                    ...(m.tool_results || []),
                    { tool_name: toolName, result: event.data.observation },
                  ],
                  metadata: {
                    ...m.metadata,
                    tool_executions: {
                      ...executions,
                      [toolName]: {
                        ...startInfo,
                        endTime,
                        duration: endTime - (startInfo.startTime || endTime),
                      },
                    },
                  },
                };
              }
              return m;
            });

            return {
              messages: newMessages,
              pendingToolsStack: stack,
              agentState: "observing",
              timeline: updatedTimeline,
            };
          });

          // Call additional handler if provided
          additionalHandlers?.onObserve?.(event);
        },
        onTextDelta: (event) => {
          set((state) => {
            const newMessages = state.messages.map((m) => {
              if (m.id === assistantMsgId) {
                return { ...m, content: m.content + event.data.delta };
              }
              return m;
            });
            return { messages: newMessages, streamStatus: "streaming" };
          });
        },
        onDecisionAsked: (event) => {
          set({ pendingDecision: event.data, agentState: "awaiting_input" });
        },
        onDoomLoopDetected: (event) => {
          set({ doomLoopDetected: event.data });
        },
        onTitleGenerated: (event) => {
          const data = event.data as {
            conversation_id: string;
            title: string;
            generated_at: string;
            message_id?: string;
            generated_by?: string;
          };
          console.log("[AgentV3] Title generated event:", data);

          set((state) => {
            // Update in conversations list
            const updatedList = state.conversations.map((c) =>
              c.id === data.conversation_id ? { ...c, title: data.title } : c
            );
            return { conversations: updatedList };
          });
        },
        onComplete: (event) => {
          set((state) => {
            // Append complete event to timeline using SSE adapter
            const completeEvent: AgentEvent<CompleteEventData> = event as AgentEvent<CompleteEventData>;
            const updatedTimeline = appendSSEEventToTimeline(state.timeline, completeEvent);

            // 更新助手消息内容（如果 complete 事件包含内容）和 trace URL
            const newMessages = state.messages.map((m) => {
              if (m.id === assistantMsgId) {
                return {
                  ...m,
                  content: event?.data?.content || m.content,
                  traceUrl: event?.data?.trace_url || m.traceUrl,
                };
              }
              return m;
            });
            return {
              messages: newMessages,
              timeline: updatedTimeline,
              isStreaming: false,
              streamStatus: "idle",
              agentState: "idle",
              activeToolCalls: new Map(),
              pendingToolsStack: [],
            };
          });
        },
        onError: (event) => {
          set({
            error: event.data.message,
            isStreaming: false,
            streamStatus: "error",
          });
        },
        onClose: () => {
          set({ isStreaming: false, streamStatus: "idle" });
        },
      };

      // For new conversations, return ID immediately and start stream in background
      // This allows the UI to navigate to the conversation URL right away
      if (isNewConversation) {
        agentService
          .chat(
            {
              conversation_id: conversationId!,
              message: content,
              project_id: projectId,
            },
            handler
          )
          .catch(() => {
            set({
              error: "Failed to connect to chat stream",
              isStreaming: false,
              streamStatus: "error",
            });
          });
        return conversationId!;
      }

      // For existing conversations, wait for stream to complete
      try {
        await agentService.chat(
          {
            conversation_id: conversationId!,
            message: content,
            project_id: projectId,
          },
          handler
        );
        return conversationId!;
      } catch (_e) {
        set({
          error: "Failed to connect to chat stream",
          isStreaming: false,
          streamStatus: "error",
        });
        return null;
      }
    },

    abortStream: () => {
      const { activeConversationId } = get();
      if (activeConversationId) {
        agentService.stopChat(activeConversationId);
        set({ isStreaming: false, streamStatus: "idle" });
      }
    },

    respondToDecision: async (requestId, decision) => {
      console.log("Responding to decision", requestId, decision);
      set({ pendingDecision: null, agentState: "thinking" });
    },

    togglePlanPanel: () =>
      set((state) => ({ showPlanPanel: !state.showPlanPanel })),
    toggleHistorySidebar: () =>
      set((state) => ({ showHistorySidebar: !state.showHistorySidebar })),

    setRenderMode: (mode: RenderMode) => set({ renderMode: mode }),

    setLeftSidebarWidth: (width: number) => set({ leftSidebarWidth: width }),
    setRightPanelWidth: (width: number) => set({ rightPanelWidth: width }),

    togglePlanMode: async () => {
      const { isPlanMode, activeConversationId } = get();
      if (!activeConversationId) return;

      try {
        if (isPlanMode) {
          const status = await planService.getPlanModeStatus(
            activeConversationId
          );
          if (status.current_plan_id) {
            await planService.exitPlanMode({
              conversation_id: activeConversationId,
              plan_id: status.current_plan_id,
            });
          }
          set({ isPlanMode: false });
        } else {
          await planService.enterPlanMode({
            conversation_id: activeConversationId,
            title: "Plan",
          });
          set({ isPlanMode: true });
        }
      } catch (error) {
        console.error("Failed to toggle plan mode", error);
      }
    },

    clearError: () => set({ error: null }),
  }),
  {
    name: 'agent-v3-storage',
    partialize: (state) => ({
      // Only persist UI preferences, not conversation/message data
      renderMode: state.renderMode,
      showHistorySidebar: state.showHistorySidebar,
      leftSidebarWidth: state.leftSidebarWidth,
      rightPanelWidth: state.rightPanelWidth,
    }),
  }))
);
