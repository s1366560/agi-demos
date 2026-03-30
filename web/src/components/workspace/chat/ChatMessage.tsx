import React from 'react';

import { Avatar, Typography } from 'antd';
import { Bot, User } from 'lucide-react';

import type { WorkspaceMessage } from '@/types/workspace';

const { Text } = Typography;

const MENTION_RE = /@"([^"]{1,64})"|@([\w][\w\-.]{0,62}[\w]|[\w])/g;

function renderContentWithMentions(content: string, isOwn: boolean): React.ReactNode {
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;

  for (const match of content.matchAll(MENTION_RE)) {
    const matchIndex = match.index;
    if (matchIndex > lastIndex) {
      parts.push(content.slice(lastIndex, matchIndex));
    }
    const mentionName = match[1] || match[2];
    parts.push(
      <span
        key={matchIndex}
        className={`font-medium ${isOwn ? 'text-blue-200' : 'text-blue-600'}`}
      >
        @{mentionName}
      </span>,
    );
    lastIndex = matchIndex + match[0].length;
  }

  if (lastIndex < content.length) {
    parts.push(content.slice(lastIndex));
  }

  return parts.length > 0 ? parts : content;
}

export interface ChatMessageProps {
  message: WorkspaceMessage;
  isOwn: boolean;
}

export const ChatMessage: React.FC<ChatMessageProps> = ({ message, isOwn }) => {
  const isAgent = message.sender_type === 'agent';
  
  const timeString = new Intl.DateTimeFormat('en-US', {
    hour: 'numeric',
    minute: 'numeric',
    hour12: true,
  }).format(new Date(message.created_at));

  return (
    <div className={`flex w-full mb-4 ${isOwn ? 'justify-end' : 'justify-start'}`}>
      <div className={`flex max-w-[70%] ${isOwn ? 'flex-row-reverse' : 'flex-row'}`}>
        <div className="flex-shrink-0 mt-1">
          <Avatar
            icon={isAgent ? <Bot size={16} /> : <User size={16} />}
            className={isAgent ? 'bg-blue-100 text-blue-600' : 'bg-slate-200 text-slate-600'}
            size="small"
          />
        </div>
        
        <div className={`flex flex-col mx-2 ${isOwn ? 'items-end' : 'items-start'}`}>
          <div className="flex items-baseline space-x-2 mb-1">
            {!isOwn && (
              <Text type="secondary" className="text-xs">
                {(message.metadata.sender_name as string) || (isAgent ? 'Agent' : 'User')}
              </Text>
            )}
            <Text type="secondary" className="text-[10px]">
              {timeString}
            </Text>
          </div>
          
          <div
            className={`px-4 py-2 rounded-2xl shadow-sm text-sm whitespace-pre-wrap break-words ${
              isOwn
                ? 'bg-blue-600 text-white rounded-tr-sm'
                : 'bg-white border border-slate-100 text-slate-800 rounded-tl-sm'
            }`}
          >
            {renderContentWithMentions(message.content, isOwn)}
          </div>
        </div>
      </div>
    </div>
  );
};
