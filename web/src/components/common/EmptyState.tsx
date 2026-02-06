import React from 'react';

import { useTranslation } from 'react-i18next';

import {
  PlusOutlined,
  SearchOutlined,
  FileTextOutlined,
  MessageOutlined,
  TeamOutlined,
  DatabaseOutlined,
} from '@ant-design/icons';

import { LazyEmpty, LazyButton } from '@/components/ui/lazyAntd';

export interface EmptyStateProps {
  type?: 'generic' | 'data' | 'search' | 'memories' | 'conversations' | 'entities' | 'team';
  title?: string;
  description?: string;
  actionText?: string;
  onAction?: () => void;
  illustration?: React.ReactNode;
}

/**
 * EmptyState Component
 * Provides consistent empty state UI across the application
 *
 * @param type - Predefined empty state type
 * @param title - Custom title (overrides type default)
 * @param description - Custom description (overrides type default)
 * @param actionText - Custom action button text
 * @param onAction - Action button click handler
 * @param illustration - Custom illustration (overrides type default)
 */
export const EmptyState: React.FC<EmptyStateProps> = ({
  type = 'generic',
  title,
  description,
  actionText,
  onAction,
  illustration,
}) => {
  const { t } = useTranslation();

  // Predefined empty state configurations
  const configs: Record<
    string,
    {
      icon: React.ReactNode;
      defaultTitle: string;
      defaultDescription: string;
    }
  > = {
    generic: {
      icon: <FileTextOutlined style={{ fontSize: 64, color: '#d9d9d9' }} />,
      defaultTitle: t('empty.generic.title', { defaultValue: 'No Data' }),
      defaultDescription: t('empty.generic.description', {
        defaultValue: 'There is no data to display yet.',
      }),
    },
    data: {
      icon: <DatabaseOutlined style={{ fontSize: 64, color: '#d9d9d9' }} />,
      defaultTitle: t('empty.data.title', { defaultValue: 'No Data Found' }),
      defaultDescription: t('empty.data.description', {
        defaultValue: 'Get started by creating your first entry.',
      }),
    },
    search: {
      icon: <SearchOutlined style={{ fontSize: 64, color: '#d9d9d9' }} />,
      defaultTitle: t('empty.search.title', { defaultValue: 'No Results' }),
      defaultDescription: t('empty.search.description', {
        defaultValue: 'Try adjusting your search terms or filters.',
      }),
    },
    memories: {
      icon: <FileTextOutlined style={{ fontSize: 64, color: '#d9d9d9' }} />,
      defaultTitle: t('empty.memories.title', { defaultValue: 'No Memories Yet' }),
      defaultDescription: t('empty.memories.description', {
        defaultValue: 'Memories will appear here as you process episodes.',
      }),
    },
    conversations: {
      icon: <MessageOutlined style={{ fontSize: 64, color: '#d9d9d9' }} />,
      defaultTitle: t('empty.conversations.title', { defaultValue: 'No Conversations' }),
      defaultDescription: t('empty.conversations.description', {
        defaultValue: 'Start a new conversation with the agent.',
      }),
    },
    entities: {
      icon: <TeamOutlined style={{ fontSize: 64, color: '#d9d9d9' }} />,
      defaultTitle: t('empty.entities.title', { defaultValue: 'No Entities Found' }),
      defaultDescription: t('empty.entities.description', {
        defaultValue: 'Entities will be extracted from your memories.',
      }),
    },
    team: {
      icon: <TeamOutlined style={{ fontSize: 64, color: '#d9d9d9' }} />,
      defaultTitle: t('empty.team.title', { defaultValue: 'No Team Members' }),
      defaultDescription: t('empty.team.description', {
        defaultValue: 'Invite team members to collaborate on this project.',
      }),
    },
  };

  const config = configs[type] || configs.generic;

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '60px 20px',
        minHeight: '400px',
      }}
    >
      <LazyEmpty
        image={illustration || config.icon}
        description={
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: '16px', fontWeight: 500, marginBottom: '8px' }}>
              {title || config.defaultTitle}
            </div>
            <div style={{ fontSize: '14px', color: '#8c8c8c' }}>
              {description || config.defaultDescription}
            </div>
          </div>
        }
      />
      {onAction && (
        <LazyButton
          type="primary"
          icon={<PlusOutlined />}
          onClick={onAction}
          style={{ marginTop: '16px' }}
        >
          {actionText || t('empty.create', { defaultValue: 'Create New' })}
        </LazyButton>
      )}
    </div>
  );
};

export default EmptyState;
