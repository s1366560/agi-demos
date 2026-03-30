import type { FC } from 'react';

import { Tooltip } from 'antd';

export interface PresenceAvatarProps {
  displayName: string;
  type: 'user' | 'agent';
  status?: string;
  themeColor?: string;
}

const STATUS_COLORS: Record<string, string> = {
  online: 'bg-green-500',
  idle: 'bg-slate-400',
  busy: 'bg-blue-500',
  error: 'bg-red-500',
};

export const PresenceAvatar: FC<PresenceAvatarProps> = ({
  displayName,
  type,
  status = 'online',
  themeColor,
}) => {
  const initial = displayName.charAt(0).toUpperCase();
  const defaultBgClass = type === 'agent' ? 'bg-purple-600' : 'bg-blue-600';
  const borderClass = type === 'agent' ? 'border-2 border-purple-300' : 'border-2 border-slate-200';
  const statusColorClass = STATUS_COLORS[status] ?? 'bg-green-500';

  return (
    <Tooltip title={`${displayName} (${status})`}>
      <div className="relative inline-block">
        <div
          className={`w-8 h-8 rounded-full text-white flex items-center justify-center text-sm font-semibold ${borderClass} ${!themeColor ? defaultBgClass : ''}`}
          style={themeColor ? { backgroundColor: themeColor } : undefined}
        >
          {initial}
        </div>
        <div
          className={`absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border-2 border-white ${statusColorClass}`}
        />
      </div>
    </Tooltip>
  );
};
