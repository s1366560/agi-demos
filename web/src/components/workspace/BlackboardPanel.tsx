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
    } catch {
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
    } catch {
      message?.error(t('workspaceDetail.blackboard.createReplyFailed'));
    } finally {
      setReplySubmitting(null);
    }
  };

  return (
    <section className="rounded-xl border border-border-light bg-surface-light p-4 dark:border-border-dark dark:bg-surface-dark">
      <h3 className="mb-3 font-semibold text-text-primary dark:text-text-inverse">{t('workspaceDetail.blackboard.title')}</h3>
      <div className="mb-3 grid gap-2">
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
          className="min-h-20 px-3 py-2 text-sm"
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
            <article key={post.id} className="rounded-lg border border-border-light p-3 transition dark:border-border-dark">
              <h4 className="font-medium text-text-primary dark:text-text-inverse">{post.title}</h4>
              <p className="text-sm text-text-secondary dark:text-text-muted">{post.content}</p>
              <div className="mt-1 text-xs text-text-muted">{t('workspaceDetail.blackboard.status')}: {post.status}</div>

              {replies.length > 0 && (
                <div className="mt-3 space-y-2 border-l-2 border-border-subtle pl-2 dark:border-border-dark">
                  {replies.map((reply) => (
                    <div key={reply.id} className="rounded bg-surface-muted p-2 text-sm text-text-secondary dark:bg-surface-dark-alt dark:text-text-muted">
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
                  className="flex-1 px-2 py-1 text-sm"
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
