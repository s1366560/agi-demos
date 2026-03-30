import type React from 'react';
import { useEffect } from 'react';

import { useTranslation } from 'react-i18next';

import { PushpinOutlined, PushpinFilled, DeleteOutlined } from '@ant-design/icons';
import {
  Card,
  Button,
  Input,
  Form,
  Typography,
  Empty,
  Popconfirm,
  Space,
  Divider,
  Tag,
  List,
} from 'antd';

import {
  useSelectedPost,
  useBlackboardReplies,
  useBlackboardActions,
  useBlackboardLoading,
} from '@/stores/blackboard';

import { formatDateTime } from '@/utils/date';


const { Title, Paragraph } = Typography;

export interface PostDetailProps {
  tenantId: string;
  projectId: string;
  workspaceId: string;
}

export const PostDetail: React.FC<PostDetailProps> = ({ tenantId, projectId, workspaceId }) => {
  const { t } = useTranslation();
  const [form] = Form.useForm();

  const selectedPost = useSelectedPost();
  const replies = useBlackboardReplies();
  const loading = useBlackboardLoading();
  const { fetchReplies, createReply, deleteReply, deletePost, pinPost, unpinPost } =
    useBlackboardActions();

  const postId = selectedPost?.id;

  useEffect(() => {
    if (postId) {
      void fetchReplies(tenantId, projectId, workspaceId, postId);
    }
  }, [tenantId, projectId, workspaceId, postId, fetchReplies]);

  if (!selectedPost) {
    return (
      <Card className="flex h-full items-center justify-center shadow-sm bg-gray-50/50">
        <Empty 
          description={
            <span className="text-gray-400">
              {t('blackboard.selectPost', 'Select a post to view details')}
            </span>
          }
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        />
      </Card>
    );
  }

  const handleReply = async (values: { content: string }) => {
    try {
      await createReply(tenantId, projectId, workspaceId, selectedPost.id, values.content);
      form.resetFields();
    } catch {
      // Error already shown via store's message.error
    }
  };

  return (
    <Card className="flex h-full flex-col shadow-sm" styles={{ body: { padding: 0 } }}>
      <div className="flex flex-col h-full">
        <div className="flex-1 overflow-y-auto p-6">
          <div className="mb-6 flex items-start justify-between gap-4">
            <div className="flex-1">
              <Title level={4} className="!mb-2">
                {selectedPost.title}
              </Title>
              <Space size="middle" className="text-sm text-gray-500">
                <span className="font-medium">{selectedPost.author_id}</span>
                <span className="text-gray-300">•</span>
                <span>{formatDateTime(selectedPost.created_at)}</span>
                {selectedPost.status === 'archived' && (
                  <Tag color="default" className="!ml-0 !mr-0 border-gray-200">
                    {t('blackboard.archived')}
                  </Tag>
                )}
              </Space>
            </div>
            <Space className="shrink-0">
              <Button
                type="text"
                className="hover:bg-gray-100 transition-colors"
                icon={selectedPost.is_pinned ? <PushpinFilled className="text-blue-500" /> : <PushpinOutlined className="text-gray-500 hover:text-gray-700" />}
                onClick={() =>
                  selectedPost.is_pinned
                    ? unpinPost(tenantId, projectId, workspaceId, selectedPost.id)
                    : pinPost(tenantId, projectId, workspaceId, selectedPost.id)
                }
                title={selectedPost.is_pinned ? t('blackboard.unpin', 'Unpin') : t('blackboard.pin', 'Pin')}
              />
              <Popconfirm
                title={t('blackboard.deleteConfirm', 'Are you sure you want to delete this post?')}
                onConfirm={() => deletePost(tenantId, projectId, workspaceId, selectedPost.id)}
                okText={t('common.yes')}
                cancelText={t('common.no')}
                okButtonProps={{ danger: true }}
              >
                <Button 
                  type="text" 
                  danger 
                  icon={<DeleteOutlined />} 
                  title={t('blackboard.delete')} 
                  className="hover:bg-red-50 transition-colors"
                />
              </Popconfirm>
            </Space>
          </div>

          <Paragraph className="whitespace-pre-wrap text-base text-gray-700">
            {selectedPost.content}
          </Paragraph>

          <Divider className="my-6" />

          <div>
            <Title level={5} className="!mb-4 text-gray-700">
              {t('blackboard.replies')} ({replies.length})
            </Title>

            <List
              dataSource={replies}
              loading={loading && replies.length === 0}
              locale={{ 
                emptyText: (
                  <Empty 
                    description={
                      <span className="text-gray-400">
                        {t('blackboard.noReplies', 'No replies yet')}
                      </span>
                    } 
                    image={Empty.PRESENTED_IMAGE_SIMPLE} 
                  />
                ) 
              }}
              renderItem={(reply) => (
                <List.Item
                  className="group px-4 py-4 hover:bg-gray-50/50 rounded-lg transition-colors -mx-4"
                  actions={[
                    <Popconfirm
                      key="delete"
                      title={t('blackboard.deleteReplyConfirm', 'Delete this reply?')}
                      onConfirm={() =>
                        deleteReply(tenantId, projectId, workspaceId, selectedPost.id, reply.id)
                      }
                      okText={t('common.yes')}
                      cancelText={t('common.no')}
                      okButtonProps={{ danger: true }}
                    >
                      <Button 
                        type="text" 
                        danger 
                        size="small" 
                        icon={<DeleteOutlined />} 
                        className="opacity-0 group-hover:opacity-100 hover:bg-red-50 transition-all"
                        aria-label={t('blackboard.delete', 'Delete')}
                      />
                    </Popconfirm>,
                  ]}
                >
                  <List.Item.Meta
                    title={
                      <Space size="middle" className="text-sm text-gray-500">
                        <span className="font-medium text-gray-700">
                          {reply.author_id}
                        </span>
                        <span className="text-gray-300">•</span>
                        <span>{formatDateTime(reply.created_at)}</span>
                      </Space>
                    }
                    description={
                      <div className="mt-2 whitespace-pre-wrap text-gray-700 text-base">
                        {reply.content}
                      </div>
                    }
                  />
                </List.Item>
              )}
            />
          </div>
        </div>

        <div className="border-t border-gray-100 bg-gray-50 p-4">
          <Form form={form} onFinish={handleReply} className="flex items-start gap-2">
            <Form.Item
              name="content"
              className="mb-0 flex-1"
              rules={[{ required: true, message: t('blackboard.required') }]}
            >
              <Input.TextArea
                rows={2}
                placeholder={t('blackboard.writeReply', 'Write a reply...')}
                autoSize={{ minRows: 2, maxRows: 6 }}
              />
            </Form.Item>
            <Button type="primary" htmlType="submit" loading={loading} disabled={loading} className="mt-1">
              {t('blackboard.sendReply', 'Send')}
            </Button>
          </Form>
        </div>
      </div>
    </Card>
  );
};
