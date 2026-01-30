/**
 * ConversationSidebar component
 *
 * Sidebar showing list of conversations with ability to create,
 * select, and delete conversations.
 */

import React, { useEffect, useRef } from 'react';
import {
  List,
  Button,
  Typography,
  Popconfirm,
  Empty,
  Spin,
  Space,
} from 'antd';
import {
  PlusOutlined,
  DeleteOutlined,
  MessageOutlined,
  CheckCircleOutlined,
} from '@ant-design/icons';
import { useAgentV3Store } from '../../stores/agentV3';
import type { Conversation } from '../../types/agent';

const { Text } = Typography;

interface ConversationSidebarProps {
  projectId: string;
  onCreateConversation?: () => void;
  onSelectConversation?: (conversation: Conversation) => void;
}

export const ConversationSidebar: React.FC<ConversationSidebarProps> = ({
  projectId,
  onCreateConversation,
  onSelectConversation,
}) => {
  const {
    conversations,
    activeConversationId,
    isLoadingHistory,
    loadConversations,
    createNewConversation,
    deleteConversation,
    setActiveConversation,
  } = useAgentV3Store();



  // Use ref to prevent duplicate calls from StrictMode
  const loadedProjectIdRef = useRef<string | null>(null);
  const loadConversationsRef = useRef(loadConversations);
  loadConversationsRef.current = loadConversations;
  
  useEffect(() => {
    if (projectId && loadedProjectIdRef.current !== projectId) {
      loadedProjectIdRef.current = projectId;
      loadConversationsRef.current(projectId);
    }
  }, [projectId]);

  const handleCreate = async () => {
    try {
      const newId = await createNewConversation(projectId);
      if (newId && onCreateConversation) {
        onCreateConversation();
      }
      // Find the newly created conversation
      const newConversation = conversations.find(c => c.id === newId);
      if (newConversation && onSelectConversation) {
        onSelectConversation(newConversation);
      }
    } catch (error) {
      console.error('Failed to create conversation:', error);
    }
  };

  const handleSelect = (conversation: Conversation) => {
    setActiveConversation(conversation.id);
    if (onSelectConversation) {
      onSelectConversation(conversation);
    }
  };

  const handleDelete = async (conversationId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await deleteConversation(conversationId, projectId);
    } catch (error) {
      console.error('Failed to delete conversation:', error);
    }
  };

  return (
    <div
      style={{
        width: 280,
        borderRight: '1px solid #f0f0f0',
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        backgroundColor: '#fafafa',
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: '16px',
          borderBottom: '1px solid #f0f0f0',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <Text strong>Conversations</Text>
        <Button
          type="primary"
          size="small"
          icon={<PlusOutlined />}
          onClick={handleCreate}
        >
          New
        </Button>
      </div>

      {/* Conversation list */}
      <div style={{ flex: 1, overflow: 'auto' }}>
        {isLoadingHistory ? (
          <div style={{ padding: 24, textAlign: 'center' }}>
            <Spin />
          </div>
        ) : conversations.length === 0 ? (
          <div style={{ padding: 24 }}>
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="No conversations yet"
            />
          </div>
        ) : (
          <List
            dataSource={conversations}
            renderItem={(conversation) => (
              <List.Item
                key={conversation.id}
                onClick={() => handleSelect(conversation)}
                style={{
                  padding: '12px 16px',
                  cursor: 'pointer',
                  borderBottom: '1px solid #f0f0f0',
                  backgroundColor:
                    activeConversationId === conversation.id ? '#e6f7ff' : 'transparent',
                }}
              >
                <div style={{ width: '100%' }}>
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'flex-start',
                      marginBottom: 4,
                    }}
                  >
                    <Text
                      ellipsis={{ tooltip: conversation.title }}
                      style={{
                        flex: 1,
                        fontWeight:
                          activeConversationId === conversation.id ? 600 : 400,
                      }}
                    >
                      {conversation.title}
                    </Text>
                    {conversation.status === 'active' && (
                      <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 12 }} />
                    )}
                  </div>
                  <Space size="small">
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      <MessageOutlined /> {conversation.message_count}
                    </Text>
                    <Popconfirm
                      title="Delete this conversation?"
                      description="This will delete all messages in this conversation."
                      onConfirm={(e) => handleDelete(conversation.id, e as any)}
                      okText="Delete"
                      cancelText="Cancel"
                    >
                      <Button
                        type="text"
                        size="small"
                        icon={<DeleteOutlined />}
                        onClick={(e) => e.stopPropagation()}
                        danger
                      />
                    </Popconfirm>
                  </Space>
                </div>
              </List.Item>
            )}
          />
        )}
      </div>
    </div>
  );
};
