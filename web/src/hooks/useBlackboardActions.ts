import { useCallback } from 'react';

import { useTranslation } from 'react-i18next';

import { useWorkspaceActions } from '@/stores/workspace';

import { useLazyMessage } from '@/components/ui/lazyAntd';

interface BlackboardActionDeps {
  tenantId: string | undefined;
  projectId: string | undefined;
  selectedWorkspaceId: string | null;
}

export function useBlackboardPageActions({
  tenantId,
  projectId,
  selectedWorkspaceId,
}: BlackboardActionDeps) {
  const { t } = useTranslation();
  const message = useLazyMessage();
  const {
    createPost,
    updatePost,
    loadReplies,
    createReply,
    updateReply,
    deletePost,
    pinPost,
    unpinPost,
    deleteReply,
  } = useWorkspaceActions();

  const handleCreatePost = useCallback(
    async (data: { title: string; content: string }) => {
      if (!tenantId || !projectId || !selectedWorkspaceId) {
        return false;
      }

      try {
        await createPost(tenantId, projectId, selectedWorkspaceId, data);
        return true;
      } catch (_createError) {
        message?.error(t('blackboard.errors.createPost', 'Failed to create post'));
        return false;
      }
    },
    [createPost, message, projectId, selectedWorkspaceId, t, tenantId]
  );

  const handleCreateReply = useCallback(
    async (postId: string, content: string) => {
      if (!tenantId || !projectId || !selectedWorkspaceId) {
        return false;
      }

      try {
        await createReply(tenantId, projectId, selectedWorkspaceId, postId, { content });
        return true;
      } catch (_createError) {
        message?.error(t('blackboard.errors.createReply', 'Failed to create reply'));
        return false;
      }
    },
    [createReply, message, projectId, selectedWorkspaceId, t, tenantId]
  );

  const handleUpdatePost = useCallback(
    async (postId: string, data: { title: string; content: string }) => {
      if (!tenantId || !projectId || !selectedWorkspaceId) {
        return false;
      }

      try {
        await updatePost(tenantId, projectId, selectedWorkspaceId, postId, data);
        return true;
      } catch (_updateError) {
        message?.error(t('blackboard.errors.updatePost', 'Failed to update post'));
        return false;
      }
    },
    [message, projectId, selectedWorkspaceId, t, tenantId, updatePost]
  );

  const handleUpdateReply = useCallback(
    async (postId: string, replyId: string, content: string) => {
      if (!tenantId || !projectId || !selectedWorkspaceId) {
        return false;
      }

      try {
        await updateReply(tenantId, projectId, selectedWorkspaceId, postId, replyId, { content });
        return true;
      } catch (_updateError) {
        message?.error(t('blackboard.errors.updateReply', 'Failed to update reply'));
        return false;
      }
    },
    [message, projectId, selectedWorkspaceId, t, tenantId, updateReply]
  );

  const handleLoadReplies = useCallback(
    async (postId: string) => {
      if (!tenantId || !projectId || !selectedWorkspaceId) {
        return false;
      }

      try {
        await loadReplies(tenantId, projectId, selectedWorkspaceId, postId);
        return true;
      } catch (_loadError) {
        message?.error(t('blackboard.errors.loadReplies', 'Failed to load replies'));
        return false;
      }
    },
    [loadReplies, message, projectId, selectedWorkspaceId, t, tenantId]
  );

  const handleDeletePost = useCallback(
    async (postId: string) => {
      if (!tenantId || !projectId || !selectedWorkspaceId) {
        return false;
      }

      try {
        await deletePost(tenantId, projectId, selectedWorkspaceId, postId);
        return true;
      } catch (_deleteError) {
        message?.error(t('blackboard.errors.deletePost', 'Failed to delete post'));
        return false;
      }
    },
    [deletePost, message, projectId, selectedWorkspaceId, t, tenantId]
  );

  const handlePinPost = useCallback(
    async (postId: string) => {
      if (!tenantId || !projectId || !selectedWorkspaceId) {
        return;
      }

      try {
        await pinPost(tenantId, projectId, selectedWorkspaceId, postId);
      } catch (_pinError) {
        message?.error(t('blackboard.errors.pinPost', 'Failed to pin post'));
        return;
      }
    },
    [message, pinPost, projectId, selectedWorkspaceId, t, tenantId]
  );

  const handleUnpinPost = useCallback(
    async (postId: string) => {
      if (!tenantId || !projectId || !selectedWorkspaceId) {
        return;
      }

      try {
        await unpinPost(tenantId, projectId, selectedWorkspaceId, postId);
      } catch (_unpinError) {
        message?.error(t('blackboard.errors.unpinPost', 'Failed to unpin post'));
        return;
      }
    },
    [message, projectId, selectedWorkspaceId, t, tenantId, unpinPost]
  );

  const handleDeleteReply = useCallback(
    async (postId: string, replyId: string) => {
      if (!tenantId || !projectId || !selectedWorkspaceId) {
        return;
      }

      try {
        await deleteReply(tenantId, projectId, selectedWorkspaceId, postId, replyId);
      } catch (_deleteError) {
        message?.error(t('blackboard.errors.deleteReply', 'Failed to delete reply'));
        return;
      }
    },
    [deleteReply, message, projectId, selectedWorkspaceId, t, tenantId]
  );

  return {
    handleCreatePost,
    handleCreateReply,
    handleUpdatePost,
    handleUpdateReply,
    handleLoadReplies,
    handleDeletePost,
    handlePinPost,
    handleUnpinPost,
    handleDeleteReply,
  };
}
