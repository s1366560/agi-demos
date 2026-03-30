import { message } from 'antd';
import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { useShallow } from 'zustand/react/shallow';

import { workspaceBlackboardService } from '@/services/workspaceService';

import { getErrorMessage } from '@/types/common';
import type { BlackboardPost, BlackboardReply } from '@/types/workspace';

interface BlackboardState {
  // State
  posts: BlackboardPost[];
  selectedPost: BlackboardPost | null;
  replies: BlackboardReply[];
  loading: boolean;
  error: string | null;

  // Actions
  fetchPosts: (tenantId: string, projectId: string, workspaceId: string) => Promise<void>;
  createPost: (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    data: { title: string; content: string }
  ) => Promise<void>;
  updatePost: (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    postId: string,
    data: Partial<Pick<BlackboardPost, 'title' | 'content' | 'status'>>
  ) => Promise<void>;
  deletePost: (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    postId: string
  ) => Promise<void>;
  pinPost: (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    postId: string
  ) => Promise<void>;
  unpinPost: (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    postId: string
  ) => Promise<void>;
  fetchReplies: (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    postId: string
  ) => Promise<void>;
  createReply: (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    postId: string,
    content: string
  ) => Promise<void>;
  deleteReply: (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    postId: string,
    replyId: string
  ) => Promise<void>;
  selectPost: (post: BlackboardPost | null) => void;
  reset: () => void;
}

export const useBlackboardStore = create<BlackboardState>()(
  devtools(
    (set, get) => ({
      posts: [],
      selectedPost: null,
      replies: [],
      loading: false,
      error: null,

      fetchPosts: async (tenantId: string, projectId: string, workspaceId: string) => {
        set({ loading: true, error: null });
        try {
          const posts = await workspaceBlackboardService.listPosts(
            tenantId,
            projectId,
            workspaceId
          );
          set({ posts, loading: false });
        } catch (error: unknown) {
          const errorMsg = getErrorMessage(error);
          set({ error: errorMsg, loading: false });
          message.error(errorMsg);
          throw error;
        }
      },

      createPost: async (
        tenantId: string,
        projectId: string,
        workspaceId: string,
        data: { title: string; content: string }
      ) => {
        set({ loading: true, error: null });
        try {
          await workspaceBlackboardService.createPost(tenantId, projectId, workspaceId, data);
          await get().fetchPosts(tenantId, projectId, workspaceId);
        } catch (error: unknown) {
          const errorMsg = getErrorMessage(error);
          set({ error: errorMsg, loading: false });
          message.error(errorMsg);
          throw error;
        }
      },

      updatePost: async (
        tenantId: string,
        projectId: string,
        workspaceId: string,
        postId: string,
        data: Partial<Pick<BlackboardPost, 'title' | 'content' | 'status'>>
      ) => {
        set({ loading: true, error: null });
        try {
          await workspaceBlackboardService.updatePost(
            tenantId,
            projectId,
            workspaceId,
            postId,
            data
          );
          await get().fetchPosts(tenantId, projectId, workspaceId);
          const currentSelected = get().selectedPost;
          if (currentSelected?.id === postId) {
            const updatedPosts = get().posts;
            const newSelected = updatedPosts.find((p) => p.id === postId) || null;
            set({ selectedPost: newSelected });
          }
        } catch (error: unknown) {
          const errorMsg = getErrorMessage(error);
          set({ error: errorMsg, loading: false });
          message.error(errorMsg);
          throw error;
        }
      },

      deletePost: async (
        tenantId: string,
        projectId: string,
        workspaceId: string,
        postId: string
      ) => {
        set({ loading: true, error: null });
        try {
          await workspaceBlackboardService.deletePost(tenantId, projectId, workspaceId, postId);
          await get().fetchPosts(tenantId, projectId, workspaceId);
          if (get().selectedPost?.id === postId) {
            set({ selectedPost: null, replies: [] });
          }
        } catch (error: unknown) {
          const errorMsg = getErrorMessage(error);
          set({ error: errorMsg, loading: false });
          message.error(errorMsg);
          throw error;
        }
      },

      pinPost: async (tenantId: string, projectId: string, workspaceId: string, postId: string) => {
        set({ loading: true, error: null });
        try {
          await workspaceBlackboardService.pinPost(tenantId, projectId, workspaceId, postId);
          await get().fetchPosts(tenantId, projectId, workspaceId);
          const currentSelected = get().selectedPost;
          if (currentSelected?.id === postId) {
            const updatedPosts = get().posts;
            const newSelected = updatedPosts.find((p) => p.id === postId) || null;
            set({ selectedPost: newSelected });
          }
        } catch (error: unknown) {
          const errorMsg = getErrorMessage(error);
          set({ error: errorMsg, loading: false });
          message.error(errorMsg);
          throw error;
        }
      },

      unpinPost: async (
        tenantId: string,
        projectId: string,
        workspaceId: string,
        postId: string
      ) => {
        set({ loading: true, error: null });
        try {
          await workspaceBlackboardService.unpinPost(tenantId, projectId, workspaceId, postId);
          await get().fetchPosts(tenantId, projectId, workspaceId);
          const currentSelected = get().selectedPost;
          if (currentSelected?.id === postId) {
            const updatedPosts = get().posts;
            const newSelected = updatedPosts.find((p) => p.id === postId) || null;
            set({ selectedPost: newSelected });
          }
        } catch (error: unknown) {
          const errorMsg = getErrorMessage(error);
          set({ error: errorMsg, loading: false });
          message.error(errorMsg);
          throw error;
        }
      },

      fetchReplies: async (
        tenantId: string,
        projectId: string,
        workspaceId: string,
        postId: string
      ) => {
        set({ loading: true, error: null });
        try {
          const replies = await workspaceBlackboardService.listReplies(
            tenantId,
            projectId,
            workspaceId,
            postId
          );
          set({ replies, loading: false });
        } catch (error: unknown) {
          const errorMsg = getErrorMessage(error);
          set({ error: errorMsg, loading: false });
          message.error(errorMsg);
          throw error;
        }
      },

      createReply: async (
        tenantId: string,
        projectId: string,
        workspaceId: string,
        postId: string,
        content: string
      ) => {
        set({ loading: true, error: null });
        try {
          await workspaceBlackboardService.createReply(
            tenantId,
            projectId,
            workspaceId,
            postId,
            { content }
          );
          await get().fetchReplies(tenantId, projectId, workspaceId, postId);
        } catch (error: unknown) {
          const errorMsg = getErrorMessage(error);
          set({ error: errorMsg, loading: false });
          message.error(errorMsg);
          throw error;
        }
      },

      deleteReply: async (
        tenantId: string,
        projectId: string,
        workspaceId: string,
        postId: string,
        replyId: string
      ) => {
        set({ loading: true, error: null });
        try {
          await workspaceBlackboardService.deleteReply(
            tenantId,
            projectId,
            workspaceId,
            postId,
            replyId
          );
          await get().fetchReplies(tenantId, projectId, workspaceId, postId);
        } catch (error: unknown) {
          const errorMsg = getErrorMessage(error);
          set({ error: errorMsg, loading: false });
          message.error(errorMsg);
          throw error;
        }
      },

      selectPost: (post: BlackboardPost | null) => {
        set({ selectedPost: post });
      },

      reset: () => {
        set({
          posts: [],
          selectedPost: null,
          replies: [],
          loading: false,
          error: null,
        });
      },
    }),
    {
      name: 'BlackboardStore',
      enabled: import.meta.env.DEV,
    }
  )
);

// Selectors
export const useBlackboardPosts = () => useBlackboardStore((state) => state.posts);
export const useSelectedPost = () => useBlackboardStore((state) => state.selectedPost);
export const useBlackboardReplies = () => useBlackboardStore((state) => state.replies);
export const useBlackboardLoading = () => useBlackboardStore((state) => state.loading);
export const useBlackboardError = () => useBlackboardStore((state) => state.error);

export const useBlackboardActions = () =>
  useBlackboardStore(
    useShallow((state) => ({
      fetchPosts: state.fetchPosts,
      createPost: state.createPost,
      updatePost: state.updatePost,
      deletePost: state.deletePost,
      pinPost: state.pinPost,
      unpinPost: state.unpinPost,
      fetchReplies: state.fetchReplies,
      createReply: state.createReply,
      deleteReply: state.deleteReply,
      selectPost: state.selectPost,
      reset: state.reset,
    }))
  );
