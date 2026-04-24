import { useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Input, Popconfirm } from 'antd';

import { formatDateTime } from '@/utils/date';

import { EmptyState } from '../EmptyState';
import { OwnedSurfaceBadge } from '../OwnedSurfaceBadge';

import type { BlackboardPost, BlackboardReply } from '@/types/workspace';


const { TextArea } = Input;

function getAuthorDisplay(authorId: string | null | undefined, fallback: string): string {
  const normalized = authorId?.trim();
  return normalized && normalized.length > 0 ? normalized : fallback;
}

function getAuthorTag(authorId: string | null | undefined): string {
  const raw = authorId?.trim() ?? '';
  if (!raw) return '?';
  if (raw.includes('@')) return raw.split('@')[0]?.slice(0, 8) ?? '?';
  return raw.slice(0, 8);
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

/* ------------------------------------------------------------------ */
/*  BBS Thread List View                                              */
/* ------------------------------------------------------------------ */

function ThreadListView({
  posts,
  loadedReplyPostIds,
  repliesByPostId,
  showCompose,
  onToggleCompose,
  onSelectPost,
  postTitle,
  setPostTitle,
  postContent,
  setPostContent,
  creatingPost,
  handleCreatePost,
  t,
}: {
  posts: BlackboardPost[];
  loadedReplyPostIds: Record<string, boolean>;
  repliesByPostId: Record<string, BlackboardReply[]>;
  showCompose: boolean;
  onToggleCompose: () => void;
  onSelectPost: (id: string) => void;
  postTitle: string;
  setPostTitle: (v: string) => void;
  postContent: string;
  setPostContent: (v: string) => void;
  creatingPost: boolean;
  handleCreatePost: () => Promise<void>;
  t: (key: string, fallback: string) => string;
}) {
  const pinnedPosts = posts.filter((p) => p.is_pinned);
  const normalPosts = posts.filter((p) => !p.is_pinned);

  return (
    <div className="space-y-0">
      {/* BBS header bar */}
      <div className="flex items-center justify-between border-b border-border-light pb-3 dark:border-border-dark">
        <div className="min-w-0">
          <h3 className="text-base font-semibold text-text-primary dark:text-text-inverse">
            {t('blackboard.discussionPosts', 'Threads')}
          </h3>
          <div className="mt-2">
            <OwnedSurfaceBadge
              labelKey="blackboard.discussionSurfaceHint"
              fallbackLabel="blackboard discussion content"
            />
          </div>
        </div>
        <button
          type="button"
          onClick={onToggleCompose}
          className="rounded-full bg-primary px-4 py-1.5 text-xs font-medium text-white transition motion-reduce:transition-none hover:bg-primary-dark active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
        >
          {showCompose
            ? t('common.cancel', 'Cancel')
            : `+ ${t('blackboard.createPost', 'New Thread')}`}
        </button>
      </div>

      {/* Compose form (collapsible) */}
      {showCompose && (
        <div className="border-b border-border-light bg-surface-muted/50 px-4 py-4 dark:border-border-dark dark:bg-surface-dark-alt/50">
          <div className="space-y-3">
            <Input
              id="blackboard-post-title"
              value={postTitle}
              aria-label={t('blackboard.postTitle', 'Title')}
              onChange={(event) => {
                setPostTitle(event.target.value);
              }}
              placeholder={t('blackboard.postTitle', 'Title')}
              maxLength={200}
              className="min-h-10"
            />
            <TextArea
              id="blackboard-post-content"
              value={postContent}
              aria-label={t('blackboard.postContent', 'Content')}
              onChange={(event) => {
                setPostContent(event.target.value);
              }}
              placeholder={t('blackboard.postContent', 'Content')}
              rows={4}
              maxLength={2000}
              showCount
            />
            <div className="flex justify-end">
              <button
                type="button"
                onClick={() => {
                  void handleCreatePost();
                }}
                disabled={creatingPost || !postTitle.trim() || !postContent.trim()}
                className="rounded-full bg-primary px-5 py-2 text-sm font-medium text-white transition motion-reduce:transition-none hover:bg-primary-dark active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {creatingPost
                  ? t('common.loading', 'Loading\u2026')
                  : t('blackboard.createPost', 'Post')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* BBS table header */}
      <div className="grid grid-cols-[1fr_80px_160px] items-center border-b border-border-light bg-surface-muted/60 px-4 py-2 text-[11px] font-medium uppercase tracking-wider text-text-muted dark:border-border-dark dark:bg-surface-dark-alt/60 dark:text-text-muted">
        <span>{t('blackboard.postTitle', 'Title')}</span>
        <span className="text-center">{t('blackboard.replies', 'Replies')}</span>
        <span className="text-right">{t('blackboard.date', 'Date')}</span>
      </div>

      {/* Pinned threads */}
      {pinnedPosts.map((post) => (
        <ThreadRow
          key={post.id}
          post={post}
          replyCount={
            loadedReplyPostIds[post.id] ? (repliesByPostId[post.id] ?? []).length : null
          }
          pinned
          onClick={() => {
            onSelectPost(post.id);
          }}
        />
      ))}

      {/* Normal threads */}
      {normalPosts.map((post) => (
        <ThreadRow
          key={post.id}
          post={post}
          replyCount={
            loadedReplyPostIds[post.id] ? (repliesByPostId[post.id] ?? []).length : null
          }
          pinned={false}
          onClick={() => {
            onSelectPost(post.id);
          }}
        />
      ))}

      {posts.length === 0 && (
        <div className="py-6">
          <EmptyState>{t('blackboard.noPosts', 'No threads yet')}</EmptyState>
        </div>
      )}
    </div>
  );
}

function ThreadRow({
  post,
  replyCount,
  pinned,
  onClick,
}: {
  post: BlackboardPost;
  replyCount: number | null;
  pinned: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="group grid w-full grid-cols-[1fr_80px_160px] items-center border-b border-border-light/60 px-4 py-3 text-left transition-colors motion-reduce:transition-none hover:bg-surface-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-inset dark:border-border-dark/60 dark:hover:bg-surface-dark-alt/40"
    >
      <div className="min-w-0 pr-3">
        <div className="flex items-center gap-2">
          {pinned && (
            <span className="shrink-0 text-[10px] text-primary">&#x1F4CC;</span>
          )}
          <span className="truncate text-sm font-medium text-text-primary group-hover:text-primary dark:text-text-inverse dark:group-hover:text-primary-200">
            {post.title}
          </span>
        </div>
        <span className="mt-0.5 inline-block rounded bg-surface-muted px-1.5 py-0.5 text-[10px] text-text-muted dark:bg-surface-dark-alt dark:text-text-muted">
          {getAuthorTag(post.author_id)}
        </span>
      </div>
      <span className="text-center text-xs tabular-nums text-text-muted dark:text-text-muted">
        {replyCount !== null ? String(replyCount) : '-'}
      </span>
      <span className="text-right text-xs tabular-nums text-text-muted dark:text-text-muted">
        {formatDateTime(post.created_at)}
      </span>
    </button>
  );
}

/* ------------------------------------------------------------------ */
/*  BBS Thread Detail View                                            */
/* ------------------------------------------------------------------ */

function ThreadDetailView({
  post,
  replies,
  repliesLoaded,
  loadingRepliesPostId,
  replyDraft,
  setReplyDraft,
  replying,
  deletingPostId,
  deletingReplyId,
  togglingPostId,
  handleCreateReply,
  handleTogglePin,
  handleDeleteSelectedPost,
  handleDeleteSelectedReply,
  handleLoadReplies,
  onBack,
  t,
}: {
  post: BlackboardPost;
  replies: BlackboardReply[];
  repliesLoaded: boolean;
  loadingRepliesPostId: string | null;
  replyDraft: string;
  setReplyDraft: (v: string) => void;
  replying: boolean;
  deletingPostId: string | null;
  deletingReplyId: string | null;
  togglingPostId: string | null;
  handleCreateReply: () => Promise<void>;
  handleTogglePin: () => Promise<void>;
  handleDeleteSelectedPost: () => Promise<void>;
  handleDeleteSelectedReply: (replyId: string) => Promise<void>;
  handleLoadReplies: (postId: string, options?: { manual?: boolean }) => Promise<void>;
  onBack: () => void;
  t: (key: string, fallback: string) => string;
}) {
  return (
    <div className="space-y-0">
      {/* Back navigation */}
      <div className="flex items-center gap-3 border-b border-border-light pb-3 dark:border-border-dark">
        <button
          type="button"
          onClick={onBack}
          className="rounded-md px-2 py-1 text-xs text-text-muted transition hover:bg-surface-muted hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 dark:hover:bg-surface-dark-alt dark:hover:text-text-inverse"
        >
          &larr; {t('blackboard.backToList', 'Back')}
        </button>
        <span className="text-xs text-text-muted dark:text-text-muted">/</span>
        <span className="truncate text-xs text-text-secondary dark:text-text-muted">
          {post.title}
        </span>
      </div>

      {/* OP (Original Post) - floor #0 */}
      <div className="border-b border-border-light dark:border-border-dark">
        <div className="flex items-center justify-between bg-surface-muted/40 px-4 py-2 dark:bg-surface-dark-alt/40">
          <div className="flex items-center gap-3">
            <span className="rounded bg-text-primary/10 px-1.5 py-0.5 font-mono text-[10px] font-bold text-text-secondary dark:bg-white/10 dark:text-text-muted">
              #0
            </span>
            <span className="text-xs font-medium text-text-primary dark:text-text-inverse">
              {getAuthorDisplay(post.author_id, t('blackboard.unknownAuthor', 'Unknown'))}
            </span>
            {post.is_pinned && (
              <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary dark:text-primary-200">
                {t('blackboard.pinned', 'Pinned')}
              </span>
            )}
          </div>
          <span className="text-xs tabular-nums text-text-muted dark:text-text-muted">
            {formatDateTime(post.created_at)}
          </span>
        </div>
        <div className="px-4 py-4">
          <h2 className="text-lg font-semibold text-text-primary dark:text-text-inverse">
            {post.title}
          </h2>
          <article className="mt-3 whitespace-pre-wrap break-words text-sm leading-7 text-text-secondary dark:text-text-muted">
            {post.content}
          </article>
          <div className="mt-4 flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                void handleTogglePin();
              }}
              disabled={togglingPostId === post.id}
              className="rounded-md border border-border-light px-3 py-1 text-xs text-text-secondary transition hover:border-primary/30 hover:bg-primary/8 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-border-dark dark:text-text-muted dark:hover:text-primary-200"
            >
              {post.is_pinned ? t('blackboard.unpin', 'Unpin') : t('blackboard.pin', 'Pin')}
            </button>
            <Popconfirm
              title={t('blackboard.deleteConfirm', 'Delete this thread?')}
              okText={t('common.yes', 'Yes')}
              cancelText={t('common.no', 'No')}
              onConfirm={() => {
                void handleDeleteSelectedPost();
              }}
            >
              <button
                type="button"
                disabled={deletingPostId === post.id}
                className="rounded-md border border-error/20 px-3 py-1 text-xs text-status-text-error transition hover:bg-error/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 disabled:cursor-not-allowed disabled:opacity-60 dark:text-status-text-error-dark"
              >
                {t('blackboard.delete', 'Delete')}
              </button>
            </Popconfirm>
          </div>
        </div>
      </div>

      {/* Replies header */}
      <div className="flex items-center justify-between bg-surface-muted/40 px-4 py-2 dark:bg-surface-dark-alt/40">
        <span className="text-xs font-medium text-text-primary dark:text-text-inverse">
          {t('blackboard.replies', 'Replies')} ({String(replies.length)})
        </span>
      </div>

      {/* Loading / not loaded states */}
      {!repliesLoaded && loadingRepliesPostId === post.id && (
        <div className="px-4 py-6 text-center text-sm text-text-muted dark:text-text-muted">
          {t('common.loading', 'Loading...')}
        </div>
      )}

      {!repliesLoaded && loadingRepliesPostId !== post.id && (
        <div className="px-4 py-6 text-center">
          <div className="text-sm text-text-muted dark:text-text-muted">
            {t('blackboard.repliesUnavailable', 'Replies not loaded.')}
          </div>
          <button
            type="button"
            onClick={() => {
              void handleLoadReplies(post.id, { manual: true });
            }}
            className="mt-2 rounded-md border border-border-light px-3 py-1 text-xs text-text-primary transition hover:border-primary/30 hover:bg-primary/8 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 dark:border-border-dark dark:text-text-inverse"
          >
            {t('blackboard.retryReplies', 'Load replies')}
          </button>
        </div>
      )}

      {/* Reply floors */}
      {repliesLoaded &&
        replies.map((reply, index) => (
          <div
            key={reply.id}
            className="border-b border-border-light/60 dark:border-border-dark/60"
          >
            <div className="flex items-center justify-between bg-surface-muted/20 px-4 py-1.5 dark:bg-surface-dark-alt/20">
              <div className="flex items-center gap-3">
                <span className="rounded bg-text-primary/10 px-1.5 py-0.5 font-mono text-[10px] font-bold text-text-secondary dark:bg-white/10 dark:text-text-muted">
                  #{String(index + 1)}
                </span>
                <span className="text-xs font-medium text-text-primary dark:text-text-inverse">
                  {getAuthorDisplay(
                    reply.author_id,
                    t('blackboard.unknownAuthor', 'Unknown')
                  )}
                </span>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-xs tabular-nums text-text-muted dark:text-text-muted">
                  {formatDateTime(reply.created_at)}
                </span>
                <Popconfirm
                  title={t('blackboard.deleteReplyConfirm', 'Delete this reply?')}
                  okText={t('common.yes', 'Yes')}
                  cancelText={t('common.no', 'No')}
                  onConfirm={() => {
                    void handleDeleteSelectedReply(reply.id);
                  }}
                >
                  <button
                    type="button"
                    disabled={deletingReplyId === reply.id}
                    className="rounded px-1.5 py-0.5 text-[10px] text-text-muted transition hover:bg-error/10 hover:text-status-text-error focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 disabled:cursor-not-allowed disabled:opacity-60 dark:text-text-muted dark:hover:text-status-text-error-dark"
                  >
                    {t('blackboard.delete', 'Del')}
                  </button>
                </Popconfirm>
              </div>
            </div>
            <p className="whitespace-pre-wrap break-words px-4 py-3 text-sm leading-6 text-text-secondary dark:text-text-muted">
              {reply.content}
            </p>
          </div>
        ))}

      {repliesLoaded && replies.length === 0 && (
        <div className="py-6">
          <EmptyState>{t('blackboard.noReplies', 'No replies yet')}</EmptyState>
        </div>
      )}

      {/* Reply compose box */}
      <div className="border-t border-border-light px-4 py-4 dark:border-border-dark">
        <div className="flex gap-3">
          <TextArea
            id="blackboard-reply-draft"
            value={replyDraft}
            aria-label={t('blackboard.writeReply', 'Write a reply...')}
            onChange={(event) => {
              setReplyDraft(event.target.value);
            }}
            placeholder={t('blackboard.writeReply', 'Write a reply...')}
            rows={3}
            maxLength={1000}
            showCount
            className="flex-1"
          />
          <div className="flex shrink-0 flex-col justify-end">
            <button
              type="button"
              onClick={() => {
                void handleCreateReply();
              }}
              disabled={replying || !replyDraft.trim()}
              className="rounded-full bg-primary px-5 py-2 text-sm font-medium text-white transition motion-reduce:transition-none hover:bg-primary-dark active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {replying
                ? t('common.loading', 'Loading\u2026')
                : t('blackboard.sendReply', 'Reply')}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main DiscussionTab                                                */
/* ------------------------------------------------------------------ */

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
  const [showCompose, setShowCompose] = useState(false);

  const selectedPost = posts.find((post) => post.id === selectedPostId) ?? null;
  const selectedReplies = selectedPost ? (repliesByPostId[selectedPost.id] ?? []) : [];
  const selectedRepliesLoaded = selectedPost
    ? loadedReplyPostIds[selectedPost.id] === true
    : false;

  const handleSelectPost = (id: string) => {
    setSelectedPostId(id);
    void handleLoadReplies(id);
  };

  if (selectedPost) {
    return (
      <ThreadDetailView
        post={selectedPost}
        replies={selectedReplies}
        repliesLoaded={selectedRepliesLoaded}
        loadingRepliesPostId={loadingRepliesPostId}
        replyDraft={replyDraft}
        setReplyDraft={setReplyDraft}
        replying={replying}
        deletingPostId={deletingPostId}
        deletingReplyId={deletingReplyId}
        togglingPostId={togglingPostId}
        handleCreateReply={handleCreateReply}
        handleTogglePin={handleTogglePin}
        handleDeleteSelectedPost={handleDeleteSelectedPost}
        handleDeleteSelectedReply={handleDeleteSelectedReply}
        handleLoadReplies={handleLoadReplies}
        onBack={() => {
          setSelectedPostId(null);
        }}
        t={t}
      />
    );
  }

  return (
    <ThreadListView
      posts={posts}
      loadedReplyPostIds={loadedReplyPostIds}
      repliesByPostId={repliesByPostId}
      showCompose={showCompose}
      onToggleCompose={() => {
        setShowCompose((prev) => !prev);
      }}
      onSelectPost={handleSelectPost}
      postTitle={postTitle}
      setPostTitle={setPostTitle}
      postContent={postContent}
      setPostContent={setPostContent}
      creatingPost={creatingPost}
      handleCreatePost={async () => {
        await handleCreatePost();
        setShowCompose(false);
      }}
      t={t}
    />
  );
}
