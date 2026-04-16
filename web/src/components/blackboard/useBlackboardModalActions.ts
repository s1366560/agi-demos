import { useCallback, useEffect, useState } from 'react';

import type { ObjectiveFormValues } from '@/components/workspace/objectives/ObjectiveCreateModal';

import type { BlackboardPost, CyberObjectiveType } from '@/types/workspace';

export interface BlackboardActionCallbacks {
  onLoadReplies: (postId: string) => Promise<boolean>;
  onCreatePost: (data: { title: string; content: string }) => Promise<boolean>;
  onCreateReply: (postId: string, content: string) => Promise<boolean>;
  onDeletePost: (postId: string) => Promise<boolean>;
  onPinPost: (postId: string) => Promise<void>;
  onUnpinPost: (postId: string) => Promise<void>;
  onDeleteReply: (postId: string, replyId: string) => Promise<void>;
}

export interface WorkspaceActionDeps {
  createObjective: (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    data: { title: string; description?: string; obj_type?: CyberObjectiveType; parent_id?: string },
  ) => Promise<void>;
  deleteObjective: (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    objectiveId: string,
  ) => Promise<void>;
  projectObjectiveToTask: (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    objectiveId: string,
  ) => Promise<void>;
  deleteGene: (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    geneId: string,
  ) => Promise<void>;
  updateGene: (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    geneId: string,
    data: Partial<{ name: string; is_active: boolean }>,
  ) => Promise<void>;
}

export interface UseBlackboardModalActionsParams {
  open: boolean;
  tenantId: string;
  projectId: string;
  workspaceId: string;
  posts: BlackboardPost[];
  loadedReplyPostIds: Record<string, boolean>;
  callbacks: BlackboardActionCallbacks;
  workspaceActions: WorkspaceActionDeps;
  message: { error: (msg: string) => void } | null | undefined;
  t: (key: string, fallback: string) => string;
}

export function useBlackboardModalActions({
  open,
  tenantId,
  projectId,
  workspaceId,
  posts,
  loadedReplyPostIds,
  callbacks,
  workspaceActions,
  message,
  t,
}: UseBlackboardModalActionsParams) {
  const {
    onLoadReplies,
    onCreatePost,
    onCreateReply,
    onDeletePost,
    onPinPost,
    onUnpinPost,
    onDeleteReply,
  } = callbacks;

  const { createObjective, deleteObjective, projectObjectiveToTask, deleteGene, updateGene } =
    workspaceActions;

  const [selectedPostId, setSelectedPostId] = useState<string | null>(null);
  const [postTitle, setPostTitle] = useState('');
  const [postContent, setPostContent] = useState('');
  const [replyDraft, setReplyDraft] = useState('');

  const [autoReplyRetryBlockedByPostId, setAutoReplyRetryBlockedByPostId] = useState<
    Record<string, boolean>
  >({});
  const [creatingPost, setCreatingPost] = useState(false);
  const [replying, setReplying] = useState(false);
  const [loadingRepliesPostId, setLoadingRepliesPostId] = useState<string | null>(null);
  const [togglingPostId, setTogglingPostId] = useState<string | null>(null);
  const [deletingPostId, setDeletingPostId] = useState<string | null>(null);
  const [deletingReplyId, setDeletingReplyId] = useState<string | null>(null);
  const [showCreateObjective, setShowCreateObjective] = useState(false);
  const [creatingObjective, setCreatingObjective] = useState(false);

  const selectedPost = posts.find((post) => post.id === selectedPostId) ?? null;

  useEffect(() => {
    const fallbackPostId = posts.find((post) => post.is_pinned)?.id ?? posts[0]?.id ?? null;
    const hasSelectedPost = posts.some((post) => post.id === selectedPostId);

    if (!hasSelectedPost && fallbackPostId !== selectedPostId) {
      setSelectedPostId(fallbackPostId);
    }
  }, [posts, selectedPostId]);

  useEffect(() => {
    setReplyDraft('');
  }, [selectedPostId]);

  useEffect(() => {
    if (!open) {
      setAutoReplyRetryBlockedByPostId({});
    }
  }, [open]);

  const handleLoadReplies = useCallback(
    async (postId: string, options?: { manual?: boolean }) => {
      setLoadingRepliesPostId(postId);
      try {
        const loaded = await onLoadReplies(postId);

        if (loaded) {
          setAutoReplyRetryBlockedByPostId((current) => {
            if (!(postId in current)) {
              return current;
            }

            return { ...current, [postId]: false };
          });
          return;
        }

        if (!options?.manual) {
          setAutoReplyRetryBlockedByPostId((current) => ({ ...current, [postId]: true }));
        }
      } finally {
        setLoadingRepliesPostId((current) => (current === postId ? null : current));
      }
    },
    [onLoadReplies],
  );

  useEffect(() => {
    if (
      !open ||
      !selectedPostId ||
      loadedReplyPostIds[selectedPostId] ||
      autoReplyRetryBlockedByPostId[selectedPostId] === true ||
      loadingRepliesPostId === selectedPostId
    ) {
      return;
    }

    void handleLoadReplies(selectedPostId);
  }, [
    autoReplyRetryBlockedByPostId,
    handleLoadReplies,
    loadedReplyPostIds,
    loadingRepliesPostId,
    open,
    selectedPostId,
  ]);

  const handleCreatePost = async () => {
    const title = postTitle.trim();
    const content = postContent.trim();
    if (!title || !content) {
      return;
    }

    setCreatingPost(true);
    try {
      const created = await onCreatePost({ title, content });
      if (created) {
        setPostTitle('');
        setPostContent('');
      }
    } finally {
      setCreatingPost(false);
    }
  };

  const handleCreateReply = async () => {
    if (!selectedPost) {
      return;
    }

    const nextContent = replyDraft.trim();
    if (!nextContent) {
      return;
    }

    setReplying(true);
    try {
      const created = await onCreateReply(selectedPost.id, nextContent);
      if (created) {
        setReplyDraft('');
      }
    } finally {
      setReplying(false);
    }
  };

  const handleTogglePin = async () => {
    if (!selectedPost) {
      return;
    }

    setTogglingPostId(selectedPost.id);
    try {
      if (selectedPost.is_pinned) {
        await onUnpinPost(selectedPost.id);
      } else {
        await onPinPost(selectedPost.id);
      }
    } finally {
      setTogglingPostId(null);
    }
  };

  const handleDeleteSelectedPost = async () => {
    if (!selectedPost) {
      return;
    }

    setDeletingPostId(selectedPost.id);
    try {
      const deleted = await onDeletePost(selectedPost.id);
      if (deleted) {
        setSelectedPostId((current) => (current === selectedPost.id ? null : current));
      }
    } finally {
      setDeletingPostId(null);
    }
  };

  const handleDeleteSelectedReply = async (replyId: string) => {
    if (!selectedPost) {
      return;
    }

    setDeletingReplyId(replyId);
    try {
      await onDeleteReply(selectedPost.id, replyId);
    } finally {
      setDeletingReplyId(null);
    }
  };

  const handleCreateObjective = async (values: ObjectiveFormValues) => {
    setCreatingObjective(true);
    try {
      const payload: Parameters<typeof createObjective>[3] = {
        title: values.title,
        obj_type: values.obj_type,
      };

      if (values.description) {
        payload.description = values.description;
      }
      if (values.parent_id) {
        payload.parent_id = values.parent_id;
      }

      await createObjective(tenantId, projectId, workspaceId, payload);
      setShowCreateObjective(false);
    } catch {
      message?.error(t('blackboard.errors.createObjective', 'Failed to create objective'));
    } finally {
      setCreatingObjective(false);
    }
  };

  const handleDeleteObjective = async (objectiveId: string) => {
    try {
      await deleteObjective(tenantId, projectId, workspaceId, objectiveId);
    } catch {
      message?.error(t('blackboard.errors.deleteObjective', 'Failed to delete objective'));
    }
  };

  const handleProjectObjective = async (objectiveId: string) => {
    try {
      await projectObjectiveToTask(tenantId, projectId, workspaceId, objectiveId);
    } catch {
      message?.error(t('blackboard.errors.createObjective', 'Failed to create objective'));
    }
  };

  const handleDeleteGene = async (geneId: string) => {
    try {
      await deleteGene(tenantId, projectId, workspaceId, geneId);
    } catch {
      message?.error(t('blackboard.errors.deleteGene', 'Failed to delete gene'));
    }
  };

  const handleToggleGeneActive = async (geneId: string, isActive: boolean) => {
    try {
      await updateGene(tenantId, projectId, workspaceId, geneId, { is_active: isActive });
    } catch {
      message?.error(t('blackboard.errors.updateGene', 'Failed to update gene'));
    }
  };

  return {
    selectedPostId,
    setSelectedPostId,
    selectedPost,
    postTitle,
    setPostTitle,
    postContent,
    setPostContent,
    replyDraft,
    setReplyDraft,

    creatingPost,
    replying,
    loadingRepliesPostId,
    togglingPostId,
    deletingPostId,
    deletingReplyId,
    showCreateObjective,
    setShowCreateObjective,
    creatingObjective,
    autoReplyRetryBlockedByPostId,

    handleLoadReplies: handleLoadReplies as (
      postId: string,
      options?: { manual?: boolean },
    ) => Promise<void>,
    handleCreatePost,
    handleCreateReply,
    handleTogglePin,
    handleDeleteSelectedPost,
    handleDeleteSelectedReply,
    handleCreateObjective,
    handleDeleteObjective,
    handleProjectObjective,
    handleDeleteGene,
    handleToggleGeneActive,
  };
}

export type UseBlackboardModalActionsReturn = ReturnType<typeof useBlackboardModalActions>;
