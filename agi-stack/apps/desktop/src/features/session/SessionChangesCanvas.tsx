import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { Badge, Button } from '@radix-ui/themes';
import {
  ChatBubbleIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  CodeIcon,
  Cross2Icon,
  PaperPlaneIcon,
  ReloadIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type {
  ChangeFile,
  ChangeLine,
  ChangeSnapshot,
  CodeRangeReference,
} from '../../types';
import {
  referenceForChangeLine,
  runInputReferenceKey,
  runInputReferenceLabel,
} from './sessionChangesModel';
import type { ChangeReviewComment } from './sessionChangesReviewModel';
import {
  collapseAllChangeFiles,
  createChangeComment,
  expandAllChangeFiles,
  reconcileExpandedChangeFiles,
  toggleExpandedChangeFile,
} from './sessionChangesReviewModel';
import './SessionChangesCanvas.css';

type CommentDraft = {
  anchorKey: string;
  reference: CodeRangeReference;
  text: string;
};

type ReviewInteraction = {
  commentsByAnchor: ReadonlyMap<string, ChangeReviewComment[]>;
  draft: CommentDraft | null;
  onStartComment: (anchorKey: string, reference: CodeRangeReference) => void;
  onDraftTextChange: (text: string) => void;
  onSubmitDraft: () => void;
  onCancelDraft: () => void;
  onRemoveComment: (commentId: string) => void;
};

type SessionChangesCanvasProps = {
  snapshot: ChangeSnapshot | null;
  loading: boolean;
  error: string | null;
  references: CodeRangeReference[];
  comments: ChangeReviewComment[];
  decision?: ReactNode;
  onToggleReference: (reference: CodeRangeReference) => void;
  onAddComment: (comment: ChangeReviewComment) => void;
  onRemoveComment: (commentId: string) => void;
  onSendComments: (comments: ChangeReviewComment[]) => void;
  onRefresh: () => void;
};

export function SessionChangesCanvas({
  snapshot,
  loading,
  error,
  references,
  comments,
  decision,
  onToggleReference,
  onAddComment,
  onRemoveComment,
  onSendComments,
  onRefresh,
}: SessionChangesCanvasProps) {
  const { t } = useI18n();
  const [expandedPaths, setExpandedPaths] = useState<string[]>([]);
  const [draft, setDraft] = useState<CommentDraft | null>(null);
  const files = snapshot?.files ?? [];
  const selectedKeys = useMemo(
    () => new Set(references.map(runInputReferenceKey)),
    [references],
  );
  const commentsByAnchor = useMemo(() => {
    const grouped = new Map<string, ChangeReviewComment[]>();
    for (const comment of comments) {
      const key = runInputReferenceKey(comment.reference);
      const bucket = grouped.get(key);
      if (bucket) {
        bucket.push(comment);
      } else {
        grouped.set(key, [comment]);
      }
    }
    return grouped;
  }, [comments]);
  useEffect(() => {
    setExpandedPaths((current) => reconcileExpandedChangeFiles(current, files));
  }, [files]);
  useEffect(() => {
    // A refresh rebinds the snapshot: anchors from an older patch digest no
    // longer resolve, so any open editor is discarded with it.
    setDraft(null);
  }, [snapshot?.id]);

  const review: ReviewInteraction = {
    commentsByAnchor,
    draft,
    onStartComment: (anchorKey, reference) => setDraft({ anchorKey, reference, text: '' }),
    onDraftTextChange: (text) =>
      setDraft((current) => (current ? { ...current, text } : current)),
    onSubmitDraft: () => {
      if (!draft) return;
      const comment = createChangeComment(
        draft.reference,
        draft.text,
        globalThis.crypto?.randomUUID?.() ?? `comment-${Date.now()}`,
        new Date().toISOString(),
      );
      if (comment) onAddComment(comment);
      setDraft(null);
    },
    onCancelDraft: () => setDraft(null),
    onRemoveComment,
  };

  return (
    <section className="session-changes-canvas" aria-label={t('session.changesTitle')}>
      <header className="session-changes-head">
        <div>
          <span>{t('session.changesKicker')}</span>
          <strong>{t('session.changesTitle')}</strong>
          {snapshot ? (
            <small>{snapshot.branch ?? t('session.branchUnavailable')}</small>
          ) : null}
        </div>
        <div className="session-changes-actions">
          {snapshot?.truncated ? (
            <Badge color="amber" variant="soft">
              {t('session.changesTruncated')}
            </Badge>
          ) : null}
          <Button size="1" variant="surface" onClick={onRefresh} disabled={loading}>
            <ReloadIcon />
            {loading ? t('session.changesRefreshing') : t('session.changesRefresh')}
          </Button>
        </div>
      </header>

      {loading && !snapshot ? (
        <ChangesState title={t('session.changesLoading')} body={t('session.changesLoadingBody')} />
      ) : error ? (
        <ChangesState title={t('session.changesError')} body={error} />
      ) : !snapshot ? (
        <ChangesState title={t('session.changesUnavailable')} body={t('session.changesUnavailableBody')} />
      ) : snapshot.status !== 'ready' ? (
        <ChangesState
          title={t(`session.changesStatus.${snapshot.status}`)}
          body={t(`session.changesReason.${snapshot.reason ?? 'unknown'}`)}
        />
      ) : snapshot.files.length === 0 ? (
        <ChangesState title={t('session.noChanges')} body={t('session.noChangesDescription')} />
      ) : (
        <>
          <div className="session-changes-summary" role="status">
            <span>{t('session.changedFiles', { count: snapshot.files_changed })}</span>
            <strong className="is-addition">+{snapshot.additions}</strong>
            <strong className="is-deletion">−{snapshot.deletions}</strong>
            <span className="session-changes-expand-actions">
              <Button
                size="1"
                variant="ghost"
                onClick={() => setExpandedPaths(expandAllChangeFiles(snapshot.files))}
              >
                {t('session.expandAllChanges')}
              </Button>
              <Button
                size="1"
                variant="ghost"
                onClick={() => setExpandedPaths(collapseAllChangeFiles())}
              >
                {t('session.collapseAllChanges')}
              </Button>
            </span>
            <small>{t('session.changeReferenceHint')}</small>
          </div>
          {comments.length > 0 ? (
            <div className="session-change-comments-bar" role="status">
              <span>{t('session.pendingChangeComments', { count: comments.length })}</span>
              <Button size="1" onClick={() => onSendComments(comments)}>
                <PaperPlaneIcon />
                {t('session.sendChangeComments')}
              </Button>
            </div>
          ) : null}
          <div className="session-change-files-list" aria-label={t('session.changedFileTabs')}>
            {snapshot.files.map((file) => {
              const expanded = expandedPaths.includes(file.path);
              return (
                <div className="session-change-file-item" key={file.path}>
                  <button
                    type="button"
                    className={`session-change-file-toggle ${expanded ? 'is-expanded' : ''}`}
                    aria-expanded={expanded}
                    aria-label={t(
                      expanded ? 'session.collapseChangeFile' : 'session.expandChangeFile',
                      { path: file.path },
                    )}
                    onClick={() =>
                      setExpandedPaths((current) => toggleExpandedChangeFile(current, file.path))
                    }
                  >
                    {expanded ? <ChevronDownIcon /> : <ChevronRightIcon />}
                    <CodeIcon />
                    <span>{file.path}</span>
                    <em>
                      +{file.additions} −{file.deletions}
                    </em>
                  </button>
                  {expanded ? (
                    <ChangeFileView
                      snapshot={snapshot}
                      file={file}
                      selectedKeys={selectedKeys}
                      review={review}
                      onToggleReference={onToggleReference}
                    />
                  ) : null}
                </div>
              );
            })}
          </div>
        </>
      )}
      {decision ? <div className="session-change-decision">{decision}</div> : null}
    </section>
  );
}

function ChangeFileView({
  snapshot,
  file,
  selectedKeys,
  review,
  onToggleReference,
}: {
  snapshot: ChangeSnapshot;
  file: ChangeFile;
  selectedKeys: Set<string>;
  review: ReviewInteraction;
  onToggleReference: (reference: CodeRangeReference) => void;
}) {
  const { t } = useI18n();
  if (file.binary) {
    return <ChangesState title={file.path} body={t('session.binaryChange')} />;
  }
  return (
    <div className="session-change-patch" aria-label={file.path}>
      <header>
        <strong>{file.path}</strong>
        <span>{file.status}</span>
      </header>
      {file.hunks.map((hunk, hunkIndex) => (
        <details open className="session-change-hunk" key={`${hunk.header}-${hunkIndex}`}>
          <summary>{hunk.header}</summary>
          <div role="table" aria-label={`${file.path} ${hunk.header}`}>
            {hunk.lines.map((line, lineIndex) => {
              const reference = referenceForChangeLine(snapshot, file, line);
              const selected = reference ? selectedKeys.has(runInputReferenceKey(reference)) : false;
              return (
                <ChangeLineRow
                  line={line}
                  reference={reference}
                  selected={selected}
                  review={review}
                  onSelect={() => reference && onToggleReference(reference)}
                  key={`${line.kind}-${line.old_line ?? 'x'}-${line.new_line ?? 'x'}-${lineIndex}`}
                />
              );
            })}
          </div>
        </details>
      ))}
    </div>
  );
}

function ChangeLineRow({
  line,
  reference,
  selected,
  review,
  onSelect,
}: {
  line: ChangeLine;
  reference: CodeRangeReference | null;
  selected: boolean;
  review: ReviewInteraction;
  onSelect: () => void;
}) {
  const { t } = useI18n();
  const anchorKey = reference ? runInputReferenceKey(reference) : null;
  const lineComments = anchorKey ? (review.commentsByAnchor.get(anchorKey) ?? []) : [];
  const draftOpen = Boolean(anchorKey && review.draft?.anchorKey === anchorKey);
  return (
    <div className="session-change-line-wrap">
      <button
        type="button"
        className={`session-change-line is-${line.kind} ${selected ? 'is-selected' : ''}`}
        aria-pressed={selected}
        aria-label={t('session.referenceChangeLine', {
          line: line.new_line ?? line.old_line ?? '—',
          kind: line.kind,
        })}
        disabled={!reference}
        onClick={onSelect}
        role="row"
      >
        <span className="old-line" role="cell">
          {line.old_line ?? ''}
        </span>
        <span className="new-line" role="cell">
          {line.new_line ?? ''}
        </span>
        <span className="change-marker" aria-hidden="true">
          {line.kind === 'addition' ? '+' : line.kind === 'deletion' ? '−' : ' '}
        </span>
        <code role="cell">{line.text || ' '}</code>
      </button>
      {reference && anchorKey ? (
        <button
          type="button"
          className="session-change-comment-trigger"
          aria-label={t('session.addChangeComment')}
          onClick={() => review.onStartComment(anchorKey, reference)}
        >
          <ChatBubbleIcon />
        </button>
      ) : null}
      {lineComments.map((comment) => (
        <div className="session-change-comment" key={comment.id}>
          <code>{runInputReferenceLabel(comment.reference)}</code>
          <p>{comment.text}</p>
          <button
            type="button"
            aria-label={t('session.removeChangeComment')}
            onClick={() => review.onRemoveComment(comment.id)}
          >
            <Cross2Icon />
          </button>
        </div>
      ))}
      {draftOpen && review.draft ? (
        <div className="session-change-comment-editor">
          <textarea
            value={review.draft.text}
            rows={2}
            autoFocus
            placeholder={t('session.changeCommentPlaceholder')}
            onChange={(event) => review.onDraftTextChange(event.target.value)}
          />
          <div className="session-change-comment-editor-actions">
            <Button
              size="1"
              disabled={!review.draft.text.trim()}
              onClick={review.onSubmitDraft}
            >
              {t('session.saveChangeComment')}
            </Button>
            <Button size="1" variant="surface" onClick={review.onCancelDraft}>
              {t('session.cancelChangeComment')}
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ChangesState({ title, body }: { title: string; body: string }) {
  return (
    <div className="session-changes-state" role="status">
      <CodeIcon />
      <strong>{title}</strong>
      <p>{body}</p>
    </div>
  );
}
