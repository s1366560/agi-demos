import { useTranslation } from 'react-i18next';

import { Button, Input, Popconfirm } from 'antd';

import { formatDateTime } from '@/utils/date';

import type { BlackboardPost, BlackboardReply } from '@/types/workspace';


const { TextArea } = Input;

function getAuthorDisplay(authorId: string | null | undefined, fallback: string): string {
  const normalized = authorId?.trim();
  return normalized && normalized.length > 0 ? normalized : fallback;
}

export interface DiscussionTabProps {
  posts: BlackboardPost[];
  selectedPostId: string | null;
  setSelectedPostId: (id: string | null) => void;
  postTitle: string;
  setPostTitle: (v: string) => void;
  postContent: string;
  setPostContent: (v: string) => void;
  replyDraft: string;
  setReplyDraft: (v: string) => void;
  creatingPost: boolean;
  replying: boolean;
  deletingPostId: string | null;
  deletingReplyId: string | null;
  togglingPostId: string | null;
  loadingRepliesPostId: string | null;
  loadedReplyPostIds: Record<string, boolean>;
  repliesByPostId: Record<string, BlackboardReply[]>;
  handleCreatePost: () => Promise<void>;
  handleCreateReply: () => Promise<void>;
  handleTogglePin: () => Promise<void>;
  handleDeleteSelectedPost: () => Promise<void>;
  handleDeleteSelectedReply: (replyId: string) => Promise<void>;
  handleLoadReplies: (postId: string, options?: { manual?: boolean }) => Promise<void>;
}

export function DiscussionTab({
  posts,
  selectedPostId,
  setSelectedPostId,
  postTitle,
  setPostTitle,
  postContent,
  setPostContent,
  replyDraft,
  setReplyDraft,
  creatingPost,
  replying,
  deletingPostId,
  deletingReplyId,
  togglingPostId,
  loadingRepliesPostId,
  loadedReplyPostIds,
  repliesByPostId,
  handleCreatePost,
  handleCreateReply,
  handleTogglePin,
  handleDeleteSelectedPost,
  handleDeleteSelectedReply,
  handleLoadReplies,
}: DiscussionTabProps) {
  const { t } = useTranslation();

  const selectedPost = posts.find((post) => post.id === selectedPostId) ?? null;
  const selectedReplies = selectedPost ? (repliesByPostId[selectedPost.id] ?? []) : [];
  const selectedRepliesLoaded = selectedPost ? loadedReplyPostIds[selectedPost.id] === true : false;

  return (
    <div className="grid gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
      <section className="min-w-0 space-y-4">
        <div className="rounded-3xl border border-border-light bg-surface-muted p-4 dark:border-border-dark dark:bg-surface-dark-alt">
          <h3 className="text-lg font-semibold text-text-primary dark:text-text-inverse">
            {t('blackboard.newPost', 'New Post')}
          </h3>
          <div className="mt-4 space-y-3">
            <label
              htmlFor="blackboard-post-title"
              className="block text-[11px] font-medium uppercase tracking-[0.16em] text-text-muted dark:text-text-muted"
            >
              {t('blackboard.postTitle', 'Title')}
            </label>
            <Input
              id="blackboard-post-title"
              value={postTitle}
              aria-label={t('blackboard.postTitle', 'Title')}
              onChange={(event) => {
                setPostTitle(event.target.value);
              }}
              placeholder={t('blackboard.postTitle', 'Title')}
              maxLength={200}
              className="min-h-11"
            />
            <label
              htmlFor="blackboard-post-content"
              className="block text-[11px] font-medium uppercase tracking-[0.16em] text-text-muted dark:text-text-muted"
            >
              {t('blackboard.postContent', 'Content')}
            </label>
            <TextArea
              id="blackboard-post-content"
              value={postContent}
              aria-label={t('blackboard.postContent', 'Content')}
              onChange={(event) => {
                setPostContent(event.target.value);
              }}
              placeholder={t('blackboard.postContent', 'Content')}
              rows={5}
              maxLength={2000}
              showCount
            />
            <Button
              type="primary"
              onClick={() => {
                void handleCreatePost();
              }}
              disabled={creatingPost || !postTitle.trim() || !postContent.trim()}
              loading={creatingPost}
              className="min-h-11 w-full sm:w-auto"
            >
              {t('blackboard.createPost', 'Create Post')}
            </Button>
          </div>
        </div>

        <div className="space-y-3">
          {posts.map((post) => (
            <button
              type="button"
              key={post.id}
              onClick={() => {
                setSelectedPostId(post.id);
              }}
              className={`w-full rounded-3xl border p-4 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 ${
                selectedPostId === post.id
                  ? 'border-primary/30 bg-primary/8'
                  : 'border-border-light bg-surface-muted hover:border-border-separator hover:bg-surface-light dark:border-border-dark dark:bg-surface-dark-alt dark:hover:border-border-dark dark:hover:bg-surface-elevated'
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h4 className="truncate text-sm font-semibold text-text-primary dark:text-text-inverse">
                    {post.title}
                  </h4>
                  <p className="mt-2 line-clamp-3 break-words text-sm leading-6 text-text-secondary dark:text-text-muted">
                    {post.content}
                  </p>
                </div>
                {post.is_pinned && (
                  <span className="rounded-full border border-primary/25 bg-primary/10 px-2 py-1 text-[11px] text-primary dark:text-primary-200">
                    {t('blackboard.pinned', 'Pinned')}
                  </span>
                )}
              </div>
              <div className="mt-3 flex items-center justify-between gap-3 text-xs text-text-muted dark:text-text-muted">
                <span>{formatDateTime(post.created_at)}</span>
                <span>
                  {loadedReplyPostIds[post.id]
                    ? `${String((repliesByPostId[post.id] ?? []).length)} ${t('blackboard.replies', 'Replies')}`
                    : t('blackboard.open', 'Open')}
                </span>
              </div>
            </button>
          ))}

          {posts.length === 0 && (
            <div className="rounded-3xl border border-dashed border-border-separator bg-surface-light p-6 text-sm text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted">
              {t('blackboard.noPosts', 'No posts yet')}
            </div>
          )}
        </div>
      </section>

      <section className="min-w-0 rounded-3xl border border-border-light bg-surface-light p-5 dark:border-border-dark dark:bg-surface-dark-alt">
        {selectedPost ? (
          <div className="space-y-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="text-[11px] uppercase tracking-[0.16em] text-text-muted dark:text-text-muted">
                  {t('blackboard.createdBy', 'Created by')}
                </div>
                <div className="mt-1 break-all text-xs font-medium text-text-secondary dark:text-text-secondary">
                  {getAuthorDisplay(
                    selectedPost.author_id,
                    t('blackboard.unknownAuthor', 'Unknown author')
                  )}
                </div>
                <h3 className="mt-2 break-words text-2xl font-semibold text-text-primary dark:text-text-inverse">
                  {selectedPost.title}
                </h3>
              </div>
              <div className="rounded-full border border-border-light bg-surface-muted px-3 py-1.5 text-xs text-text-muted dark:border-border-dark dark:bg-surface-dark dark:text-text-muted">
                {formatDateTime(selectedPost.created_at)}
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => {
                  void handleTogglePin();
                }}
                disabled={togglingPostId === selectedPost.id}
                className="min-h-10 rounded-2xl border border-border-light bg-surface-muted px-4 text-sm text-text-primary transition hover:border-primary/30 hover:bg-primary/8 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-border-dark dark:bg-surface-dark-alt dark:text-text-inverse"
              >
                {selectedPost.is_pinned
                  ? t('blackboard.unpin', 'Unpin')
                  : t('blackboard.pin', 'Pin')}
              </button>

              <Popconfirm
                title={t('blackboard.deleteConfirm', 'Are you sure you want to delete this post?')}
                okText={t('common.yes', 'Yes')}
                cancelText={t('common.no', 'No')}
                onConfirm={() => {
                  void handleDeleteSelectedPost();
                }}
              >
                <button
                  type="button"
                  disabled={deletingPostId === selectedPost.id}
                  className="min-h-10 rounded-2xl border border-error/25 bg-error/10 px-4 text-sm text-status-text-error transition hover:bg-error/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 disabled:cursor-not-allowed disabled:opacity-60 dark:text-status-text-error-dark"
                >
                  {t('blackboard.delete', 'Delete')}
                </button>
              </Popconfirm>
            </div>

            <article className="rounded-3xl border border-border-light bg-surface-muted p-5 text-sm leading-7 text-text-secondary dark:border-border-dark dark:bg-surface-dark-alt dark:text-text-secondary">
              {selectedPost.content}
            </article>

            <div>
              <div className="mb-3 flex items-center justify-between gap-3">
                <h4 className="text-base font-semibold text-text-primary dark:text-text-inverse">
                  {t('blackboard.replies', 'Replies')}
                </h4>
                <span className="text-xs text-text-muted dark:text-text-muted">
                  {String(selectedReplies.length)}
                </span>
              </div>

              <div className="space-y-3">
                {!selectedRepliesLoaded && loadingRepliesPostId === selectedPost.id && (
                  <div className="rounded-3xl border border-border-light bg-surface-muted px-4 py-5 text-sm text-text-secondary dark:border-border-dark dark:bg-surface-dark-alt dark:text-text-muted">
                    {t('common.loading', 'Loading...')}
                  </div>
                )}

                {!selectedRepliesLoaded && loadingRepliesPostId !== selectedPost.id && (
                  <div className="rounded-3xl border border-dashed border-border-separator bg-surface-light p-5 text-sm text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted">
                    <div>
                      {t('blackboard.repliesUnavailable', 'Replies are not loaded yet.')}
                    </div>
                    <button
                      type="button"
                      onClick={() => {
                        void handleLoadReplies(selectedPost.id, { manual: true });
                      }}
                      className="mt-3 rounded-2xl border border-border-light px-4 py-2 text-sm text-text-primary transition hover:border-primary/30 hover:bg-primary/8 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 dark:border-border-dark dark:text-text-inverse"
                    >
                      {t('blackboard.retryReplies', 'Retry loading replies')}
                    </button>
                  </div>
                )}

                {selectedRepliesLoaded &&
                  selectedReplies.map((reply) => (
                    <article
                      key={reply.id}
                      className="rounded-3xl border border-border-light bg-surface-muted p-4 dark:border-border-dark dark:bg-surface-dark-alt"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="text-[11px] uppercase tracking-[0.16em] text-text-muted dark:text-text-muted">
                            {t('blackboard.createdBy', 'Created by')}
                          </div>
                          <div className="mt-1 break-all text-sm font-medium text-text-primary dark:text-text-inverse">
                            {getAuthorDisplay(
                              reply.author_id,
                              t('blackboard.unknownAuthor', 'Unknown author')
                            )}
                          </div>
                          <div className="mt-1 text-xs text-text-muted dark:text-text-muted">
                            {formatDateTime(reply.created_at)}
                          </div>
                        </div>
                        <Popconfirm
                          title={t('blackboard.deleteReplyConfirm', 'Are you sure you want to delete this reply?')}
                          okText={t('common.yes', 'Yes')}
                          cancelText={t('common.no', 'No')}
                          onConfirm={() => {
                            void handleDeleteSelectedReply(reply.id);
                          }}
                        >
                          <button
                            type="button"
                            disabled={deletingReplyId === reply.id}
                            className="rounded-xl border border-border-light px-3 py-2 text-xs text-text-secondary transition hover:border-error/25 hover:bg-error/10 hover:text-status-text-error focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-border-dark dark:text-text-secondary dark:hover:text-status-text-error-dark"
                          >
                            {t('blackboard.delete', 'Delete')}
                          </button>
                        </Popconfirm>
                      </div>
                      <p className="mt-3 whitespace-pre-wrap break-words text-sm leading-6 text-text-secondary dark:text-text-muted">
                        {reply.content}
                      </p>
                    </article>
                  ))}

                {selectedRepliesLoaded && selectedReplies.length === 0 && (
                  <div className="rounded-3xl border border-dashed border-border-separator bg-surface-light p-5 text-sm text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted">
                    {t('blackboard.noReplies', 'No replies yet')}
                  </div>
                )}
              </div>
            </div>

            <div className="rounded-3xl border border-border-light bg-surface-muted p-4 dark:border-border-dark dark:bg-surface-dark-alt">
              <h4 className="text-sm font-semibold text-text-primary dark:text-text-inverse">
                {t('blackboard.reply', 'Reply')}
              </h4>
              <label
                htmlFor="blackboard-reply-draft"
                className="mt-3 block text-xs font-medium uppercase tracking-[0.16em] text-text-muted dark:text-text-muted"
              >
                {t('blackboard.writeReply', 'Write a reply...')}
              </label>
              <TextArea
                id="blackboard-reply-draft"
                value={replyDraft}
                aria-label={t('blackboard.writeReply', 'Write a reply...')}
                onChange={(event) => {
                  setReplyDraft(event.target.value);
                }}
                placeholder={t('blackboard.writeReply', 'Write a reply...')}
                rows={4}
                maxLength={1000}
                showCount
                className="mt-3"
              />
              <div className="mt-3 flex justify-end">
                <Button
                  type="primary"
                  onClick={() => {
                    void handleCreateReply();
                  }}
                  disabled={replying || !replyDraft.trim()}
                  loading={replying}
                  className="min-h-11"
                >
                  {t('blackboard.sendReply', 'Send')}
                </Button>
              </div>
            </div>
          </div>
        ) : (
          <div className="flex min-h-[320px] items-center justify-center rounded-3xl border border-dashed border-border-separator bg-surface-light text-sm text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted">
            {t('blackboard.selectPost', 'Select a post to view details')}
          </div>
        )}
      </section>
    </div>
  );
}
