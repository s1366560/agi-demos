import type React from 'react';
import { useState, useMemo } from 'react';

import { useTranslation } from 'react-i18next';

import { PushpinOutlined, MessageOutlined } from '@ant-design/icons';
import { Button, Input, Form } from 'antd';

import {
  useBlackboardPosts,
  useSelectedPost,
  useBlackboardActions,
  useBlackboardLoading,
} from '@/stores/blackboard';

import { formatDateOnly } from '@/utils/date';


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
    <div className="flex h-full flex-col rounded-xl border border-border-light bg-surface-light dark:border-border-dark dark:bg-surface-dark">
      <div className="border-b border-border-light p-4 dark:border-border-dark">
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-1 rounded-full bg-surface-muted p-1 dark:bg-surface-dark-alt">
            <button
              type="button"
              onClick={() => { setFilter('all'); }}
              className={`rounded-full px-3 py-1.5 text-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 ${
                filter === 'all'
                  ? 'bg-surface-light text-text-primary shadow-sm dark:bg-surface-dark dark:text-text-inverse'
                  : 'text-text-muted hover:text-text-primary dark:hover:text-text-inverse'
              }`}
            >
              {t('blackboard.allPosts')}
            </button>
            <button
              type="button"
              onClick={() => { setFilter('pinned'); }}
              className={`rounded-full px-3 py-1.5 text-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 ${
                filter === 'pinned'
                  ? 'bg-surface-light text-text-primary shadow-sm dark:bg-surface-dark dark:text-text-inverse'
                  : 'text-text-muted hover:text-text-primary dark:hover:text-text-inverse'
              }`}
            >
              {t('blackboard.pinnedOnly')}
            </button>
          </div>
          {!isCreating && (
            <Button type="primary" onClick={() => { setIsCreating(true); }}>
              {t('blackboard.newPost')}
            </Button>
          )}
        </div>

        {isCreating && (
          <div className="mb-4 rounded-xl border border-border-light bg-surface-muted p-4 dark:border-border-dark dark:bg-surface-dark-alt">
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
          </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-2">
        {loading && posts.length === 0 ? (
          <div className="flex justify-center p-8">
            <div className="h-5 w-5 animate-spin rounded-full border-2 border-border-light border-t-primary" />
          </div>
        ) : filteredPosts.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center p-8 text-center">
            <p className="text-sm text-text-muted">{t('blackboard.noPosts', 'No posts yet')}</p>
            {!isCreating && (
              <Button type="primary" className="mt-4" onClick={() => { setIsCreating(true); }}>
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
                  aria-pressed={isSelected}
                  onClick={() => { selectPost(post); }}
                  className={`w-full cursor-pointer rounded-lg border p-3 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 ${
                    isSelected
                      ? 'border-primary/40 bg-primary/8 dark:border-primary/30 dark:bg-primary/10'
                      : 'border-transparent hover:border-border-light hover:bg-surface-muted dark:hover:border-border-dark dark:hover:bg-surface-dark-alt'
                  }`}
                >
                  <div className="mb-1 flex items-start justify-between">
                    <span className="line-clamp-1 flex-1 font-semibold text-text-primary dark:text-text-inverse">
                      {post.title}
                    </span>
                    {post.is_pinned && (
                      <PushpinOutlined className="ml-2 mt-1 text-primary" />
                    )}
                  </div>
                  <p className="line-clamp-2 text-sm text-text-secondary dark:text-text-muted">
                    {post.content}
                  </p>
                  <div className="mt-2 flex items-center justify-between text-xs text-text-muted">
                    <div className="flex items-center gap-1.5">
                      <MessageOutlined />
                      <span>{formatDateOnly(post.created_at)}</span>
                    </div>
                    {post.status === 'archived' && (
                      <span className="rounded-full bg-surface-muted px-2 py-0.5 text-[11px] text-text-muted dark:bg-surface-dark-alt">
                        {t('blackboard.archived')}
                      </span>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};
