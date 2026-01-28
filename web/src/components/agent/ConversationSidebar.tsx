import React, { useMemo } from "react";
import { Button } from "antd";
import {
  PlusOutlined,
  MessageOutlined,
  DeleteOutlined,
} from "@ant-design/icons";
import { Conversation } from "../../types/agent";

interface ConversationSidebarProps {
  conversations: Conversation[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string, e: React.MouseEvent) => void;
}

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
    <div className="flex flex-col h-full bg-slate-50">
      <div className="p-4 border-b border-slate-200">
        <Button
          type="primary"
          block
          icon={<PlusOutlined />}
          onClick={onNew}
          className="h-10 font-medium"
        >
          New Chat
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto custom-scrollbar p-2">
        {formattedConversations.map((item) => (
          <div
            key={item.id}
            onClick={() => onSelect(item.id)}
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
            />
          </div>
        ))}
      </div>
    </div>
  );
};
