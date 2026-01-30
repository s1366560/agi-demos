import { useEffect, useState, useRef, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { message, Form } from "antd";
import { useProjectStore } from "../stores/project";
import { useAgentV3Store } from "../stores/agentV3";
import { agentService } from "../services/agentService";
import type { StarterTile } from "../components/agent/chat/IdleState";

export function useAgentChat() {
  const { projectId, conversation: conversationIdParam } = useParams<{
    projectId: string;
    conversation?: string;
  }>();
  const navigate = useNavigate();
  const { currentProject, projects, setCurrentProject } = useProjectStore();

  // Get state directly from agentV3 store
  const {
    conversations,
    activeConversationId,
    timeline,
    isLoadingHistory,
    isStreaming,
    workPlan,
    executionPlan,
    isPlanMode,
    loadConversations,
    loadMessages,
    setActiveConversation,
    createNewConversation,
    sendMessage,
    abortStream,
    togglePlanMode,
  } = useAgentV3Store();

  // Local UI state
  const [inputValue, setInputValue] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [historySidebarOpen, setHistorySidebarOpen] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [showPlanEditor, setShowPlanEditor] = useState(false);
  const [showEnterPlanModal, setShowEnterPlanModal] = useState(false);
  const [planForm] = Form.useForm();
  
  // Note: respondToDecision, deleteConversation, clearError, error, 
  // pendingDecision, doomLoopDetected, streamStatus are available in store but not used currently
  
  // Get togglePlanPanel from store for handleViewPlan
  const togglePlanPanel = useAgentV3Store((state) => state.togglePlanPanel);

  // Refs
  const pendingSendRef = useRef<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const prevMessagesLoadingRef = useRef(isLoadingHistory);

  // WebSocket connection management
  useEffect(() => {
    // Connect to WebSocket when component mounts
    if (!agentService.isConnected()) {
      agentService.connect().catch((err) => {
        console.error("[useAgentChat] Failed to connect WebSocket:", err);
      });
    }

    // Cleanup on unmount - stop any active chat but keep connection alive
    // (connection is shared across the app)
    return () => {
      const currentConvId = useAgentV3Store.getState().activeConversationId;
      const streaming = useAgentV3Store.getState().isStreaming;
      if (streaming && currentConvId) {
        console.log("[useAgentChat] Cleanup: stopping chat for", currentConvId);
        agentService.stopChat(currentConvId);
      }
    };
  }, []);

  // Fetch Plan Mode status
  useEffect(() => {
    if (activeConversationId) {
      // Plan mode status is loaded in loadMessages
    }
  }, [activeConversationId]);

  // Scroll logic
  const scrollToBottom = useCallback((behavior: ScrollBehavior = "smooth") => {
    messagesEndRef.current?.scrollIntoView({ behavior, block: "end" });
  }, []);

  useEffect(() => {
    if (timeline.length > 0 || isStreaming) {
      scrollToBottom("smooth");
    }
  }, [timeline.length, isStreaming, scrollToBottom]);

  useEffect(() => {
    const wasLoading = prevMessagesLoadingRef.current;
    prevMessagesLoadingRef.current = isLoadingHistory;

    if (wasLoading && !isLoadingHistory && timeline.length > 0) {
      requestAnimationFrame(() => {
        scrollToBottom("auto");
      });
    }
  }, [isLoadingHistory, timeline.length, scrollToBottom]);

  // Project sync
  // Use ref to prevent duplicate calls and avoid dependency on listConversations
  const loadedProjectIdRef = useRef<string | null>(null);
  const loadConversationsRef = useRef(loadConversations);
  loadConversationsRef.current = loadConversations;
  
  useEffect(() => {
    if (projectId && loadedProjectIdRef.current !== projectId) {
      loadedProjectIdRef.current = projectId;
      loadConversationsRef.current(projectId);
      const project = projects.find((p) => p.id === projectId);
      if (project && currentProject?.id !== projectId) {
        setCurrentProject(project);
      }
    }
  // ONLY depend on projectId, NOT listConversations
  }, [projectId]);

  // URL param sync
  // Skip during streaming to avoid race condition where getMessages overwrites
  // messages added by SSE events (addMessage) during new conversation creation.
  useEffect(() => {
    if (
      conversationIdParam &&
      conversations.length > 0 &&
      !isStreaming
    ) {
      const conversation = conversations.find(
        (c) => c.id === conversationIdParam
      );
      // Get fresh activeConversationId from store to avoid stale closure
      const latestActiveId = useAgentV3Store.getState().activeConversationId;
      if (
        conversation &&
        latestActiveId !== conversationIdParam
      ) {
        setActiveConversation(conversationIdParam);
        loadMessages(conversationIdParam, projectId!);
      }
    }
  }, [
    conversationIdParam,
    conversations,
    setActiveConversation,
    isStreaming,
    projectId,
    loadMessages,
  ]);

  // Auto-select first conversation
  useEffect(() => {
    if (
      !conversationIdParam &&
      conversations.length > 0 &&
      !activeConversationId
    ) {
      const firstConv = conversations[0];
      setActiveConversation(firstConv.id);
      loadMessages(firstConv.id, projectId!);
      navigate(`/project/${projectId}/agent/${firstConv.id}`, {
        replace: true,
      });
    }
  }, [
    conversations,
    activeConversationId,
    conversationIdParam,
    setActiveConversation,
    navigate,
    projectId,
    loadMessages,
  ]);

  // Handlers
  const handleSend = useCallback(
    async (messageText: string) => {
      if (pendingSendRef.current === messageText || isSending || isStreaming) {
        return;
      }

      pendingSendRef.current = messageText;
      setIsSending(true);

      try {
        if (!activeConversationId) {
          const newId = await createNewConversation(projectId!);
          if (newId) {
            navigate(`/project/${projectId}/agent/${newId}`, {
              replace: true,
            });
            await sendMessage(messageText, projectId!);
          }
        } else {
          await sendMessage(messageText, projectId!);
        }
      } finally {
        setIsSending(false);
        setTimeout(() => {
          pendingSendRef.current = null;
        }, 500);
      }
    },
    [
      isSending,
      isStreaming,
      activeConversationId,
      projectId,
      createNewConversation,
      sendMessage,
      navigate,
    ]
  );

  const handleStop = () => {
    abortStream();
  };

  const handleTileClick = (tile: StarterTile) => {
    handleSend(tile.title);
  };

  const handleSelectConversation = useCallback(
    (conversationId: string) => {
      setActiveConversation(conversationId);
      loadMessages(conversationId, projectId!);
      navigate(`/project/${projectId}/agent/${conversationId}`, {
        replace: true,
      });
    },
    [setActiveConversation, navigate, projectId, loadMessages]
  );

  const handleNewChat = useCallback(async () => {
    if (projectId) {
      const newId = await createNewConversation(projectId);
      if (newId) {
        navigate(`/project/${projectId}/agent/${newId}`, {
          replace: true,
        });
      }
    }
  }, [projectId, createNewConversation, navigate]);

  // Plan Mode Handlers
  const handleViewPlan = useCallback(() => {
    setShowPlanEditor(true);
    togglePlanPanel();
  }, [togglePlanPanel]);

  const handleExitPlanMode = useCallback(
    async (_approve: boolean) => {
      // Exit plan mode via toggle
      await togglePlanMode();
      setShowPlanEditor(false);
    },
    [togglePlanMode]
  );

  const handleUpdatePlan = useCallback(
    async (_content: string) => {
      // Update plan functionality if needed
    },
    []
  );

  const handleEnterPlanMode = useCallback(async () => {
    if (!activeConversationId) {
      message.warning("Please start or select a conversation first");
      return;
    }
    setShowEnterPlanModal(true);
  }, [activeConversationId]);

  const handleEnterPlanSubmit = useCallback(async () => {
    if (!activeConversationId) return;

    try {
      await planForm.validateFields();
      await togglePlanMode();
      message.success("Entered Plan Mode successfully");
      setShowEnterPlanModal(false);
      planForm.resetFields();
    } catch (error: unknown) {
      const err = error as { errorFields?: unknown; message?: string };
      if (!err.errorFields) {
        message.error(err.message || "Failed to enter Plan Mode");
      }
    }
  }, [activeConversationId, togglePlanMode, planForm]);

  // Load earlier messages (backward pagination) - not implemented in v3
  const handleLoadEarlier = useCallback(async () => {
    console.log("[useAgentChat] Load earlier not implemented in v3");
  }, []);

  // Derive current conversation object
  const currentConversation = conversations.find(c => c.id === activeConversationId) || null;

  // Derive hasEarlierMessages from messages
  const hasEarlierMessages = false; // Not implemented in v3

  return {
    // State
    projectId,
    currentConversation,
    conversations,
    timeline,
    messagesLoading: isLoadingHistory,
    isStreaming,
    inputValue,
    setInputValue,
    historySidebarOpen,
    setHistorySidebarOpen,
    searchQuery,
    setSearchQuery,
    showPlanEditor,
    setShowPlanEditor,
    showEnterPlanModal,
    setShowEnterPlanModal,
    planForm,

    // Store State
    currentWorkPlan: workPlan,
    currentStepNumber: workPlan?.current_step_index ?? null,
    executionTimeline: [], // Not in v3
    toolExecutionHistory: [], // Not in v3
    matchedPattern: null, // Not in v3
    currentPlan: executionPlan,
    planModeStatus: isPlanMode ? { is_in_plan_mode: true } : null,
    planLoading: false,

    // Pagination state
    hasEarlierMessages,

    // Refs
    messagesEndRef,
    scrollContainerRef,

    // Handlers
    handleSend,
    handleStop,
    handleTileClick,
    handleSelectConversation,
    handleNewChat,
    handleViewPlan,
    handleExitPlanMode,
    handleUpdatePlan,
    handleEnterPlanMode,
    handleEnterPlanSubmit,
    handleLoadEarlier,
  };
}
