import { describe, expect, it, vi } from 'vitest';

import { DiscussionTab } from '@/components/blackboard/tabs/DiscussionTab';
import { render, screen } from '@/test/utils';

describe('DiscussionTab', () => {
  it('marks discussion as an owned authoritative surface', () => {
    render(
      <DiscussionTab
        posts={[]}
        selectedPostId={null}
        setSelectedPostId={vi.fn()}
        postTitle=""
        setPostTitle={vi.fn()}
        postContent=""
        setPostContent={vi.fn()}
        replyDraft=""
        setReplyDraft={vi.fn()}
        creatingPost={false}
        replying={false}
        deletingPostId={null}
        deletingReplyId={null}
        togglingPostId={null}
        loadingRepliesPostId={null}
        loadedReplyPostIds={{}}
        repliesByPostId={{}}
        handleCreatePost={vi.fn()}
        handleCreateReply={vi.fn()}
        handleTogglePin={vi.fn()}
        handleDeleteSelectedPost={vi.fn()}
        handleDeleteSelectedReply={vi.fn()}
        handleLoadReplies={vi.fn()}
      />
    );

    const boundaryBadge = screen.getByText('blackboard.discussionSurfaceHint').closest('div');
    expect(boundaryBadge).toHaveAttribute('data-blackboard-boundary', 'owned');
    expect(boundaryBadge).toHaveAttribute('data-blackboard-authority', 'authoritative');
  });
});
