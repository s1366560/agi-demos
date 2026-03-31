import { useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Button, Input } from 'antd';

import { useWorkspaceActions, useWorkspacePosts, useWorkspaceStore } from '@/stores/workspace';

import { useLazyMessage } from '@/components/ui/lazyAntd';

const { TextArea } = Input;

interface BlackboardPanelProps {
  tenantId: string;
  projectId: string;
  workspaceId: string;
}

export function BlackboardPanel({ tenantId, projectId, workspaceId }: BlackboardPanelProps) {
  const { t } = useTranslation();
  const message = useLazyMessage();
  const posts = useWorkspacePosts();
  const repliesByPostId = useWorkspaceStore((state) => state.repliesByPostId);
  const { createPost, createReply } = useWorkspaceActions();
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [replyDrafts, setReplyDrafts] = useState<Record<string, string>>({});
  const [isPostSubmitting, setIsPostSubmitting] = useState(false);
  const [replySubmitting, setReplySubmitting] = useState<string | null>(null);

  const onCreatePost = async () => {
    if (!title.trim() || !content.trim()) return;
    setIsPostSubmitting(true);
    try {
      await createPost(tenantId, projectId, workspaceId, {
        title: title.trim(),
        content: content.trim(),
      });
      setTitle('');
      setContent('');
    } catch (err) {
      console.error('Failed to create post', err);
      message?.error(t('workspaceDetail.blackboard.createPostFailed'));
    } finally {
      setIsPostSubmitting(false);
    }
  };

  const onCreateReply = async (postId: string) => {
    const draft = replyDrafts[postId]?.trim();
    if (!draft) return;
    setReplySubmitting(postId);
    try {
      await createReply(tenantId, projectId, workspaceId, postId, { content: draft });
      setReplyDrafts((prev) => ({ ...prev, [postId]: '' }));
    } catch (err) {
      console.error('Failed to create reply', err);
      message?.error(t('workspaceDetail.blackboard.createReplyFailed'));
    } finally {
      setReplySubmitting(null);
    }
  };

  return (
    <section className="rounded-lg border border-border-light p-4 bg-surface-light dark:border-border-dark dark:bg-surface-dark transition-colors duration-200">
      <h3 className="font-semibold text-text-primary dark:text-text-inverse mb-3">{t('workspaceDetail.blackboard.title')}</h3>
      <div className="grid gap-2 mb-3">
        <Input
          aria-label={t('workspaceDetail.blackboard.postTitle')}
          placeholder={t('workspaceDetail.blackboard.postTitle')}
          value={title}
          maxLength={200}
          onChange={(e) => {
            setTitle(e.target.value);
          }}
          className="px-3 py-2 text-sm"
        />
        <TextArea
          aria-label={t('workspaceDetail.blackboard.postContent')}
          placeholder={t('workspaceDetail.blackboard.postContent')}
          value={content}
          maxLength={2000}
          showCount
          onChange={(e) => {
            setContent(e.target.value);
          }}
          autoSize={{ minRows: 3 }}
          className="px-3 py-2 text-sm min-h-20"
        />
        <Button
          type="primary"
          className="w-fit focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1"
          onClick={() => void onCreatePost()}
          disabled={!title.trim() || !content.trim() || isPostSubmitting}
          loading={isPostSubmitting}
        >
          {t('workspaceDetail.blackboard.addPost')}
        </Button>
      </div>

      <div className="space-y-3">
        {posts.map((post) => {
          const replies = repliesByPostId[post.id] || [];
          return (
            <article key={post.id} className="border border-border-light dark:border-border-dark rounded p-3 transition-all duration-300">
              <h4 className="font-medium text-text-primary dark:text-text-inverse">{post.title}</h4>
              <p className="text-sm text-text-secondary dark:text-text-muted">{post.content}</p>
              <div className="text-xs text-text-muted mt-1">{t('workspaceDetail.blackboard.status')}: {post.status}</div>

              {replies.length > 0 && (
                <div className="mt-3 space-y-2 pl-2 border-l-2 border-border-subtle dark:border-border-dark">
                  {replies.map((reply) => (
                    <div key={reply.id} className="text-sm text-text-secondary dark:text-text-muted bg-surface-muted dark:bg-surface-dark-alt p-2 rounded">
                      {reply.content}
                    </div>
                  ))}
                </div>
              )}

              <div className="mt-2 flex gap-2">
                <Input
                  aria-label="Reply to post"
                  placeholder={t('workspaceDetail.blackboard.replyPlaceholder')}
                  value={replyDrafts[post.id] ?? ''}
                  maxLength={500}
                  onChange={(e) => {
                    setReplyDrafts((prev) => ({ ...prev, [post.id]: e.target.value }));
                  }}
                  className="px-2 py-1 text-sm flex-1"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      void onCreateReply(post.id);
                    }
                  }}
                />
                <Button
                  type="default"
                  className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1"
                  onClick={() => void onCreateReply(post.id)}
                  disabled={!replyDrafts[post.id]?.trim() || replySubmitting === post.id}
                  loading={replySubmitting === post.id}
                >
                  {t('workspaceDetail.blackboard.reply')}
                </Button>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
