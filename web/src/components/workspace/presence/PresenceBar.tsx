import type { FC } from 'react';

import { Space, Typography } from 'antd';

import { useOnlineAgents, useOnlineUsers } from '@/stores/workspace';

import { PresenceAvatar } from '@/components/workspace/presence/PresenceAvatar';

const { Text } = Typography;

export interface PresenceBarProps {
  workspaceId: string;
}

export const PresenceBar: FC<PresenceBarProps> = () => {
  const onlineUsers = useOnlineUsers();
  const onlineAgents = useOnlineAgents();

  const totalOnline = onlineUsers.length + onlineAgents.length;

  if (totalOnline === 0) {
    return null;
  }

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '8px 16px',
        borderRadius: 8,
        backgroundColor: 'rgba(0, 0, 0, 0.02)',
        border: '1px solid rgba(0, 0, 0, 0.06)',
      }}
    >
      <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>
        Online ({totalOnline})
      </Text>
      <Space size={4} wrap>
        {onlineUsers.map((user) => (
          <PresenceAvatar
            key={user.user_id}
            displayName={user.display_name}
            type="user"
            status="online"
          />
        ))}
        {onlineAgents.map((agent) => (
          <PresenceAvatar
            key={agent.agent_id}
            displayName={agent.display_name}
            type="agent"
            status={agent.status}
          />
        ))}
      </Space>
    </div>
  );
};
