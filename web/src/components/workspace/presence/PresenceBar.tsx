import type { FC } from 'react';

import { useTranslation } from 'react-i18next';

import { Space, Typography } from 'antd';

import { useOnlineAgents, useOnlineUsers } from '@/stores/workspace';

import { PresenceAvatar } from '@/components/workspace/presence/PresenceAvatar';

const { Text } = Typography;

export interface PresenceBarProps {
  workspaceId: string;
}

export const PresenceBar: FC<PresenceBarProps> = () => {
  const { t } = useTranslation();
  const onlineUsers = useOnlineUsers();
  const onlineAgents = useOnlineAgents();

  const totalOnline = onlineUsers.length + onlineAgents.length;

  if (totalOnline === 0) {
    return null;
  }

  return (
    <div className="flex items-center gap-3 px-4 py-2 rounded-lg bg-slate-50 dark:bg-slate-800 border border-slate-200/60 dark:border-slate-700/60 transition-colors duration-200">
      <Text type="secondary" className="text-xs whitespace-nowrap">
        {t('workspaceDetail.presence.online')} ({totalOnline})
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
