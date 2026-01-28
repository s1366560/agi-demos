/**
 * ChatHistorySidebar - Conversation history sidebar (320px)
 *
 * Displays conversation history with status indicators.
 * Matches design from docs/statics/project workbench/agent/chat history/
 */

import { useState } from "react";

export type SidebarConversationStatus = "done" | "running" | "failed";

export interface Conversation {
  id: string;
  title: string;
  status: SidebarConversationStatus;
  messageCount?: number;
  timestamp?: string;
}

export interface ChatHistorySidebarProps {
  /** List of conversations */
  conversations?: Conversation[];
  /** Currently selected conversation ID */
  selectedConversationId?: string;
  /** Callback when conversation is clicked */
  onSelectConversation?: (conversationId: string) => void;
  /** Callback when "New Chat" is clicked */
  onNewChat?: () => void;
  /** Search query */
  searchQuery?: string;
  /** Callback when search query changes */
  onSearchChange?: (query: string) => void;
}

/**
 * ChatHistorySidebar component
 *
 * @example
 * <ChatHistorySidebar
 *   conversations={[
 *     { id: '1', title: 'Q4 Trend Analysis', status: 'done', timestamp: 'Today, 2:45 PM' },
 *     { id: '2', title: 'Project Onboarding', status: 'running', timestamp: 'Today, 10:20 AM' },
 *   ]}
 *   onSelectConversation={(id) => console.log(id)}
 *   onNewChat={() => console.log('new chat')}
 * />
 */
export function ChatHistorySidebar({
  conversations = [],
  selectedConversationId,
  onSelectConversation,
  onNewChat,
  searchQuery = "",
  onSearchChange,
}: ChatHistorySidebarProps) {
  const [localSearch, setLocalSearch] = useState(searchQuery);

  const handleSearchChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    setLocalSearch(value);
    onSearchChange?.(value);
  };

  // Filter conversations based on search
  const filteredConversations = conversations.filter((conv) =>
    conv.title.toLowerCase().includes(localSearch.toLowerCase())
  );

  // Split into recent (top 5) and older
  const recentConversations = filteredConversations.slice(0, 5);
  const olderConversations = filteredConversations.slice(5);

  const getStatusColor = (status: SidebarConversationStatus): string => {
    switch (status) {
      case "done":
        return "text-emerald-500";
      case "running":
        return "text-blue-500";
      case "failed":
        return "text-red-500";
      default:
        return "text-slate-400";
    }
  };

  const getStatusLabel = (status: SidebarConversationStatus): string => {
    switch (status) {
      case "done":
        return "Done";
      case "running":
        return "Running";
      case "failed":
        return "Failed";
      default:
        return "";
    }
  };

  return (
    <aside className="w-80 flex flex-col bg-slate-50 dark:bg-[#0c0c0e] border-r border-slate-200 dark:border-border-dark shrink-0">
      <div className="p-4 flex flex-col h-full space-y-4">
        {/* New Chat Button */}
        <button
          onClick={onNewChat}
          aria-label="新建对话"
          className="w-full flex items-center justify-center gap-2 bg-primary hover:bg-primary/90 text-white py-2.5 px-4 rounded-xl transition-all shadow-lg shadow-primary/20 text-sm font-semibold"
        >
          <span className="material-symbols-outlined text-xl">add_comment</span>
          <span>New Chat</span>
        </button>

        {/* Search Input */}
        <div className="relative">
          <span
            className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-text-muted text-lg"
            aria-hidden="true"
          >
            search
          </span>
          <input
            type="text"
            value={localSearch}
            onChange={handleSearchChange}
            placeholder="Search history..."
            aria-label="搜索对话历史"
            className="w-full bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-xl pl-10 pr-4 py-2 text-sm focus:ring-2 focus:ring-primary/50 transition-all placeholder:text-text-muted text-slate-900 dark:text-white shadow-md"
          />
        </div>

        {/* Scrollable Conversation List */}
        <div className="flex-1 overflow-y-auto space-y-1 -mx-2 px-2">
          {/* Recent Sessions */}
          {recentConversations.length > 0 && (
            <>
              <h3 className="text-[10px] font-bold text-text-muted uppercase tracking-wider px-2 mb-2 mt-4">
                Recent Sessions
              </h3>
              {recentConversations.map((conversation) => (
                <button
                  key={conversation.id}
                  onClick={() => onSelectConversation?.(conversation.id)}
                  aria-label={conversation.title}
                  aria-pressed={selectedConversationId === conversation.id}
                  aria-current={selectedConversationId === conversation.id ? 'true' : undefined}
                  className={`w-full text-left p-3 rounded-xl cursor-pointer transition-colors group ${
                    selectedConversationId === conversation.id
                      ? "bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark ring-1 ring-primary/30"
                      : "hover:bg-slate-100 dark:hover:bg-white/5"
                  }`}
                >
                  <div className="flex justify-between items-start mb-1">
                    <h4
                      className={`text-sm font-medium truncate pr-2 leading-tight ${
                        selectedConversationId === conversation.id
                          ? "text-slate-900 dark:text-white font-semibold"
                          : "text-slate-700 dark:text-slate-300 group-hover:text-slate-900 dark:group-hover:text-white"
                      }`}
                    >
                      {conversation.title}
                    </h4>
                    <span
                      className={`flex-shrink-0 flex items-center gap-1 text-[10px] font-bold uppercase ${getStatusColor(
                        conversation.status
                      )}`}
                    >
                      <span
                        className={`w-1.5 h-1.5 rounded-full ${getStatusColor(
                          conversation.status
                        ).replace("text-", "bg-")}`}
                      />
                      {getStatusLabel(conversation.status)}
                    </span>
                  </div>
                  {conversation.timestamp && (
                    <p className="text-[11px] text-text-muted">
                      {conversation.timestamp}
                    </p>
                  )}
                </button>
              ))}
            </>
          )}

          {/* Older Sessions */}
          {olderConversations.length > 0 && (
            <>
              <h3 className="text-[10px] font-bold text-text-muted uppercase tracking-wider px-2 mb-2 mt-6">
                Older
              </h3>
              {olderConversations.map((conversation) => (
                <button
                  key={conversation.id}
                  onClick={() => onSelectConversation?.(conversation.id)}
                  aria-label={conversation.title}
                  aria-pressed={selectedConversationId === conversation.id}
                  className="w-full text-left p-3 hover:bg-slate-100 dark:hover:bg-white/5 rounded-xl cursor-pointer transition-colors group"
                >
                  <div className="flex justify-between items-start mb-1">
                    <h4 className="text-sm font-medium text-slate-700 dark:text-slate-300 group-hover:text-slate-900 dark:group-hover:text-white truncate pr-2 leading-tight">
                      {conversation.title}
                    </h4>
                    <span
                      className={`flex-shrink-0 flex items-center gap-1 text-[10px] font-bold uppercase ${getStatusColor(
                        conversation.status
                      )}`}
                    >
                      <span
                        className={`w-1.5 h-1.5 rounded-full ${getStatusColor(
                          conversation.status
                        ).replace("text-", "bg-")}`}
                      />
                      {getStatusLabel(conversation.status)}
                    </span>
                  </div>
                  {conversation.timestamp && (
                    <p className="text-[11px] text-text-muted">
                      {conversation.timestamp}
                    </p>
                  )}
                </button>
              ))}
            </>
          )}

          {/* Empty State */}
          {filteredConversations.length === 0 && localSearch && (
            <div className="text-center py-8">
              <p className="text-sm text-slate-400">No conversations found</p>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}

export default ChatHistorySidebar;
