import { useEffect, useState, useRef, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { message, Form } from "antd";
import { useProjectStore } from "../stores/project";
import {
  useAgentStore,
  useTimelineEvents,
  useMessagesLoading,
  useHasEarlierMessages,
} from "../stores/agent";
import { agentService } from "../services/agentService";
import type { StarterTile } from "../components/agent/chat/IdleState";

export function useAgentChat() {
  const { projectId, conversation: conversationIdParam } = useParams<{
    projectId: string;
    conversation?: string;
  }>();
  const navigate = useNavigate();
  const { currentProject, projects, setCurrentProject } = useProjectStore();

  // Use unified timeline events (instead of deprecated useMessages)
  const timeline = useTimelineEvents();
  const messagesLoading = useMessagesLoading();
  const hasEarlierMessages = useHasEarlierMessages();

  const {
    conversations,
    currentConversation,
    listConversations,
    createConversation,
    setCurrentConversation,
    sendMessage,
    stopChat,
    isStreaming,
    currentWorkPlan,
    currentStepNumber,
    executionTimeline,
    toolExecutionHistory,
    matchedPattern,
    currentPlan,
    planModeStatus,
    planLoading,
    enterPlanMode,
    exitPlanMode,
    updatePlan,
    getPlanModeStatus,
    loadEarlierMessages,
    // New conversation pending state (to prevent race condition)
    isNewConversationPending,
  } = useAgentStore();

  // Local UI state
  const [inputValue, setInputValue] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [historySidebarOpen, setHistorySidebarOpen] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [showPlanEditor, setShowPlanEditor] = useState(false);
  const [showEnterPlanModal, setShowEnterPlanModal] = useState(false);
  const [planForm] = Form.useForm();

  // Refs
  const pendingSendRef = useRef<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const prevMessagesLoadingRef = useRef(messagesLoading);

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
      const currentConvId = useAgentStore.getState().currentConversation?.id;
      const streaming = useAgentStore.getState().isStreaming;
      if (streaming && currentConvId) {
        console.log("[useAgentChat] Cleanup: stopping chat for", currentConvId);
        agentService.stopChat(currentConvId);
      }
    };
  }, []);

  // Fetch Plan Mode status
  useEffect(() => {
    if (currentConversation?.id) {
      getPlanModeStatus(currentConversation.id);
    }
  }, [currentConversation?.id, getPlanModeStatus]);

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
    prevMessagesLoadingRef.current = messagesLoading;

    if (wasLoading && !messagesLoading && timeline.length > 0) {
      requestAnimationFrame(() => {
        scrollToBottom("auto");
      });
    }
  }, [messagesLoading, timeline.length, scrollToBottom]);

  // Project sync
  // Use ref to prevent duplicate calls and avoid dependency on listConversations
  const loadedProjectIdRef = useRef<string | null>(null);
  const listConversationsRef = useRef(listConversations);
  listConversationsRef.current = listConversations;
  
  useEffect(() => {
    if (projectId && loadedProjectIdRef.current !== projectId) {
      loadedProjectIdRef.current = projectId;
      listConversationsRef.current(projectId);
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
  // Also skip when a new conversation is pending (isNewConversationPending) to prevent
  // race condition where URL change after createConversation triggers setCurrentConversation
  // which would call getMessages and overwrite SSE-added messages.
  // Use useAgentStore.getState() to get the latest store value, not the stale
  // closure value from the previous render, to avoid calling setCurrentConversation
  // redundantly when creating a new conversation.
  useEffect(() => {
    if (
      conversationIdParam &&
      conversations.length > 0 &&
      !isStreaming &&
      !isNewConversationPending
    ) {
      const conversation = conversations.find(
        (c) => c.id === conversationIdParam
      );
      // Get fresh currentConversation from store to avoid stale closure
      const latestCurrentConversation =
        useAgentStore.getState().currentConversation;
      if (
        conversation &&
        latestCurrentConversation?.id !== conversationIdParam
      ) {
        setCurrentConversation(conversation);
      }
    }
  }, [
    conversationIdParam,
    conversations,
    setCurrentConversation,
    isStreaming,
    isNewConversationPending,
  ]);

  // Auto-select first conversation
  useEffect(() => {
    if (
      !conversationIdParam &&
      conversations.length > 0 &&
      !currentConversation
    ) {
      setCurrentConversation(conversations[0]);
      navigate(`/project/${projectId}/agent/${conversations[0].id}`, {
        replace: true,
      });
    }
  }, [
    conversations,
    currentConversation,
    conversationIdParam,
    setCurrentConversation,
    navigate,
    projectId,
  ]);

  // Handlers
  const handleSend = useCallback(
    async (message: string) => {
      if (pendingSendRef.current === message || isSending || isStreaming) {
        return;
      }

      pendingSendRef.current = message;
      setIsSending(true);

      try {
        if (!currentConversation) {
          const newConversation = await createConversation(projectId!);
          setCurrentConversation(newConversation, true);
          navigate(`/project/${projectId}/agent/${newConversation.id}`, {
            replace: true,
          });
          await sendMessage(
            newConversation.id,
            message,
            newConversation.project_id
          );
        } else {
          await sendMessage(
            currentConversation.id,
            message,
            currentConversation.project_id
          );
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
      currentConversation,
      projectId,
      createConversation,
      setCurrentConversation,
      sendMessage,
      navigate,
    ]
  );

  const handleStop = () => {
    if (currentConversation) {
      stopChat(currentConversation.id);
    }
  };

  const handleTileClick = (tile: StarterTile) => {
    handleSend(tile.title);
  };

  const handleSelectConversation = useCallback(
    (conversationId: string) => {
      const conversation = conversations.find((c) => c.id === conversationId);
      if (conversation) {
        setCurrentConversation(conversation);
        navigate(`/project/${projectId}/agent/${conversationId}`, {
          replace: true,
        });
      }
    },
    [conversations, setCurrentConversation, navigate, projectId]
  );

  const handleNewChat = useCallback(async () => {
    if (projectId) {
      const newConversation = await createConversation(projectId);
      setCurrentConversation(newConversation, true);
      navigate(`/project/${projectId}/agent/${newConversation.id}`, {
        replace: true,
      });
    }
  }, [projectId, createConversation, setCurrentConversation, navigate]);

  // Plan Mode Handlers
  const handleViewPlan = useCallback(() => {
    setShowPlanEditor(true);
  }, []);

  const handleExitPlanMode = useCallback(
    async (approve: boolean) => {
      if (currentConversation?.id && currentPlan?.id) {
        await exitPlanMode(currentConversation.id, currentPlan.id, approve);
        setShowPlanEditor(false);
      }
    },
    [currentConversation?.id, currentPlan?.id, exitPlanMode]
  );

  const handleUpdatePlan = useCallback(
    async (content: string) => {
      if (currentPlan?.id) {
        await updatePlan(currentPlan.id, { content });
      }
    },
    [currentPlan?.id, updatePlan]
  );

  const handleEnterPlanMode = useCallback(async () => {
    if (!currentConversation?.id) {
      message.warning("Please start or select a conversation first");
      return;
    }
    setShowEnterPlanModal(true);
  }, [currentConversation?.id]);

  const handleEnterPlanSubmit = useCallback(async () => {
    if (!currentConversation?.id) return;

    try {
      const values = await planForm.validateFields();
      await enterPlanMode(
        currentConversation.id,
        values.title,
        values.description
      );
      message.success("Entered Plan Mode successfully");
      setShowEnterPlanModal(false);
      planForm.resetFields();
    } catch (error: unknown) {
      const err = error as { errorFields?: unknown; message?: string };
      if (!err.errorFields) {
        message.error(err.message || "Failed to enter Plan Mode");
      }
    }
  }, [currentConversation?.id, enterPlanMode, planForm]);

  // Load earlier messages (backward pagination)
  const handleLoadEarlier = useCallback(async () => {
    if (!currentConversation?.id || !projectId) {
      console.log("[useAgentChat] Cannot load earlier: no conversation or project");
      return;
    }
    console.log("[useAgentChat] Loading earlier messages for", currentConversation.id);
    await loadEarlierMessages(currentConversation.id, projectId, 50);
  }, [currentConversation?.id, projectId, loadEarlierMessages]);

  return {
    // State
    projectId,
    currentConversation,
    conversations,
    timeline,
    messagesLoading,
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
    currentWorkPlan,
    currentStepNumber,
    executionTimeline,
    toolExecutionHistory,
    matchedPattern,
    currentPlan,
    planModeStatus,
    planLoading,

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
