import type { ChangeFile, CodeRangeReference } from '../../types';
import { runInputReferenceKey, runInputReferenceLabel } from './sessionChangesModel';

/**
 * P1-4 review-panel model: per-file expand/collapse state and line-anchored
 * inline review comments that are batched into a single composer message.
 *
 * Pending comments live in memory only, keyed by conversation id. They are
 * deliberately not persisted to localStorage: a comment anchors to a specific
 * snapshot id + patch digest, and a stale anchor after restart would point at
 * a diff line the agent can no longer resolve.
 */

export type ChangeReviewComment = {
  id: string;
  reference: CodeRangeReference;
  text: string;
  createdAt: string;
};

export type ChangeReviewCommentMap = Record<string, ChangeReviewComment[]>;

export function createChangeComment(
  reference: CodeRangeReference,
  text: string,
  id: string,
  createdAt: string,
): ChangeReviewComment | null {
  const trimmed = text.trim();
  if (!trimmed || !id) return null;
  return { id, reference, text: trimmed, createdAt };
}

export function commentsForConversation(
  map: ChangeReviewCommentMap,
  conversationId: string | null | undefined,
): ChangeReviewComment[] {
  if (!conversationId) return [];
  return map[conversationId] ?? [];
}

export function addChangeComment(
  map: ChangeReviewCommentMap,
  conversationId: string,
  comment: ChangeReviewComment,
): ChangeReviewCommentMap {
  const existing = map[conversationId] ?? [];
  return { ...map, [conversationId]: [...existing, comment] };
}

export function removeChangeComment(
  map: ChangeReviewCommentMap,
  conversationId: string,
  commentId: string,
): ChangeReviewCommentMap {
  const existing = map[conversationId] ?? [];
  const next = existing.filter((comment) => comment.id !== commentId);
  if (next.length === existing.length) return map;
  if (next.length === 0) {
    const { [conversationId]: _removed, ...rest } = map;
    return rest;
  }
  return { ...map, [conversationId]: next };
}

export function clearChangeComments(
  map: ChangeReviewCommentMap,
  conversationId: string,
): ChangeReviewCommentMap {
  if (!(conversationId in map)) return map;
  const { [conversationId]: _removed, ...rest } = map;
  return rest;
}

/** Structured references carried alongside the batched comment message. */
export function referencesForChangeComments(
  comments: readonly ChangeReviewComment[],
): CodeRangeReference[] {
  const seen = new Set<string>();
  const references: CodeRangeReference[] = [];
  for (const comment of comments) {
    const key = runInputReferenceKey(comment.reference);
    if (seen.has(key)) continue;
    seen.add(key);
    references.push(comment.reference);
  }
  return references;
}

/**
 * Batch every pending comment into one agent-bound message. Each comment is a
 * quoted anchor (`path#L12`, or `path#L-9` for the old side) followed by the
 * indented review text, so the agent can resolve the exact commented location
 * even where structured references are not carried on the wire.
 */
export function buildChangeCommentsMessage(
  comments: readonly ChangeReviewComment[],
): string {
  const entries = comments.map((comment, index) => {
    const anchor = runInputReferenceLabel(comment.reference);
    const body = comment.text
      .split('\n')
      .map((line) => `   ${line}`)
      .join('\n');
    return `${index + 1}. ${anchor}\n${body}`;
  });
  return ['Please address the following inline review comments:', '', ...entries].join('\n');
}

export function toggleExpandedChangeFile(
  expanded: readonly string[],
  path: string,
): string[] {
  return expanded.includes(path)
    ? expanded.filter((candidate) => candidate !== path)
    : [...expanded, path];
}

export function expandAllChangeFiles(files: readonly ChangeFile[]): string[] {
  return files.map((file) => file.path);
}

export function collapseAllChangeFiles(): string[] {
  return [];
}

/**
 * Drop expanded paths that disappeared from the snapshot after a refresh.
 * When nothing valid remains, fall back to the first file so the panel never
 * renders a fully collapsed wall with no hint of content.
 */
export function reconcileExpandedChangeFiles(
  expanded: readonly string[],
  files: readonly ChangeFile[],
): string[] {
  const paths = new Set(files.map((file) => file.path));
  const kept = expanded.filter((path) => paths.has(path));
  if (kept.length > 0) return kept;
  return files.length > 0 ? [files[0].path] : [];
}
