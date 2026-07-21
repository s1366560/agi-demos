import { memo, useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactElement } from 'react';

import { useTranslation } from 'react-i18next';

import { message } from 'antd';
import {
  AlertCircle,
  ChevronDown,
  ChevronRight,
  Database,
  File,
  FileArchive,
  FileAudio,
  FileCode2,
  FileImage,
  FileText,
  FileVideo,
  Folder,
  FolderOpen,
  HardDrive,
  Loader2,
  PanelLeftClose,
  PanelLeftOpen,
  RefreshCw,
} from 'lucide-react';

import { useCanvasActions, type CanvasContentType } from '@/stores/canvasStore';

import { artifactService, fetchArtifactResource } from '@/services/artifactService';
import { projectSandboxService } from '@/services/projectSandboxService';

import { isCanvasPreviewable, isOfficeExtension, isOfficeMimeType } from '@/utils/filePreview';
import { isSafeArtifactUrl, pathMatchesArtifact } from '@/utils/sandboxArtifactPath';

import {
  buildArtifactFileTree,
  buildSandboxFileTree,
  parseSandboxGlobPaths,
  type CanvasFileNode,
  type CanvasFileSource,
} from './canvasFileTreeModel';

import type { Artifact } from '@/types/agent';
import type { ExecuteToolResponse } from '@/services/projectSandboxService';

interface CanvasFileExplorerProps {
  projectId?: string | undefined;
  tenantId?: string | undefined;
  workspaceId?: string | null | undefined;
}

interface SourceLoadState {
  nodes: CanvasFileNode[];
  loading: boolean;
  loaded: boolean;
  error: string | null;
}

const INITIAL_SOURCE_STATE: Record<CanvasFileSource, SourceLoadState> = {
  sandbox: { nodes: [], loading: false, loaded: false, error: null },
  artifacts: { nodes: [], loading: false, loaded: false, error: null },
};

const TEXT_FILE_EXTENSIONS = new Set([
  'txt',
  'md',
  'markdown',
  'json',
  'jsonl',
  'yaml',
  'yml',
  'toml',
  'csv',
  'tsv',
  'xml',
  'html',
  'htm',
  'svg',
  'css',
  'scss',
  'less',
  'js',
  'jsx',
  'ts',
  'tsx',
  'mjs',
  'cjs',
  'py',
  'pyi',
  'go',
  'rs',
  'java',
  'kt',
  'kts',
  'rb',
  'php',
  'sh',
  'bash',
  'zsh',
  'fish',
  'sql',
  'log',
  'ini',
  'cfg',
  'conf',
  'env',
  'dockerfile',
  'gitignore',
  'gitattributes',
  'prettierrc',
  'eslintrc',
]);

const BINARY_FILE_EXTENSIONS = new Set([
  'png',
  'jpg',
  'jpeg',
  'gif',
  'webp',
  'avif',
  'ico',
  'pdf',
  'doc',
  'docx',
  'xls',
  'xlsx',
  'ppt',
  'pptx',
  'mp3',
  'wav',
  'ogg',
  'mp4',
  'webm',
  'mov',
  'zip',
  'tar',
  'gz',
  'tgz',
  'rar',
  '7z',
  'bin',
  'wasm',
  'sqlite',
  'db',
]);

const DATA_EXTENSIONS = new Set(['json', 'jsonl', 'csv', 'tsv', 'xml', 'yaml', 'yml', 'toml']);
const MARKDOWN_EXTENSIONS = new Set(['md', 'markdown']);
const PREVIEW_TEXT_EXTENSIONS = new Set(['html', 'htm', 'svg']);
const CODE_BASENAMES = new Set(['dockerfile', 'makefile', 'gemfile', 'rakefile', 'procfile']);

function cloneInitialSourceState(): Record<CanvasFileSource, SourceLoadState> {
  return {
    sandbox: { ...INITIAL_SOURCE_STATE.sandbox },
    artifacts: { ...INITIAL_SOURCE_STATE.artifacts },
  };
}

function getFileExtension(path: string): string {
  const name = getFileName(path);
  const dotIndex = name.lastIndexOf('.');
  return dotIndex >= 0 ? name.slice(dotIndex + 1).toLowerCase() : '';
}

function getFileName(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).at(-1) ?? path;
}

function getBasename(path: string): string {
  const name = getFileName(path);
  const dotIndex = name.lastIndexOf('.');
  return (dotIndex >= 0 ? name.slice(0, dotIndex) : name).toLowerCase();
}

function getMimeTypeForPath(path: string): string | undefined {
  const ext = getFileExtension(path);
  if (ext === 'md' || ext === 'markdown') return 'text/markdown';
  if (ext === 'html' || ext === 'htm') return 'text/html';
  if (ext === 'svg') return 'image/svg+xml';
  if (ext === 'json' || ext === 'jsonl') return 'application/json';
  if (ext === 'csv') return 'text/csv';
  if (ext === 'pdf') return 'application/pdf';
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'avif'].includes(ext)) {
    return `image/${ext === 'jpg' ? 'jpeg' : ext}`;
  }
  if (['mp3', 'wav', 'ogg'].includes(ext)) return `audio/${ext}`;
  if (['mp4', 'webm'].includes(ext)) return `video/${ext}`;
  if (TEXT_FILE_EXTENSIONS.has(ext) || CODE_BASENAMES.has(getBasename(path))) {
    return 'text/plain';
  }
  return undefined;
}

function getCanvasTypeForFile(path: string, mimeType?: string | null): CanvasContentType {
  const mime = (mimeType ?? '').toLowerCase();
  const ext = getFileExtension(path);
  if (mime.includes('markdown') || MARKDOWN_EXTENSIONS.has(ext)) return 'markdown';
  if (
    mime.includes('json') ||
    mime.includes('csv') ||
    mime.includes('xml') ||
    mime.includes('yaml') ||
    mime.includes('toml') ||
    DATA_EXTENSIONS.has(ext)
  ) {
    return 'data';
  }
  if (mime.includes('html') || mime.includes('svg') || PREVIEW_TEXT_EXTENSIONS.has(ext)) {
    return 'preview';
  }
  return 'code';
}

function getArtifactUrl(artifact: Artifact): string {
  return artifact.url || artifact.previewUrl || artifactService.getDownloadUrl(artifact.id);
}

function isTextSandboxFile(path: string): boolean {
  const ext = getFileExtension(path);
  if (TEXT_FILE_EXTENSIONS.has(ext)) return true;
  if (BINARY_FILE_EXTENSIONS.has(ext)) return false;
  return CODE_BASENAMES.has(getBasename(path));
}

function isTextArtifact(artifact: Artifact): boolean {
  const mime = artifact.mimeType.toLowerCase();
  const ext = getFileExtension(artifact.filename);
  return (
    mime.startsWith('text/') ||
    mime.includes('json') ||
    mime.includes('csv') ||
    mime.includes('xml') ||
    mime.includes('yaml') ||
    mime.includes('toml') ||
    artifact.category === 'code' ||
    artifact.category === 'data' ||
    TEXT_FILE_EXTENSIONS.has(ext)
  );
}

function isPdfFile(path: string, mimeType?: string): boolean {
  return (
    mimeType?.toLowerCase().includes('application/pdf') === true || getFileExtension(path) === 'pdf'
  );
}

function isPreviewableByUrl(path: string, mimeType?: string): boolean {
  const mime = (mimeType ?? '').toLowerCase();
  return (
    isPdfFile(path, mime) ||
    mime.startsWith('image/') ||
    mime.startsWith('video/') ||
    mime.startsWith('audio/') ||
    isOfficeMimeType(mime) ||
    isOfficeExtension(path) ||
    isCanvasPreviewable(mime, path)
  );
}

function extractToolText(result: ExecuteToolResponse): string {
  return result.content
    .map((item) => item.text)
    .filter((text): text is string => typeof text === 'string')
    .join('\n');
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim().length > 0) return error.message;
  if (typeof error === 'string' && error.trim().length > 0) return error;
  return 'Unknown error';
}

function getNodeIcon(node: CanvasFileNode) {
  const mime = node.artifact?.mimeType.toLowerCase() ?? getMimeTypeForPath(node.name) ?? '';
  const ext = getFileExtension(node.name);
  if (
    mime.startsWith('image/') ||
    ['png', 'jpg', 'jpeg', 'gif', 'webp', 'avif', 'svg'].includes(ext)
  ) {
    return <FileImage size={14} />;
  }
  if (mime.startsWith('video/') || ['mp4', 'webm', 'mov'].includes(ext))
    return <FileVideo size={14} />;
  if (mime.startsWith('audio/') || ['mp3', 'wav', 'ogg'].includes(ext))
    return <FileAudio size={14} />;
  if (['zip', 'tar', 'gz', 'tgz', 'rar', '7z'].includes(ext)) return <FileArchive size={14} />;
  if (TEXT_FILE_EXTENSIONS.has(ext) || CODE_BASENAMES.has(getBasename(node.name))) {
    return <FileCode2 size={14} />;
  }
  if (mime.startsWith('text/') || mime.includes('pdf') || isOfficeExtension(node.name)) {
    return <FileText size={14} />;
  }
  return <File size={14} />;
}

function formatFileSize(sizeBytes: number | undefined): string {
  if (sizeBytes === undefined || sizeBytes < 0) return '';
  if (sizeBytes < 1024) return `${sizeBytes} B`;
  const units = ['KB', 'MB', 'GB'];
  let size = sizeBytes / 1024;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size.toFixed(size >= 10 ? 0 : 1)} ${units[unitIndex]}`;
}

const TreeNode = memo<{
  node: CanvasFileNode;
  depth: number;
  expandedIds: Set<string>;
  openingPath: string | null;
  onToggle: (node: CanvasFileNode) => void;
  onOpen: (node: CanvasFileNode) => void;
}>(({ node, depth, expandedIds, openingPath, onToggle, onOpen }) => {
  const expanded = expandedIds.has(node.id);
  const opening = openingPath === node.path;
  const isDirectory = node.kind === 'directory';
  const sizeLabel = node.artifact ? formatFileSize(node.artifact.sizeBytes) : '';
  const paddingLeft = 8 + depth * 14;

  return (
    <div>
      <button
        type="button"
        title={node.path}
        onClick={() => {
          if (isDirectory) {
            onToggle(node);
            return;
          }
          onOpen(node);
        }}
        className="group flex h-7 w-full min-w-0 items-center gap-1.5 pr-2 text-left text-xs text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-slate-50"
        style={{ paddingLeft }}
      >
        <span className="flex h-4 w-4 shrink-0 items-center justify-center text-slate-400">
          {isDirectory ? (
            expanded ? (
              <ChevronDown size={13} />
            ) : (
              <ChevronRight size={13} />
            )
          ) : (
            <span className="h-3.5 w-3.5" />
          )}
        </span>
        <span className="flex h-4 w-4 shrink-0 items-center justify-center text-slate-400">
          {isDirectory ? (
            expanded ? (
              <FolderOpen size={14} />
            ) : (
              <Folder size={14} />
            )
          ) : opening ? (
            <Loader2 size={13} className="animate-spin" />
          ) : (
            getNodeIcon(node)
          )}
        </span>
        <span className="min-w-0 flex-1 truncate">{node.name}</span>
        {sizeLabel && (
          <span className="hidden shrink-0 text-2xs text-slate-400 group-hover:block">
            {sizeLabel}
          </span>
        )}
      </button>
      {isDirectory && expanded && node.children.length > 0 && (
        <div>
          {node.children.map((child) => (
            <TreeNode
              key={child.id}
              node={child}
              depth={depth + 1}
              expandedIds={expandedIds}
              openingPath={openingPath}
              onToggle={onToggle}
              onOpen={onOpen}
            />
          ))}
        </div>
      )}
    </div>
  );
});
TreeNode.displayName = 'TreeNode';

export const CanvasFileExplorer = memo<CanvasFileExplorerProps>(({ projectId }) => {
  const { t } = useTranslation();
  const { openTab } = useCanvasActions();
  const [activeSource, setActiveSource] = useState<CanvasFileSource>('sandbox');
  const [collapsed, setCollapsed] = useState(false);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() => new Set());
  const [openingPath, setOpeningPath] = useState<string | null>(null);
  const [sourceState, setSourceState] =
    useState<Record<CanvasFileSource, SourceLoadState>>(cloneInitialSourceState);

  useEffect(() => {
    setExpandedIds(new Set());
    setSourceState(cloneInitialSourceState());
  }, [projectId]);

  const activeState = sourceState[activeSource];

  const updateSourceState = useCallback(
    (source: CanvasFileSource, patch: Partial<SourceLoadState>) => {
      setSourceState((current) => ({
        ...current,
        [source]: { ...current[source], ...patch },
      }));
    },
    []
  );

  const loadSource = useCallback(
    async (source: CanvasFileSource, force = false) => {
      const currentState = sourceState[source];
      if (!force && (currentState.loading || currentState.loaded)) return;
      if (!projectId) {
        updateSourceState(source, {
          nodes: [],
          loading: false,
          loaded: true,
          error: t('agent.canvas.fileExplorer.noProject', {
            defaultValue: 'Select a project to browse files.',
          }),
        });
        return;
      }

      updateSourceState(source, { loading: true, error: null });
      try {
        if (source === 'sandbox') {
          const result = await projectSandboxService.executeTool(projectId, {
            tool_name: 'glob',
            arguments: { pattern: '**/*', path: '/workspace', max_results: 500 },
            timeout: 30,
          });
          const text = extractToolText(result);
          if (!result.success || result.is_error) {
            throw new Error(
              text ||
                t('agent.canvas.fileExplorer.loadFailed', {
                  defaultValue: 'Failed to load files',
                })
            );
          }
          updateSourceState(source, {
            nodes: buildSandboxFileTree(parseSandboxGlobPaths(text)),
            loading: false,
            loaded: true,
            error: null,
          });
          return;
        }

        const { artifacts } = await artifactService.list(projectId, { limit: 500 });
        updateSourceState(source, {
          nodes: buildArtifactFileTree(artifacts),
          loading: false,
          loaded: true,
          error: null,
        });
      } catch (error) {
        updateSourceState(source, {
          nodes: [],
          loading: false,
          loaded: true,
          error: getErrorMessage(error),
        });
      }
    },
    [projectId, sourceState, t, updateSourceState]
  );

  useEffect(() => {
    void loadSource(activeSource);
  }, [activeSource, loadSource]);

  const sourceOptions = useMemo(
    () =>
      [
        {
          id: 'sandbox' as const,
          label: t('agent.canvas.fileExplorer.sandbox', { defaultValue: 'Sandbox' }),
          icon: <HardDrive size={13} />,
        },
        {
          id: 'artifacts' as const,
          label: t('agent.canvas.fileExplorer.artifacts', { defaultValue: 'Artifacts' }),
          icon: <Database size={13} />,
        },
      ] satisfies Array<{
        id: CanvasFileSource;
        label: string;
        icon: ReactElement;
      }>,
    [t]
  );

  const handleToggleNode = useCallback((node: CanvasFileNode) => {
    setExpandedIds((current) => {
      const next = new Set(current);
      if (next.has(node.id)) {
        next.delete(node.id);
      } else {
        next.add(node.id);
      }
      return next;
    });
  }, []);

  const openPreviewTab = useCallback(
    (params: {
      id: string;
      title: string;
      url: string;
      mimeType?: string | undefined;
      artifactId?: string | undefined;
    }) => {
      if (!isSafeArtifactUrl(params.url)) {
        void message.warning(
          t('agent.canvas.fileExplorer.noPreview', {
            defaultValue: 'No preview is available for this file.',
          })
        );
        return;
      }
      openTab({
        id: params.id,
        title: params.title,
        type: 'preview',
        content: params.url,
        mimeType: params.mimeType,
        pdfVerified: isPdfFile(params.title, params.mimeType) || undefined,
        artifactId: params.artifactId,
        artifactUrl: params.url,
        previewMode: 'url',
      });
    },
    [openTab, t]
  );

  const openTextTab = useCallback(
    (params: {
      id: string;
      title: string;
      content: string;
      mimeType?: string | undefined;
      artifactId?: string | undefined;
      artifactUrl?: string | undefined;
    }) => {
      openTab({
        id: params.id,
        title: params.title,
        type: getCanvasTypeForFile(params.title, params.mimeType),
        content: params.content,
        language: getFileExtension(params.title) || undefined,
        mimeType: params.mimeType,
        artifactId: params.artifactId,
        artifactUrl: params.artifactUrl,
      });
    },
    [openTab]
  );

  const openSandboxNode = useCallback(
    async (node: CanvasFileNode) => {
      if (!projectId) return;

      if (isTextSandboxFile(node.path)) {
        const result = await projectSandboxService.executeTool(projectId, {
          tool_name: 'read',
          arguments: { file_path: node.path, offset: 0, limit: 50000, raw: true },
          timeout: 30,
        });
        const text = extractToolText(result);
        if (!result.success || result.is_error) {
          throw new Error(
            text ||
              t('agent.canvas.fileExplorer.openFailed', {
                defaultValue: 'Failed to open file',
              })
          );
        }
        const mimeType = getMimeTypeForPath(node.name);
        openTextTab({
          id: `sandbox:${projectId}:${node.path}`,
          title: node.name,
          content: text,
          mimeType,
        });
        return;
      }

      const { artifacts } = await artifactService.list(projectId, { limit: 500 });
      const artifact = artifacts.find((item) => pathMatchesArtifact(node.path, item));
      if (!artifact) {
        void message.warning(
          t('agent.canvas.fileExplorer.noPreview', {
            defaultValue: 'No preview is available for this file.',
          })
        );
        return;
      }

      const url = getArtifactUrl(artifact);
      if (!isPreviewableByUrl(artifact.filename, artifact.mimeType)) {
        void message.warning(
          t('agent.canvas.fileExplorer.noPreview', {
            defaultValue: 'No preview is available for this file.',
          })
        );
        return;
      }
      openPreviewTab({
        id: `artifact:${artifact.id}`,
        title: artifact.filename || node.name,
        url,
        mimeType: artifact.mimeType,
        artifactId: artifact.id,
      });
    },
    [openPreviewTab, openTextTab, projectId, t]
  );

  const openArtifactNode = useCallback(
    async (node: CanvasFileNode) => {
      const artifact = node.artifact;
      if (!artifact) return;
      const url = getArtifactUrl(artifact);

      if (isTextArtifact(artifact)) {
        const response = await fetchArtifactResource(url);
        if (!response.ok) {
          throw new Error(
            t('agent.canvas.fileExplorer.openFailed', {
              defaultValue: 'Failed to open file',
            })
          );
        }
        const responseMimeType = response.headers.get('content-type')?.toLowerCase() || undefined;
        const content = await response.text();
        openTextTab({
          id: `artifact:${artifact.id}`,
          title: artifact.filename,
          content,
          mimeType: responseMimeType || artifact.mimeType,
          artifactId: artifact.id,
          artifactUrl: url,
        });
        return;
      }

      if (!isPreviewableByUrl(artifact.filename, artifact.mimeType)) {
        void message.warning(
          t('agent.canvas.fileExplorer.noPreview', {
            defaultValue: 'No preview is available for this file.',
          })
        );
        return;
      }

      openPreviewTab({
        id: `artifact:${artifact.id}`,
        title: artifact.filename,
        url,
        mimeType: artifact.mimeType,
        artifactId: artifact.id,
      });
    },
    [openPreviewTab, openTextTab, t]
  );

  const handleOpenNode = useCallback(
    async (node: CanvasFileNode) => {
      if (node.kind === 'directory') {
        handleToggleNode(node);
        return;
      }

      setOpeningPath(node.path);
      try {
        if (node.source === 'sandbox') {
          await openSandboxNode(node);
        } else {
          await openArtifactNode(node);
        }
      } catch (error) {
        void message.error(
          t('agent.canvas.fileExplorer.openFailedWithMessage', {
            defaultValue: 'Failed to open file: {{message}}',
            message: getErrorMessage(error),
          })
        );
      } finally {
        setOpeningPath(null);
      }
    },
    [handleToggleNode, openArtifactNode, openSandboxNode, t]
  );

  if (collapsed) {
    return (
      <aside className="hidden h-full w-10 shrink-0 border-r border-slate-200 bg-slate-50/90 md:flex dark:border-slate-800 dark:bg-slate-950/90">
        <button
          type="button"
          aria-label={t('agent.canvas.fileExplorer.expand', {
            defaultValue: 'Expand file browser',
          })}
          title={t('agent.canvas.fileExplorer.expand', {
            defaultValue: 'Expand file browser',
          })}
          onClick={() => {
            setCollapsed(false);
          }}
          className="flex h-10 w-full items-center justify-center text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
        >
          <PanelLeftOpen size={16} />
        </button>
      </aside>
    );
  }

  return (
    <aside className="hidden h-full w-[260px] shrink-0 flex-col border-r border-slate-200 bg-slate-50/90 md:flex xl:w-[272px] dark:border-slate-800 dark:bg-slate-950/90">
      <div className="flex h-10 shrink-0 items-center gap-2 border-b border-slate-200 px-2 dark:border-slate-800">
        <span className="min-w-0 flex-1 truncate text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
          {t('agent.canvas.fileExplorer.title', { defaultValue: 'Files' })}
        </span>
        <button
          type="button"
          aria-label={t('agent.canvas.fileExplorer.refresh', { defaultValue: 'Refresh files' })}
          title={t('agent.canvas.fileExplorer.refresh', { defaultValue: 'Refresh files' })}
          onClick={() => {
            void loadSource(activeSource, true);
          }}
          className="flex h-7 w-7 items-center justify-center rounded-md text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 disabled:cursor-not-allowed disabled:opacity-60 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
          disabled={activeState.loading}
        >
          <RefreshCw size={14} className={activeState.loading ? 'animate-spin' : undefined} />
        </button>
        <button
          type="button"
          aria-label={t('agent.canvas.fileExplorer.collapse', {
            defaultValue: 'Collapse file browser',
          })}
          title={t('agent.canvas.fileExplorer.collapse', {
            defaultValue: 'Collapse file browser',
          })}
          onClick={() => {
            setCollapsed(true);
          }}
          className="flex h-7 w-7 items-center justify-center rounded-md text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
        >
          <PanelLeftClose size={14} />
        </button>
      </div>

      <div className="flex shrink-0 gap-1 border-b border-slate-200 p-2 dark:border-slate-800">
        {sourceOptions.map((source) => (
          <button
            key={source.id}
            type="button"
            data-testid={`canvas-file-source-${source.id}`}
            onClick={() => {
              setActiveSource(source.id);
            }}
            className={`flex h-7 min-w-0 flex-1 items-center justify-center gap-1.5 rounded-md px-2 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 ${
              activeSource === source.id
                ? 'bg-white text-slate-900 shadow-sm ring-1 ring-slate-200 dark:bg-slate-800 dark:text-slate-50 dark:ring-slate-700'
                : 'text-slate-500 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100'
            }`}
          >
            {source.icon}
            <span className="truncate">{source.label}</span>
          </button>
        ))}
      </div>

      <div className="min-h-0 flex-1 overflow-auto py-1">
        {activeState.loading ? (
          <div className="flex h-full min-h-32 items-center justify-center gap-2 px-4 text-xs text-slate-500 dark:text-slate-400">
            <Loader2 size={14} className="animate-spin" />
            {t('agent.canvas.fileExplorer.loading', { defaultValue: 'Loading files...' })}
          </div>
        ) : activeState.error ? (
          <div className="flex min-h-32 flex-col items-center justify-center gap-2 px-4 text-center text-xs text-slate-500 dark:text-slate-400">
            <AlertCircle size={18} className="text-amber-500" />
            <div className="font-medium text-slate-700 dark:text-slate-200">
              {t('agent.canvas.fileExplorer.loadFailed', { defaultValue: 'Failed to load files' })}
            </div>
            <div className="max-w-full break-words">{activeState.error}</div>
          </div>
        ) : activeState.nodes.length === 0 ? (
          <div className="flex h-full min-h-32 items-center justify-center px-4 text-center text-xs text-slate-500 dark:text-slate-400">
            {t('agent.canvas.fileExplorer.empty', { defaultValue: 'No files found' })}
          </div>
        ) : (
          activeState.nodes.map((node) => (
            <TreeNode
              key={node.id}
              node={node}
              depth={0}
              expandedIds={expandedIds}
              openingPath={openingPath}
              onToggle={handleToggleNode}
              onOpen={handleOpenNode}
            />
          ))
        )}
      </div>
    </aside>
  );
});
CanvasFileExplorer.displayName = 'CanvasFileExplorer';
