import { useEffect, useState } from 'react';
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
  artifactCanvasDownloadDescriptor,
  cancelArtifactCanvasTabClose,
  confirmArtifactCanvasTabClose,
  createArtifactCanvasWorkspace,
  editArtifactCanvasWorkspaceContent,
  formatArtifactCanvasData,
  reconcileArtifactCanvasWorkspace,
  requestArtifactCanvasTabClose,
  selectArtifactCanvasWorkspaceTab,
  setArtifactCanvasViewMode,
  toggleArtifactCanvasTabPin,
} from './artifactCanvasEventModel';
import type {
  ArtifactCanvasViewMode,
  LiveArtifactCanvasState,
} from './artifactCanvasEventModel';
import './LiveArtifactCanvas.css';

type LiveArtifactCanvasProps = {
  state: LiveArtifactCanvasState;
  onSelect: (artifactId: string) => void;
};

const safeMarkdownComponents: Components = {
  a: ({ children }) => <span className="artifact-markdown-link">{children}</span>,
  img: ({ alt }) => <span className="artifact-markdown-image">[{alt ?? 'image'}]</span>,
};

export function LiveArtifactCanvas({ state, onSelect }: LiveArtifactCanvasProps) {
  const { t } = useI18n();
  const [workspace, setWorkspace] = useState(() => createArtifactCanvasWorkspace(state));
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    setWorkspace((current) => reconcileArtifactCanvasWorkspace(current, state));
  }, [state]);

  const active =
    workspace.tabs.find((candidate) => candidate.id === workspace.activeArtifactId) ??
    workspace.tabs[workspace.tabs.length - 1];
  const pendingClose = workspace.tabs.find(
    (candidate) => candidate.id === workspace.pendingCloseArtifactId,
  );

  if (!active) return null;
  const title = active.title || t('artifact.untitled');
  const language = active.language || active.contentType;

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

  const downloadActiveContent = () => {
    try {
      const descriptor = artifactCanvasDownloadDescriptor(active);
      const objectUrl = URL.createObjectURL(
        new Blob([descriptor.content], { type: descriptor.mimeType }),
      );
      const anchor = document.createElement('a');
      anchor.href = objectUrl;
      anchor.download = descriptor.filename;
      anchor.hidden = true;
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(objectUrl);
      setNotice(t('artifact.downloaded'));
    } catch {
      setNotice(t('artifact.downloadFailed'));
    }
  };

  const modeIcon = (mode: ArtifactCanvasViewMode) => {
    if (mode === 'markdown') return <FileTextIcon aria-hidden="true" />;
    if (mode === 'data') return <TableIcon aria-hidden="true" />;
    if (mode === 'preview') return <EyeOpenIcon aria-hidden="true" />;
    return <CodeIcon aria-hidden="true" />;
  };

  return (
    <section className="live-artifact-canvas" aria-label={t('artifact.liveCanvas')}>
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
          <button type="button" onClick={downloadActiveContent} title={t('artifact.download')}>
            <DownloadIcon aria-hidden="true" />
            <span>{t('artifact.download')}</span>
          </button>
          <button
            type="button"
            disabled={!ARTIFACT_CANVAS_SAVE_CAPABILITY.available}
            title={t('artifact.saveUnavailable')}
          >
            {t('artifact.save')}
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
          <pre aria-label={t('artifact.previewLabel')}>
            <code>{active.draftContent}</code>
          </pre>
        ) : null}
      </article>
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
