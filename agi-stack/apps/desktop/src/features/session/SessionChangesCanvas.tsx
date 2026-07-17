import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { Badge, Button } from '@radix-ui/themes';
import { CodeIcon, ReloadIcon } from '@radix-ui/react-icons';

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
} from './sessionChangesModel';
import './SessionChangesCanvas.css';

type SessionChangesCanvasProps = {
  snapshot: ChangeSnapshot | null;
  loading: boolean;
  error: string | null;
  references: CodeRangeReference[];
  decision?: ReactNode;
  onToggleReference: (reference: CodeRangeReference) => void;
  onRefresh: () => void;
};

export function SessionChangesCanvas({
  snapshot,
  loading,
  error,
  references,
  decision,
  onToggleReference,
  onRefresh,
}: SessionChangesCanvasProps) {
  const { t } = useI18n();
  const [activePath, setActivePath] = useState<string>('');
  const selectedKeys = useMemo(
    () => new Set(references.map(runInputReferenceKey)),
    [references],
  );
  useEffect(() => {
    if (!snapshot?.files.length) {
      setActivePath('');
      return;
    }
    if (!snapshot.files.some((file) => file.path === activePath)) {
      setActivePath(snapshot.files[0].path);
    }
  }, [activePath, snapshot]);
  const activeFile =
    snapshot?.files.find((file) => file.path === activePath) ?? snapshot?.files[0] ?? null;

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
            <small>{t('session.changeReferenceHint')}</small>
          </div>
          <nav className="session-change-files" aria-label={t('session.changedFileTabs')}>
            {snapshot.files.map((file) => (
              <button
                type="button"
                className={file.path === activeFile?.path ? 'is-active' : ''}
                aria-pressed={file.path === activeFile?.path}
                onClick={() => setActivePath(file.path)}
                key={file.path}
              >
                <CodeIcon />
                <span>{file.path}</span>
                <em>
                  +{file.additions} −{file.deletions}
                </em>
              </button>
            ))}
          </nav>
          {activeFile ? (
            <ChangeFileView
              snapshot={snapshot}
              file={activeFile}
              selectedKeys={selectedKeys}
              onToggleReference={onToggleReference}
            />
          ) : null}
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
  onToggleReference,
}: {
  snapshot: ChangeSnapshot;
  file: ChangeFile;
  selectedKeys: Set<string>;
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
                  selected={selected}
                  disabled={!reference}
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
  selected,
  disabled,
  onSelect,
}: {
  line: ChangeLine;
  selected: boolean;
  disabled: boolean;
  onSelect: () => void;
}) {
  const { t } = useI18n();
  return (
    <button
      type="button"
      className={`session-change-line is-${line.kind} ${selected ? 'is-selected' : ''}`}
      aria-pressed={selected}
      aria-label={t('session.referenceChangeLine', {
        line: line.new_line ?? line.old_line ?? '—',
        kind: line.kind,
      })}
      disabled={disabled}
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
