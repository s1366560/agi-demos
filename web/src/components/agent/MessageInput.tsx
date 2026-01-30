/**
 * MessageInput component
 *
 * Input field for sending messages to the agent.
 */

import React, { useState } from 'react';
import { Input, Button, Space } from 'antd';
import { SendOutlined } from '@ant-design/icons';
import { useAgentV3Store } from '../../stores/agentV3';

const { TextArea } = Input;

interface MessageInputProps {
  disabled?: boolean;
  onSend?: (message: string) => void;
}

export const MessageInput: React.FC<MessageInputProps> = ({ disabled = false, onSend }) => {
  const [message, setMessage] = useState('');
  const { isStreaming, activeConversationId } = useAgentV3Store();

  const handleSend = async () => {
    if (!message.trim() || isStreaming || !activeConversationId) {
      return;
    }

    const messageToSend = message;
    setMessage('');

    if (onSend) {
      onSend(messageToSend);
    } else {
      // Use store's sendMessage
      await useAgentV3Store.getState().sendMessage(
        messageToSend,
        '', // projectId will be set by caller
      );
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div
      style={{
        padding: '16px 24px',
        borderTop: '1px solid #f0f0f0',
        backgroundColor: '#fff',
      }}
    >
      <Space.Compact style={{ width: '100%', display: 'flex' }}>
        <TextArea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={handleKeyPress}
          placeholder="Type your message... (Enter to send, Shift+Enter for new line)"
          autoSize={{ minRows: 1, maxRows: 4 }}
          disabled={disabled || isStreaming}
          style={{ flex: 1 }}
        />
        <Button
          type="primary"
          icon={<SendOutlined />}
          onClick={handleSend}
          disabled={!message.trim() || disabled || isStreaming}
          style={{ height: 'auto' }}
        >
          Send
        </Button>
      </Space.Compact>
    </div>
  );
};
