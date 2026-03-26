import { useState } from 'react';

import { useWorkspaceActions, useWorkspacePosts, useWorkspaceStore } from '@/stores/workspace';

interface BlackboardPanelProps {
  tenantId: string;
  projectId: string;
  workspaceId: string;
}

export function BlackboardPanel({ tenantId, projectId, workspaceId }: BlackboardPanelProps) {
  const posts = useWorkspacePosts();
  const repliesByPostId = useWorkspaceStore((state) => state.repliesByPostId);
  const { createPost, createReply } = useWorkspaceActions();
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [replyDrafts, setReplyDrafts] = useState<Record<string, string>>({});

  const onCreatePost = async () => {
    if (!title.trim() || !content.trim()) return;
    await createPost(tenantId, projectId, workspaceId, {
      title: title.trim(),
      content: content.trim(),
    });
    setTitle('');
    setContent('');
  };

  const onCreateReply = async (postId: string) => {
    const draft = replyDrafts[postId]?.trim();
    if (!draft) return;
    await createReply(tenantId, projectId, workspaceId, postId, { content: draft });
    setReplyDrafts((prev) => ({ ...prev, [postId]: '' }));
  };

  return (
    <section className="rounded-lg border border-slate-200 p-4 bg-white">
      <h3 className="font-semibold text-slate-900 mb-3">Blackboard</h3>
      <div className="grid gap-2 mb-3">
        <input
          placeholder="Post title"
          value={title}
          onChange={(e) => {
            setTitle(e.target.value);
          }}
          className="border rounded px-3 py-2 text-sm"
        />
        <textarea
          placeholder="Post content"
          value={content}
          onChange={(e) => {
            setContent(e.target.value);
          }}
          className="border rounded px-3 py-2 text-sm min-h-20"
        />
        <button
          type="button"
          className="px-3 py-2 bg-primary text-white rounded w-fit"
          onClick={() => void onCreatePost()}
        >
          Add post
        </button>
      </div>

      <div className="space-y-3">
        {posts.map((post) => {
          const replies = repliesByPostId[post.id] || [];
          return (
            <article key={post.id} className="border rounded p-3 transition-all duration-300">
              <h4 className="font-medium">{post.title}</h4>
              <p className="text-sm text-slate-700">{post.content}</p>
              <div className="text-xs text-slate-500 mt-1">status: {post.status}</div>

              {replies.length > 0 && (
                <div className="mt-3 space-y-2 pl-2 border-l-2 border-slate-100">
                  {replies.map((reply) => (
                    <div key={reply.id} className="text-sm text-slate-600 bg-slate-50 p-2 rounded">
                      {reply.content}
                    </div>
                  ))}
                </div>
              )}

              <div className="mt-2 flex gap-2">
                <input
                  placeholder="Reply"
                  value={replyDrafts[post.id] ?? ''}
                  onChange={(e) => {
                    setReplyDrafts((prev) => ({ ...prev, [post.id]: e.target.value }));
                  }}
                  className="border rounded px-2 py-1 text-sm flex-1"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      void onCreateReply(post.id);
                    }
                  }}
                />
                <button
                  type="button"
                  className="px-2 py-1 text-xs border rounded"
                  onClick={() => void onCreateReply(post.id)}
                >
                  Reply
                </button>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
