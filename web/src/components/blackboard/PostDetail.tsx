import type React from 'react';
import { useEffect } from 'react';

import { useTranslation } from 'react-i18next';

import { PushpinOutlined, PushpinFilled, DeleteOutlined } from '@ant-design/icons';
import {
  Button,
  Input,
  Form,
  Popconfirm,
} from 'antd';

import {
  useSelectedPost,
  useBlackboardReplies,
  useBlackboardActions,
  useBlackboardLoading,
} from '@/stores/blackboard';

import { formatDateTime } from '@/utils/date';


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
      <div className="flex h-full items-center justify-center rounded-xl border border-border-light bg-surface-muted dark:border-border-dark dark:bg-surface-dark">
        <div className="flex flex-col items-center justify-center p-8 text-center">
          <p className="text-sm text-text-muted">
            {t('blackboard.selectPost', 'Select a post to view details')}
          </p>
        </div>
      </div>
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
    <div className="flex h-full flex-col rounded-xl border border-border-light bg-surface-light dark:border-border-dark dark:bg-surface-dark">
      <div className="flex h-full flex-col">
        <div className="flex-1 overflow-y-auto p-6">
          <div className="mb-6 flex items-start justify-between gap-4">
            <div className="flex-1">
              <h4 className="mb-2 text-lg font-semibold text-text-primary dark:text-text-inverse">
                {selectedPost.title}
              </h4>
              <div className="flex items-center gap-3 text-sm text-text-secondary">
                <span className="font-medium">{selectedPost.author_id}</span>
                <span className="text-text-muted">&bull;</span>
                <span>{formatDateTime(selectedPost.created_at)}</span>
                {selectedPost.status === 'archived' && (
                  <span className="rounded-full bg-surface-muted px-2 py-0.5 text-[11px] text-text-muted dark:bg-surface-dark-alt">
                    {t('blackboard.archived')}
                  </span>
                )}
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <Button
                type="text"
                className="transition-colors hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
                icon={selectedPost.is_pinned ? <PushpinFilled className="text-primary" /> : <PushpinOutlined className="text-text-muted hover:text-text-primary dark:hover:text-text-inverse" />}
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
                  className="transition-colors hover:bg-error/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
                />
              </Popconfirm>
            </div>
          </div>

          <p className="whitespace-pre-wrap text-sm leading-7 text-text-secondary dark:text-text-muted">
            {selectedPost.content}
          </p>

          <hr className="my-6 border-border-light dark:border-border-dark" />

          <div>
            <h5 className="mb-4 text-base font-semibold text-text-secondary">
              {t('blackboard.replies')} ({replies.length})
            </h5>

            {loading && replies.length === 0 ? (
              <div className="flex justify-center p-8">
                <div className="h-5 w-5 animate-spin rounded-full border-2 border-border-light border-t-primary" />
              </div>
            ) : replies.length === 0 ? (
              <div className="flex flex-col items-center justify-center p-8 text-center">
                <p className="text-sm text-text-muted">
                  {t('blackboard.noReplies', 'No replies yet')}
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                {replies.map((reply) => (
                  <article
                    key={reply.id}
                    className="group -mx-4 rounded-lg px-4 py-4 transition-colors hover:bg-surface-muted/80 dark:hover:bg-surface-dark-alt/80"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-3 text-sm text-text-secondary">
                          <span className="font-medium text-text-primary dark:text-text-inverse">
                            {reply.author_id}
                          </span>
                          <span className="text-text-muted">&bull;</span>
                          <span>{formatDateTime(reply.created_at)}</span>
                        </div>
                        <p className="mt-2 whitespace-pre-wrap text-sm leading-7 text-text-secondary dark:text-text-muted">
                          {reply.content}
                        </p>
                      </div>
                      <Popconfirm
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
                          className="opacity-0 transition-all hover:bg-error/10 group-hover:opacity-100 group-focus-within:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
                          aria-label={t('blackboard.delete', 'Delete')}
                        />
                      </Popconfirm>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="border-t border-border-light bg-surface-muted p-4 dark:border-border-dark dark:bg-surface-dark-alt">
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
    </div>
  );
};
