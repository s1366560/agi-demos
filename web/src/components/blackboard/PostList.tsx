import type React from 'react';
import { useState, useMemo } from 'react';

import { useTranslation } from 'react-i18next';

import { PushpinOutlined, MessageOutlined } from '@ant-design/icons';
import { Card, Button, Input, Form, Typography, Tabs, Space, Tag, Empty, Spin } from 'antd';

import {
  useBlackboardPosts,
  useSelectedPost,
  useBlackboardActions,
  useBlackboardLoading,
} from '@/stores/blackboard';

import { formatDateOnly } from '@/utils/date';


const { Text } = Typography;

export interface PostListProps {
  tenantId: string;
  projectId: string;
  workspaceId: string;
}

export const PostList: React.FC<PostListProps> = ({ tenantId, projectId, workspaceId }) => {
  const { t } = useTranslation();
  const [form] = Form.useForm();

  const posts = useBlackboardPosts();
  const selectedPost = useSelectedPost();
  const loading = useBlackboardLoading();
  const { selectPost, createPost } = useBlackboardActions();

  const [isCreating, setIsCreating] = useState(false);
  const [filter, setFilter] = useState<'all' | 'pinned'>('all');

  const filteredPosts = useMemo(() => {
    let result = [...posts];
    if (filter === 'pinned') {
      result = result.filter((p) => p.is_pinned);
    }
    
    return result.sort((a, b) => {
      if (a.is_pinned && !b.is_pinned) return -1;
      if (!a.is_pinned && b.is_pinned) return 1;
      return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
    });
  }, [posts, filter]);

  const handleCreate = async (values: { title: string; content: string }) => {
    try {
      await createPost(tenantId, projectId, workspaceId, values);
      setIsCreating(false);
      form.resetFields();
    } catch {
      // Error already shown via store's message.error
    }
  };

  return (
    <Card
      className="flex h-full flex-col shadow-sm"
      styles={{ body: { display: 'flex', flexDirection: 'column', flex: 1, padding: 0, overflow: 'hidden' } }}
    >
      <div className="border-b border-gray-100 p-4">
        <div className="mb-4 flex items-center justify-between">
          <Tabs
            activeKey={filter}
            onChange={(key) => { setFilter(key as 'all' | 'pinned'); }}
            className="!mb-0"
            items={[
              { key: 'all', label: t('blackboard.allPosts') },
              { key: 'pinned', label: t('blackboard.pinnedOnly') },
            ]}
          />
          {!isCreating && (
            <Button type="primary" onClick={() => { setIsCreating(true); }}>
              {t('blackboard.newPost')}
            </Button>
          )}
        </div>

        {isCreating && (
          <Card size="small" className="mb-4 bg-gray-50">
            <Form form={form} layout="vertical" onFinish={handleCreate}>
              <Form.Item
                name="title"
                rules={[{ required: true, message: t('blackboard.required') }]}
              >
                <Input placeholder={t('blackboard.postTitle')} />
              </Form.Item>
              <Form.Item
                name="content"
                rules={[{ required: true, message: t('blackboard.required') }]}
                className="mb-2"
              >
                <Input.TextArea rows={3} placeholder={t('blackboard.postContent')} />
              </Form.Item>
              <div className="flex justify-end gap-2">
                <Button disabled={loading} onClick={() => { setIsCreating(false); }}>{t('blackboard.cancel')}</Button>
                <Button type="primary" htmlType="submit" loading={loading} disabled={loading}>
                  {t('blackboard.createPost')}
                </Button>
              </div>
            </Form>
          </Card>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-2">
        {loading && posts.length === 0 ? (
          <div className="flex justify-center p-8">
            <Spin />
          </div>
        ) : filteredPosts.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center p-6">
            <Empty 
              description={t('blackboard.noPosts', 'No posts yet')} 
              className="mb-4"
            />
            {!isCreating && (
              <Button type="primary" onClick={() => { setIsCreating(true); }}>
                {t('blackboard.createPost', 'Create Post')}
              </Button>
            )}
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {filteredPosts.map((post) => {
              const isSelected = selectedPost?.id === post.id;
              return (
                <button
                  type="button"
                  key={post.id}
                  onClick={() => { selectPost(post); }}
                  className={`w-full text-left cursor-pointer rounded-lg border p-3 transition-all outline-none focus:ring-2 focus:ring-blue-500/20 ${
                    isSelected
                      ? 'border-blue-500 bg-blue-50'
                      : 'border-transparent hover:border-gray-200 hover:bg-gray-50'
                  }`}
                >
                  <div className="mb-1 flex items-start justify-between">
                    <Text strong className="line-clamp-1 flex-1">
                      {post.title}
                    </Text>
                    {post.is_pinned && (
                      <PushpinOutlined className="ml-2 mt-1 text-blue-500" />
                    )}
                  </div>
                  <Text className="line-clamp-2 text-sm text-gray-500">
                    {post.content}
                  </Text>
                  <div className="mt-2 flex items-center justify-between text-xs text-gray-400">
                    <Space size="small">
                      <MessageOutlined />
                      <span>{formatDateOnly(post.created_at)}</span>
                    </Space>
                    {post.status === 'archived' && (
                      <Tag color="default" className="!mr-0">
                        {t('blackboard.archived')}
                      </Tag>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </Card>
  );
};
