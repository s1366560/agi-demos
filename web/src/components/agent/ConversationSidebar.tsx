import React, { useMemo } from "react";
import { Button } from "antd";
import {
  PlusOutlined,
  MessageOutlined,
  DeleteOutlined,
} from "@ant-design/icons";
import { Conversation } from "../../types/agent";

/**
 * Props for ConversationSidebar component
 */
interface ConversationSidebarProps {
  /** Array of conversations to display */
  conversations: Conversation[];
  /** ID of the currently active conversation */
  activeId: string | null;
  /** Callback when a conversation is selected */
  onSelect: (id: string) => void;
  /** Callback when the "New Chat" button is clicked */
  onNew: () => void;
  /** Callback when a conversation is deleted */
  onDelete: (id: string, e: React.MouseEvent) => void;
}

/**
 * ConversationSidebar Component - Conversation history sidebar
 *
 * Displays a list of conversations with selection, creation, and deletion
 * capabilities. Formats dates and highlights active conversation.
 *
 * @component
 *
 * @features
 * - New chat button for creating conversations
 * - Scrollable conversation list
 * - Active conversation highlighting
 * - Conversation date formatting
 * - Delete button with hover visibility
 * - Active status indicator
 * - Memoized formatted conversations for performance
 *
 * @example
 * ```tsx
 * import { ConversationSidebar } from '@/components/agent/ConversationSidebar'
 *
 * function AgentChat() {
 *   const { conversations, activeId } = useAgentV3Store()
 *
 *   const handleSelect = (id: string) => setActiveConversation(id)
 *   const handleNew = () => createNewConversation()
 *   const handleDelete = (id: string) => deleteConversation(id)
 *
 *   return (
 *     <ConversationSidebar
 *       conversations={conversations}
 *       activeId={activeId}
 *       onSelect={handleSelect}
 *       onNew={handleNew}
 *       onDelete={handleDelete}
 *     />
 *   )
 * }
 * ```
 */

export const ConversationSidebar: React.FC<ConversationSidebarProps> = ({
  conversations,
  activeId,
  onSelect,
  onNew,
  onDelete,
}) => {
  // Memoize conversation list with formatted dates to avoid re-computing on every render
  const formattedConversations = useMemo(() => {
    return conversations.map((item) => ({
      ...item,
      formattedDate: new Date(item.created_at).toLocaleDateString(),
      isActive: item.id === activeId,
      displayTitle: item.title || "Untitled Conversation",
    }));
  }, [conversations, activeId]);

  return (
    <div className="flex flex-col h-full bg-slate-50" data-testid="conversation-sidebar">
      <div className="p-4 border-b border-slate-200">
        <Button
          type="primary"
          block
          icon={<PlusOutlined />}
          onClick={onNew}
          className="h-10 font-medium"
          data-testid="new-chat-button"
        >
          New Chat
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto custom-scrollbar p-2" data-testid="conversation-list">
        {formattedConversations.map((item) => (
          <div
            key={item.id}
            onClick={() => onSelect(item.id)}
            data-testid={`conversation-${item.id}`}
            data-active={item.isActive}
            className={`
              group relative flex items-start gap-3 p-3 mb-1 rounded-lg cursor-pointer transition-all
              ${
                item.isActive
                  ? "bg-white shadow-sm border border-slate-200"
                  : "hover:bg-slate-100 border border-transparent"
              }
            `}
          >
            <MessageOutlined
              className={`mt-1 ${
                item.isActive ? "text-primary" : "text-slate-400"
              }`}
            />

            <div className="flex-1 min-w-0">
              <div
                className={`block truncate text-sm mb-0.5 ${
                  item.isActive
                    ? "font-semibold text-slate-900"
                    : "text-slate-700"
                }`}
              >
                {item.displayTitle}
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-500">
                  {item.formattedDate}
                </span>
                {item.status === "active" && (
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                )}
              </div>
            </div>

            <Button
              type="text"
              size="small"
              icon={<DeleteOutlined />}
              className="absolute right-2 top-2 opacity-0 group-hover:opacity-100 text-slate-400 hover:text-red-500"
              onClick={(e) => onDelete(item.id, e)}
              data-testid={`delete-conversation-${item.id}`}
            />
          </div>
        ))}
      </div>
    </div>
  );
};
