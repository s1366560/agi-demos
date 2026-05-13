import { describe, expect, it, vi } from 'vitest';

import { DiscussionTab } from '@/components/blackboard/tabs/DiscussionTab';
import { fireEvent, render, screen, waitFor } from '@/test/utils';

import type { DiscussionTabProps } from '@/components/blackboard/tabs/DiscussionTab';

function defaultProps(overrides: Partial<DiscussionTabProps> = {}): DiscussionTabProps {
  return {
    posts: [],
    selectedPostId: null,
    setSelectedPostId: vi.fn(),
    postTitle: '',
    setPostTitle: vi.fn(),
    postContent: '',
    setPostContent: vi.fn(),
    replyDraft: '',
    setReplyDraft: vi.fn(),
    creatingPost: false,
    replying: false,
    updatingPostId: null,
    updatingReplyId: null,
    deletingPostId: null,
    deletingReplyId: null,
    togglingPostId: null,
    loadingRepliesPostId: null,
    loadedReplyPostIds: {},
    repliesByPostId: {},
    handleCreatePost: vi.fn().mockResolvedValue(undefined),
    handleCreateReply: vi.fn().mockResolvedValue(undefined),
    handleUpdateSelectedPost: vi.fn().mockResolvedValue(true),
    handleUpdateSelectedReply: vi.fn().mockResolvedValue(true),
    handleTogglePin: vi.fn().mockResolvedValue(undefined),
    handleDeleteSelectedPost: vi.fn().mockResolvedValue(undefined),
    handleDeleteSelectedReply: vi.fn().mockResolvedValue(undefined),
    handleLoadReplies: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

describe('DiscussionTab', () => {
  it('marks discussion as an owned authoritative surface', () => {
    render(<DiscussionTab {...defaultProps()} />);

    const boundaryBadge = screen.getByText('blackboard.discussionSurfaceHint').closest('div');
    expect(boundaryBadge).toHaveAttribute('data-blackboard-boundary', 'owned');
    expect(boundaryBadge).toHaveAttribute('data-blackboard-authority', 'authoritative');
  });

  it('submits edited post title and content', async () => {
    const handleUpdateSelectedPost = vi.fn().mockResolvedValue(true);
    render(
      <DiscussionTab
        {...defaultProps({
          selectedPostId: 'post-1',
          posts: [
            {
              id: 'post-1',
              workspace_id: 'ws-1',
              author_id: 'user-1',
              title: 'Original title',
              content: 'Original content',
              status: 'open',
              is_pinned: false,
              metadata: {},
              created_at: '2026-03-30T10:00:00Z',
            },
          ],
          loadedReplyPostIds: { 'post-1': true },
          handleUpdateSelectedPost,
        })}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'blackboard.edit' }));
    fireEvent.change(screen.getByDisplayValue('Original title'), {
      target: { value: 'Updated title' },
    });
    fireEvent.change(screen.getByDisplayValue('Original content'), {
      target: { value: 'Updated content' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(handleUpdateSelectedPost).toHaveBeenCalledWith({
        title: 'Updated title',
        content: 'Updated content',
      });
    });
  });

  it('submits edited reply content', async () => {
    const handleUpdateSelectedReply = vi.fn().mockResolvedValue(true);
    render(
      <DiscussionTab
        {...defaultProps({
          selectedPostId: 'post-1',
          posts: [
            {
              id: 'post-1',
              workspace_id: 'ws-1',
              author_id: 'user-1',
              title: 'Question',
              content: 'Body',
              status: 'open',
              is_pinned: false,
              metadata: {},
              created_at: '2026-03-30T10:00:00Z',
            },
          ],
          loadedReplyPostIds: { 'post-1': true },
          repliesByPostId: {
            'post-1': [
              {
                id: 'reply-1',
                post_id: 'post-1',
                workspace_id: 'ws-1',
                author_id: 'user-2',
                content: 'Original reply',
                metadata: {},
                created_at: '2026-03-30T10:01:00Z',
              },
            ],
          },
          handleUpdateSelectedReply,
        })}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'blackboard.editReply' }));
    fireEvent.change(screen.getByDisplayValue('Original reply'), {
      target: { value: 'Updated reply' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(handleUpdateSelectedReply).toHaveBeenCalledWith('reply-1', 'Updated reply');
    });
  });
});
