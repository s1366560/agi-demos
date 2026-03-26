import type { FC } from 'react';

import { Tooltip } from 'antd';

export interface PresenceAvatarProps {
  displayName: string;
  type: 'user' | 'agent';
  status?: string;
  themeColor?: string;
}

const STATUS_COLORS: Record<string, string> = {
  online: '#52c41a',
  idle: '#8c8c8c',
  busy: '#1890ff',
  error: '#ff4d4f',
};

export const PresenceAvatar: FC<PresenceAvatarProps> = ({
  displayName,
  type,
  status = 'online',
  themeColor,
}) => {
  const initial = displayName.charAt(0).toUpperCase();
  const bgColor = themeColor ?? (type === 'agent' ? '#722ed1' : '#1677ff');
  const statusColor = STATUS_COLORS[status] ?? STATUS_COLORS.online;

  return (
    <Tooltip title={`${displayName} (${status})`}>
      <div style={{ position: 'relative', display: 'inline-block' }}>
        <div
          style={{
            width: 32,
            height: 32,
            borderRadius: '50%',
            backgroundColor: bgColor,
            color: '#fff',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 14,
            fontWeight: 600,
            border: type === 'agent' ? '2px solid #d3adf7' : '2px solid #e6e6e6',
          }}
        >
          {initial}
        </div>
        <div
          style={{
            position: 'absolute',
            bottom: -1,
            right: -1,
            width: 10,
            height: 10,
            borderRadius: '50%',
            backgroundColor: statusColor,
            border: '2px solid #fff',
          }}
        />
      </div>
    </Tooltip>
  );
};
