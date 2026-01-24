/**
 * Conversation Sidebar
 *
 * Sidebar component displaying conversation list with search and filters.
 */

import { useState, useEffect, useMemo } from "react";
import {
  PlusOutlined,
  SearchOutlined,
  DeleteOutlined,
  EditOutlined,
  CheckOutlined,
  CloseOutlined,
  MessageOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import {
  useConversations,
  useCurrentConversation,
  useAgentV2Store,
} from "../../../stores/agentV2";
import type { Conversation } from "../../../types/agentV2";

export function ConversationSidebar() {
  const conversations = useConversations();
  const currentConversation = useCurrentConversation();
  const {
    sidebarOpen,
    searchQuery,
    setSearchQuery,
    filterStatus,
    setFilterStatus,
    createConversation,
    selectConversation,
    deleteConversation,
    updateConversationTitle,
    generateConversationTitle,
  } = useAgentV2Store();

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");

  // Filter conversations based on search query and status
  const filteredConversations = useMemo(() => {
    let filtered = conversations;

    // Status filter
    if (filterStatus !== "all") {
      filtered = filtered.filter((c) => c.status === filterStatus);
    }

    // Search filter
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter((c) => c.title.toLowerCase().includes(query));
    }

    // Sort by updated_at (newest first)
    return filtered.sort(
      (a, b) =>
        new Date(b.updated_at || b.created_at).getTime() -
        new Date(a.updated_at || a.created_at).getTime()
    );
  }, [conversations, searchQuery, filterStatus]);

  // Get current project from URL
  const projectId = useMemo(() => {
    const match = window.location.pathname.match(/\/project\/([^\/]+)/);
    return match ? match[1] : null;
  }, []);

  // Load conversations on mount
  useEffect(() => {
    if (projectId) {
      useAgentV2Store.getState().listConversations(projectId);
    }
  }, [projectId]);

  const handleCreateNew = async () => {
    if (!projectId) return;
    try {
      const conversation = await createConversation(projectId);
      selectConversation(conversation);
      setEditingId(conversation.id);
      setEditTitle(conversation.title);
    } catch (error) {
      console.error("Failed to create conversation:", error);
    }
  };

  const handleSelectConversation = (conversation: Conversation) => {
    selectConversation(conversation);
  };

  const handleDeleteConversation = async (
    e: React.MouseEvent,
    conversation: Conversation
  ) => {
    e.stopPropagation();
    if (!projectId) return;

    if (window.confirm("Delete this conversation?")) {
      try {
        await deleteConversation(conversation.id, projectId);
        if (currentConversation?.id === conversation.id) {
          selectConversation(null);
        }
      } catch (error) {
        console.error("Failed to delete conversation:", error);
      }
    }
  };

  const handleStartEdit = (e: React.MouseEvent, conversation: Conversation) => {
    e.stopPropagation();
    setEditingId(conversation.id);
    setEditTitle(conversation.title);
  };

  const handleSaveTitle = async (
    e: React.MouseEvent,
    conversation: Conversation
  ) => {
    e.stopPropagation();
    if (!projectId || !editTitle.trim()) return;

    try {
      await updateConversationTitle(
        conversation.id,
        projectId,
        editTitle.trim()
      );
      setEditingId(null);
      setEditTitle("");
    } catch (error) {
      console.error("Failed to update title:", error);
    }
  };

  const handleCancelEdit = (e?: React.MouseEvent | React.KeyboardEvent) => {
    e?.stopPropagation();
    setEditingId(null);
    setEditTitle("");
  };

  const handleGenerateTitle = async (
    e: React.MouseEvent,
    conversation: Conversation
  ) => {
    e.stopPropagation();
    if (!projectId) return;

    try {
      await generateConversationTitle(conversation.id, projectId);
    } catch (error) {
      console.error("Failed to generate title:", error);
    }
  };

  if (!sidebarOpen) {
    return null;
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="p-4 border-b border-gray-200 dark:border-gray-800">
        <button
          onClick={handleCreateNew}
          className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors font-medium"
        >
          <PlusOutlined />
          New Conversation
        </button>
      </div>

      {/* Search */}
      <div className="p-4">
        <div className="relative">
          <SearchOutlined className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="Search conversations..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-10 pr-4 py-2 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition-all"
          />
        </div>

        {/* Status Filter */}
        <div className="flex gap-2 mt-3">
          <button
            onClick={() => setFilterStatus("all")}
            className={`px-3 py-1 text-sm rounded-full transition-colors ${
              filterStatus === "all"
                ? "bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300"
                : "text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800"
            }`}
          >
            All
          </button>
          <button
            onClick={() => setFilterStatus("active")}
            className={`px-3 py-1 text-sm rounded-full transition-colors ${
              filterStatus === "active"
                ? "bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300"
                : "text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800"
            }`}
          >
            Active
          </button>
          <button
            onClick={() => setFilterStatus("archived")}
            className={`px-3 py-1 text-sm rounded-full transition-colors ${
              filterStatus === "archived"
                ? "bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300"
                : "text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800"
            }`}
          >
            Archived
          </button>
        </div>
      </div>

      {/* Conversation List */}
      <div className="flex-1 overflow-y-auto px-4 pb-4">
        {filteredConversations.length === 0 ? (
          <div className="text-center py-8 text-gray-500 dark:text-gray-400">
            <MessageOutlined className="w-12 h-12 mx-auto mb-2 opacity-50" />
            <p className="text-sm">
              {searchQuery ? "No conversations found" : "No conversations yet"}
            </p>
          </div>
        ) : (
          <ul className="space-y-2">
            {filteredConversations.map((conversation) => (
              <li key={conversation.id}>
                <div
                  onClick={() => handleSelectConversation(conversation)}
                  className={`group p-3 rounded-lg cursor-pointer transition-colors ${
                    currentConversation?.id === conversation.id
                      ? "bg-blue-50 dark:bg-blue-900/30 border border-blue-200 dark:border-blue-800"
                      : "hover:bg-gray-100 dark:hover:bg-gray-800 border border-transparent"
                  }`}
                >
                  {editingId === conversation.id ? (
                    <div className="flex items-center gap-2">
                      <input
                        type="text"
                        value={editTitle}
                        onChange={(e) => setEditTitle(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            handleSaveTitle(e as any, conversation);
                          } else if (e.key === "Escape") {
                            handleCancelEdit(e);
                          }
                        }}
                        onClick={(e) => e.stopPropagation()}
                        className="flex-1 px-2 py-1 text-sm bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded focus:ring-2 focus:ring-blue-500 outline-none"
                        autoFocus
                      />
                      <button
                        onClick={(e) => handleSaveTitle(e, conversation)}
                        className="p-1 text-green-600 hover:bg-green-50 dark:hover:bg-green-900/30 rounded"
                      >
                        <CheckOutlined />
                      </button>
                      <button
                        onClick={handleCancelEdit}
                        className="p-1 text-red-600 hover:bg-red-50 dark:hover:bg-red-900/30 rounded"
                      >
                        <CloseOutlined />
                      </button>
                    </div>
                  ) : (
                    <div className="flex items-start gap-3">
                      <MessageOutlined className="text-gray-400 mt-0.5 flex-shrink-0" />
                      <div className="flex-1 min-w-0">
                        <h3 className="font-medium text-gray-900 dark:text-gray-100 truncate">
                          {conversation.title}
                        </h3>
                        <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                          {conversation.message_count} messages ·{" "}
                          {new Date(
                            conversation.updated_at || conversation.created_at
                          ).toLocaleDateString()}
                        </p>
                      </div>
                      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        {conversation.title === "New Conversation" && (
                          <button
                            onClick={(e) =>
                              handleGenerateTitle(e, conversation)
                            }
                            className="p-1.5 text-gray-400 hover:text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-900/30 rounded"
                            title="Generate title with AI"
                          >
                            <ThunderboltOutlined />
                          </button>
                        )}
                        <button
                          onClick={(e) => handleStartEdit(e, conversation)}
                          className="p-1.5 text-gray-400 hover:text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-900/30 rounded"
                          title="Rename"
                        >
                          <EditOutlined />
                        </button>
                        <button
                          onClick={(e) =>
                            handleDeleteConversation(e, conversation)
                          }
                          className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-900/30 rounded"
                          title="Delete"
                        >
                          <DeleteOutlined />
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
