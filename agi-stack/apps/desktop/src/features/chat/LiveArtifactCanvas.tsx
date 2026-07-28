import { useCallback, useEffect, useState } from 'react';
import {
  ClipboardCopyIcon,
  CodeIcon,
  Cross2Icon,
  DownloadIcon,
  DrawingPinIcon,
  EyeOpenIcon,
  FileTextIcon,
  TableIcon,
} from '@radix-ui/react-icons';
import { Badge } from '@radix-ui/themes';
import ReactMarkdown from 'react-markdown';
import type { Components } from 'react-markdown';

import { useI18n } from '../../i18n';
import {
  ARTIFACT_CANVAS_SAVE_CAPABILITY,
  ARTIFACT_CANVAS_VIEW_MODES,
  applyArtifactCanvasWorkspaceAuthorityContent,
  artifactCanvasDownloadDescriptor,
  cancelArtifactCanvasTabClose,
  confirmArtifactCanvasTabClose,
  createArtifactCanvasWorkspace,
  editArtifactCanvasWorkspaceContent,
  formatArtifactCanvasData,
  markArtifactCanvasWorkspaceSaved,
  redoArtifactCanvasWorkspaceContent,
  reconcileArtifactCanvasWorkspace,
  requestArtifactCanvasTabClose,
  selectArtifactCanvasWorkspaceTab,
  setArtifactCanvasViewMode,
  toggleArtifactCanvasTabPin,
  undoArtifactCanvasWorkspaceContent,
} from './artifactCanvasEventModel';
import type {
  ArtifactCanvasViewMode,
  LiveArtifactCanvasState,
} from './artifactCanvasEventModel';
import {
  a2uiCommandToHitlSubmission,
  type A2UISurfaceAuthority,
} from './a2uiSurfaceAuthorityModel';
import {
  createArtifactSaveCommandV2,
  isEditableArtifactMime,
} from './artifactContentContractV2';
import { ArtifactPreviewSurface } from './ArtifactPreviewSurface';
import {
  DesktopArtifactRequestError,
  type ArtifactContentContractV2,
  type DesktopArtifactClient,
} from './desktopArtifactClient';
import { DesktopA2UISurface } from './DesktopA2UISurface';
import type { HitlResponseSubmission } from '../../types';
import './LiveArtifactCanvas.css';

type LiveArtifactCanvasProps = {
  state: LiveArtifactCanvasState;
  onSelect: (artifactId: string) => void;
  a2uiAuthorities?: Readonly<Record<string, A2UISurfaceAuthority>>;
  onRespondToA2UI?: (submission: HitlResponseSubmission) => Promise<void>;
  artifactClient?: DesktopArtifactClient;
};

type ArtifactConflictNotice = {
  serverRevision: number;
  serverContentHash: string;
};

const safeMarkdownComponents: Components = {
  a: ({ children }) => <span className="artifact-markdown-link">{children}</span>,
  img: ({ alt }) => <span className="artifact-markdown-image">[{alt ?? 'image'}]</span>,
};

export function LiveArtifactCanvas({
  state,
  onSelect,
  a2uiAuthorities = {},
  onRespondToA2UI,
  artifactClient,
}: LiveArtifactCanvasProps) {
  const { t } = useI18n();
  const [workspace, setWorkspace] = useState(() => createArtifactCanvasWorkspace(state));
  const [notice, setNotice] = useState<string | null>(null);
  const [authorities, setAuthorities] = useState<
    Record<string, ArtifactContentContractV2>
  >({});
  const [conflicts, setConflicts] = useState<Record<string, ArtifactConflictNotice>>({});
  const [savingArtifactId, setSavingArtifactId] = useState<string | null>(null);

  useEffect(() => {
    setWorkspace((current) => reconcileArtifactCanvasWorkspace(current, state));
  }, [state]);

  const active =
    workspace.tabs.find((candidate) => candidate.id === workspace.activeArtifactId) ??
    workspace.tabs[workspace.tabs.length - 1];
  const pendingClose = workspace.tabs.find(
    (candidate) => candidate.id === workspace.pendingCloseArtifactId,
  );

  const activeId = active?.id ?? null;
  const activeContentType = active?.contentType ?? null;

  useEffect(() => {
    if (!artifactClient || !activeId || activeContentType === 'a2ui_surface') {
      return undefined;
    }
    const controller = new AbortController();
    void artifactClient
      .loadContent(activeId, controller.signal)
      .then((authority) => {
        if (controller.signal.aborted) return;
        setAuthorities((current) => ({ ...current, [activeId]: authority }));
        setWorkspace((current) =>
          applyArtifactCanvasWorkspaceAuthorityContent(
            current,
            activeId,
            authority.content,
            authority.mime_type,
            true,
          ),
        );
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted || isAbortError(error)) return;
      });
    return () => controller.abort();
  }, [activeContentType, activeId, artifactClient]);

  const saveActive = useCallback(async () => {
    if (!artifactClient || !activeId) return;
    const tab = workspace.tabs.find((candidate) => candidate.id === activeId);
    const authority = authorities[activeId];
    if (!tab || !tab.dirty || !authority || !isEditableArtifactMime(authority.mime_type)) {
      return;
    }
    const draftContentHash = await artifactContentHash(tab.draftContent);
    const command = createArtifactSaveCommandV2({
      authority,
      draftContent: tab.draftContent,
      draftContentHash,
      expectedRevision: authority.revision,
      idempotencyKey: artifactSaveIdempotencyKey(activeId, authority.revision, draftContentHash),
    });
    if (!command.ok) {
      setNotice(t('artifact.saveFailed'));
      return;
    }

    setSavingArtifactId(activeId);
    try {
      const receipt = await artifactClient.saveContent(activeId, command.command);
      setAuthorities((current) => ({
        ...current,
        [activeId]: {
          ...authority,
          revision: receipt.revision,
          content_hash: receipt.content_hash,
          content: tab.draftContent,
        },
      }));
      setWorkspace((current) => markArtifactCanvasWorkspaceSaved(current, activeId));
      setConflicts((current) => omitArtifactRecord(current, activeId));
      setNotice(t('artifact.saved'));
    } catch (error: unknown) {
      if (
        error instanceof DesktopArtifactRequestError &&
        error.httpStatus === 409 &&
        error.serverRevision !== null &&
        error.serverContentHash !== null
      ) {
        setConflicts((current) => ({
          ...current,
          [activeId]: {
            serverRevision: error.serverRevision!,
            serverContentHash: error.serverContentHash!,
          },
        }));
        setNotice(t('artifact.saveConflict'));
      } else {
        setNotice(t('artifact.saveFailed'));
      }
    } finally {
      setSavingArtifactId((current) => (current === activeId ? null : current));
    }
  }, [activeId, artifactClient, authorities, t, workspace.tabs]);

  if (!active) return null;
  const title = active.title || t('artifact.untitled');
  const language = active.language || active.contentType;
  const a2uiAuthority = a2uiAuthorities[active.id] ?? null;
  const activeAuthority = authorities[active.id] ?? null;
  const activeConflict = conflicts[active.id] ?? null;
  const canSave = Boolean(
    ARTIFACT_CANVAS_SAVE_CAPABILITY.available &&
      artifactClient &&
      activeAuthority &&
      isEditableArtifactMime(activeAuthority.mime_type) &&
      active.dirty &&
      savingArtifactId !== active.id,
  );

  const selectTab = (artifactId: string) => {
    setWorkspace((current) => selectArtifactCanvasWorkspaceTab(current, artifactId));
    onSelect(artifactId);
  };

  const closeTab = (artifactId: string) => {
    const result = requestArtifactCanvasTabClose(workspace, artifactId);
    setWorkspace(result.state);
    if (result.status === 'blocked_pinned') {
      setNotice(t('artifact.pinnedCloseUnavailable'));
    } else if (
      result.status === 'closed' &&
      result.state.activeArtifactId &&
      result.state.activeArtifactId !== workspace.activeArtifactId
    ) {
      onSelect(result.state.activeArtifactId);
    }
  };

  const discardPendingChanges = () => {
    const next = confirmArtifactCanvasTabClose(workspace);
    setWorkspace(next);
    if (next.activeArtifactId && next.activeArtifactId !== workspace.activeArtifactId) {
      onSelect(next.activeArtifactId);
    }
  };

  const copyActiveContent = async () => {
    try {
      await navigator.clipboard.writeText(active.draftContent);
      setNotice(t('artifact.copied'));
    } catch {
      setNotice(t('artifact.copyFailed'));
    }
  };

  const downloadActiveContent = async () => {
    try {
      if (artifactClient) {
        const blob = await artifactClient.download(active.id);
        triggerArtifactDownload(blob, active.title);
        setNotice(t('artifact.downloaded'));
        return;
      }
      const descriptor = artifactCanvasDownloadDescriptor(active);
      triggerArtifactDownload(
        new Blob([descriptor.content], { type: descriptor.mimeType }),
        descriptor.filename,
      );
      setNotice(t('artifact.downloaded'));
    } catch {
      setNotice(t('artifact.downloadFailed'));
    }
  };

  const reloadConflictAuthority = async () => {
    if (!artifactClient) return;
    try {
      const authority = await artifactClient.loadContent(active.id);
      setAuthorities((current) => ({ ...current, [active.id]: authority }));
      setWorkspace((current) =>
        applyArtifactCanvasWorkspaceAuthorityContent(
          current,
          active.id,
          authority.content,
          authority.mime_type,
          true,
        ),
      );
      setConflicts((current) => omitArtifactRecord(current, active.id));
      setNotice(t('artifact.serverReloadedDraftPreserved'));
    } catch {
      setNotice(t('artifact.previewFailed'));
    }
  };

  const saveConflictCopy = () => {
    triggerArtifactDownload(
      new Blob([active.draftContent], {
        type: activeAuthority?.mime_type ?? 'text/plain;charset=utf-8',
      }),
      `${active.title || 'artifact'}.draft`,
    );
    setNotice(t('artifact.draftCopySaved'));
  };

  const copyConflictDraft = async () => {
    try {
      await navigator.clipboard.writeText(active.draftContent);
      setNotice(t('artifact.copied'));
    } catch {
      setNotice(t('artifact.copyFailed'));
    }
  };

  const modeIcon = (mode: ArtifactCanvasViewMode) => {
    if (mode === 'markdown') return <FileTextIcon aria-hidden="true" />;
    if (mode === 'data') return <TableIcon aria-hidden="true" />;
    if (mode === 'preview') return <EyeOpenIcon aria-hidden="true" />;
    return <CodeIcon aria-hidden="true" />;
  };

  return (
    <section
      className="live-artifact-canvas"
      aria-label={t('artifact.liveCanvas')}
      onKeyDown={(event) => {
        if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
          event.preventDefault();
          void saveActive();
        }
      }}
    >
      <header>
        <span className="artifact-canvas-heading">
          <FileTextIcon aria-hidden="true" />
          <span>
            <strong>{title}</strong>
            <small>{t('artifact.liveCanvasDescription')}</small>
          </span>
        </span>
        <div className="artifact-canvas-header-actions">
          <Badge color="cyan" variant="soft">
            {language}
          </Badge>
          <button type="button" onClick={copyActiveContent} title={t('artifact.copy')}>
            <ClipboardCopyIcon aria-hidden="true" />
            <span>{t('artifact.copy')}</span>
          </button>
          <button
            type="button"
            onClick={() => void downloadActiveContent()}
            title={t('artifact.download')}
          >
            <DownloadIcon aria-hidden="true" />
            <span>{t('artifact.download')}</span>
          </button>
          <button
            type="button"
            disabled={!canSave}
            title={canSave ? t('artifact.save') : t('artifact.saveUnavailable')}
            onClick={() => void saveActive()}
          >
            {savingArtifactId === active.id ? t('artifact.saving') : t('artifact.save')}
          </button>
        </div>
      </header>
      <nav role="tablist" aria-label={t('artifact.liveArtifactTabs')}>
        {workspace.tabs.map((tab) => (
          <span className={`artifact-canvas-tab ${tab.id === active.id ? 'selected' : ''}`} key={tab.id}>
            <button
              type="button"
              role="tab"
              aria-selected={tab.id === active.id}
              onClick={() => selectTab(tab.id)}
            >
              {tab.title || t('artifact.untitled')}
              {tab.dirty ? <span aria-hidden="true">•</span> : null}
            </button>
            <button
              type="button"
              className="artifact-canvas-tab-action"
              aria-label={t(tab.pinned ? 'artifact.unpinTab' : 'artifact.pinTab', {
                title: tab.title || t('artifact.untitled'),
              })}
              aria-pressed={tab.pinned}
              onClick={() =>
                setWorkspace((current) => toggleArtifactCanvasTabPin(current, tab.id))
              }
            >
              <DrawingPinIcon aria-hidden="true" />
            </button>
            <button
              type="button"
              className="artifact-canvas-tab-action"
              aria-label={t('artifact.closeTab', {
                title: tab.title || t('artifact.untitled'),
              })}
              disabled={tab.pinned}
              onClick={() => closeTab(tab.id)}
            >
              <Cross2Icon aria-hidden="true" />
            </button>
          </span>
        ))}
      </nav>
      <div
        className="artifact-canvas-mode-switcher"
        role="radiogroup"
        aria-label={t('artifact.viewModeGroup')}
      >
        {ARTIFACT_CANVAS_VIEW_MODES.map((mode) => (
          <button
            type="button"
            role="radio"
            aria-checked={active.viewMode === mode}
            className={active.viewMode === mode ? 'selected' : ''}
            key={mode}
            onClick={() =>
              setWorkspace((current) => setArtifactCanvasViewMode(current, active.id, mode))
            }
          >
            {modeIcon(mode)}
            {t(`artifact.viewMode.${mode}`)}
          </button>
        ))}
        <span className="artifact-canvas-history-actions">
          <button
            type="button"
            disabled={active.undoStack.length === 0}
            onClick={() =>
              setWorkspace((current) =>
                undoArtifactCanvasWorkspaceContent(current, active.id),
              )
            }
          >
            {t('artifact.undo')}
          </button>
          <button
            type="button"
            disabled={active.redoStack.length === 0}
            onClick={() =>
              setWorkspace((current) =>
                redoArtifactCanvasWorkspaceContent(current, active.id),
              )
            }
          >
            {t('artifact.redo')}
          </button>
        </span>
      </div>
      <article aria-label={t('artifact.liveArtifactContent', { title })}>
        {active.viewMode === 'code' ? (
          <textarea
            aria-label={t('artifact.editorLabel', { title })}
            spellCheck={false}
            value={active.draftContent}
            onChange={(event) =>
              setWorkspace((current) =>
                editArtifactCanvasWorkspaceContent(current, active.id, event.target.value),
              )
            }
          />
        ) : null}
        {active.viewMode === 'markdown' ? (
          <div className="artifact-canvas-markdown" aria-label={t('artifact.markdownLabel')}>
            <ReactMarkdown skipHtml components={safeMarkdownComponents}>
              {active.draftContent}
            </ReactMarkdown>
          </div>
        ) : null}
        {active.viewMode === 'data' ? (
          <pre aria-label={t('artifact.dataLabel')}>
            <code>{formatArtifactCanvasData(active.draftContent)}</code>
          </pre>
        ) : null}
        {active.viewMode === 'preview' ? (
          active.contentType === 'a2ui_surface' ? (
            <DesktopA2UISurface
              messages={active.draftContent}
              requestId={a2uiAuthority?.requestId ?? null}
              authorityRevision={a2uiAuthority?.authorityRevision ?? null}
              idempotencyKey={a2uiAuthority?.idempotencyKey ?? null}
              allowedActions={a2uiAuthority?.allowedActions ?? []}
              answered={a2uiAuthority?.answered ?? false}
              canRespond={Boolean(a2uiAuthority?.canRespond && onRespondToA2UI)}
              onCommand={async (command) => {
                if (!onRespondToA2UI) return;
                await onRespondToA2UI(a2uiCommandToHitlSubmission(command));
              }}
            />
          ) : (
            artifactClient ? (
              <ArtifactPreviewSurface
                key={`${active.id}:${active.mimeType ?? active.contentType}`}
                artifactId={active.id}
                client={artifactClient}
                mimeType={active.mimeType ?? active.contentType}
                sizeBytes={active.sizeBytes}
                title={title}
              />
            ) : (
              <pre aria-label={t('artifact.previewLabel')}>
                <code>{active.draftContent}</code>
              </pre>
            )
          )
        ) : null}
      </article>
      {activeConflict ? (
        <div
          className="artifact-canvas-conflict"
          role="alert"
          data-server-revision={activeConflict.serverRevision}
          data-server-content-hash={activeConflict.serverContentHash}
        >
          <strong>{t('artifact.conflictTitle')}</strong>
          <span>{t('artifact.conflictDescription')}</span>
          <div>
            <button type="button" onClick={() => void reloadConflictAuthority()}>
              {t('artifact.reloadServer')}
            </button>
            <button type="button" onClick={saveConflictCopy}>
              {t('artifact.saveCopy')}
            </button>
            <button type="button" onClick={() => void copyConflictDraft()}>
              {t('artifact.copyDraft')}
            </button>
          </div>
        </div>
      ) : null}
      {notice ? (
        <div className="artifact-canvas-notice" role="status">
          <span>{notice}</span>
          <button type="button" onClick={() => setNotice(null)} aria-label={t('common.dismiss')}>
            <Cross2Icon aria-hidden="true" />
          </button>
        </div>
      ) : null}
      {pendingClose ? (
        <div className="artifact-canvas-confirmation-backdrop">
          <div
            className="artifact-canvas-confirmation"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="artifact-unsaved-title"
            aria-describedby="artifact-unsaved-description"
          >
            <strong id="artifact-unsaved-title">{t('artifact.unsavedTitle')}</strong>
            <p id="artifact-unsaved-description">
              {t('artifact.unsavedDescription', {
                title: pendingClose.title || t('artifact.untitled'),
              })}
            </p>
            <div>
              <button
                type="button"
                onClick={() =>
                  setWorkspace((current) => cancelArtifactCanvasTabClose(current))
                }
              >
                {t('common.cancel')}
              </button>
              <button type="button" onClick={discardPendingChanges}>
                {t('artifact.discardChanges')}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}

async function artifactContentHash(content: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(content));
  return `sha256:${[...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('')}`;
}

function artifactSaveIdempotencyKey(
  _artifactId: string,
  revision: number,
  contentHash: string,
): string {
  return `artifact:${revision}:${contentHash.slice('sha256:'.length, 39)}`;
}

function triggerArtifactDownload(blob: Blob, filename: string): void {
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = objectUrl;
  anchor.download =
    filename
      .split(/[\\/]/u)
      .filter(Boolean)
      .at(-1)
      ?.replace(/[\u0000-\u001f<>:"/\\|?*]/gu, '_') || 'artifact';
  anchor.hidden = true;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(objectUrl);
}

function omitArtifactRecord<T>(record: Record<string, T>, artifactId: string): Record<string, T> {
  return Object.fromEntries(
    Object.entries(record).filter(([candidate]) => candidate !== artifactId),
  );
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError';
}
