import { memo, useCallback, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { message } from 'antd';
import {
  Loader2,
  PanelRight,
  Image as ImageIcon,
  Film,
  AudioLines,
  FileText,
  Code as CodeIcon,
  Table as TableIcon,
  FileArchive,
  Paperclip,
  AlertCircle,
  File as FileIcon,
  Download,
  LoaderCircle,
} from 'lucide-react';

import { fetchArtifactResource } from '../../../services/artifactService';
import { type CanvasContentType, useCanvasStore } from '../../../stores/canvasStore';
import { useLayoutModeStore } from '../../../stores/layoutMode';
import { useSandboxStore } from '../../../stores/sandbox';
import { isOfficeMimeType, isOfficeExtension } from '../../../utils/filePreview';

import { TimeBadge } from './shared';

import type { ArtifactCreatedEvent } from '../../../types/agent';

interface ArtifactCreatedItemProps {
  event: ArtifactCreatedEvent & { error?: string | undefined };
}

const CANVAS_FORCE_VIEW_MODE_EVENT = 'canvas:force-view-mode';

function requestCanvasViewMode() {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(CANVAS_FORCE_VIEW_MODE_EVENT));
  window.setTimeout(() => {
    window.dispatchEvent(new CustomEvent(CANVAS_FORCE_VIEW_MODE_EVENT));
  }, 0);
}

function getCategoryIcon(category: string) {
  switch (category) {
    case 'image':
      return ImageIcon;
    case 'video':
      return Film;
    case 'audio':
      return AudioLines;
    case 'document':
      return FileText;
    case 'code':
      return CodeIcon;
    case 'data':
      return TableIcon;
    case 'archive':
      return FileArchive;
    default:
      return Paperclip;
  }
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${String(bytes)} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const CANVAS_COMPATIBLE_CATEGORIES = ['code', 'document', 'data', 'image', 'video', 'audio'];

const CANVAS_COMPATIBLE_MIME_TYPES = new Set([
  'application/json',
  'application/xml',
  'application/yaml',
  'application/javascript',
  'application/typescript',
  'application/x-python',
  'application/pdf',
  'application/msword',
  'application/vnd.ms-excel',
  'application/vnd.ms-powerpoint',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation',
]);

const EXTENSION_LANG_MAP: Record<string, string> = {
  py: 'python',
  js: 'javascript',
  ts: 'typescript',
  tsx: 'tsx',
  jsx: 'jsx',
  rs: 'rust',
  go: 'go',
  java: 'java',
  cpp: 'cpp',
  c: 'c',
  rb: 'ruby',
  php: 'php',
  sh: 'bash',
  sql: 'sql',
  html: 'html',
  css: 'css',
  json: 'json',
  yaml: 'yaml',
  yml: 'yaml',
  xml: 'xml',
  md: 'markdown',
  toml: 'toml',
  ini: 'ini',
  csv: 'csv',
};

const CATEGORY_CONTENT_TYPE_MAP: Record<string, CanvasContentType> = {
  code: 'code',
  document: 'markdown',
  data: 'data',
};

function getArtifactExtension(filename: string): string {
  const name = filename.split(/[\\/]/).filter(Boolean).at(-1) ?? filename;
  const dotIndex = name.lastIndexOf('.');
  return dotIndex >= 0 ? name.slice(dotIndex + 1).toLowerCase() : '';
}

function getCanvasContentTypeForArtifact(
  filename: string,
  mimeType: string,
  category: string
): CanvasContentType {
  const ext = getArtifactExtension(filename);
  const mime = mimeType.toLowerCase();
  if (ext === 'md' || ext === 'markdown' || mime.includes('markdown')) return 'markdown';
  if (
    ['json', 'jsonl', 'csv', 'tsv', 'xml', 'yaml', 'yml', 'toml'].includes(ext) ||
    mime.includes('json') ||
    mime.includes('csv') ||
    mime.includes('xml') ||
    mime.includes('yaml') ||
    mime.includes('toml')
  ) {
    return 'data';
  }
  return CATEGORY_CONTENT_TYPE_MAP[category] || 'code';
}

function isCanvasCompatible(category: string, mimeType: string): boolean {
  return (
    CANVAS_COMPATIBLE_CATEGORIES.includes(category) ||
    mimeType.startsWith('text/') ||
    mimeType.startsWith('image/') ||
    mimeType.startsWith('video/') ||
    mimeType.startsWith('audio/') ||
    CANVAS_COMPATIBLE_MIME_TYPES.has(mimeType)
  );
}

export const ArtifactCreatedItem = memo(
  function ArtifactCreatedItem({ event }: ArtifactCreatedItemProps) {
    const { t } = useTranslation();
    const [imageError, setImageError] = useState(false);
    const [imageLoaded, setImageLoaded] = useState(false);

    const storeArtifact = useSandboxStore((state) => state.artifacts.get(event.artifactId));
    const artifactUrl = storeArtifact?.url || event.url;
    const artifactPreviewUrl = storeArtifact?.previewUrl || event.previewUrl;
    const artifactError = storeArtifact?.errorMessage || event.error;
    const artifactStatus =
      storeArtifact?.status || (event.url ? 'ready' : artifactError ? 'error' : 'uploading');

    const canOpenInCanvas = isCanvasCompatible(event.category, event.mimeType);

    const handleOpenInCanvas = useCallback(async () => {
      const url = artifactUrl || artifactPreviewUrl;
      if (!url) return;

      const mime = event.mimeType.toLowerCase();
      if (
        mime.startsWith('image/') ||
        mime.startsWith('video/') ||
        mime.startsWith('audio/') ||
        isOfficeMimeType(mime) ||
        isOfficeExtension(event.filename)
      ) {
        useCanvasStore.getState().openTab({
          id: event.artifactId,
          title: event.filename,
          type: 'preview',
          content: url,
          mimeType: event.mimeType,
          artifactId: event.artifactId,
          artifactUrl: url,
        });
        const currentMode = useLayoutModeStore.getState().mode;
        if (currentMode !== 'canvas') {
          useLayoutModeStore.getState().setMode('canvas');
        }
        requestCanvasViewMode();
        return;
      }

      try {
        const response = await fetchArtifactResource(url);
        if (!response.ok) {
          throw new Error(`Failed to fetch artifact content: ${String(response.status)}`);
        }
        const responseType = response.headers.get('content-type')?.toLowerCase() || '';
        if (responseType.includes('application/pdf')) {
          useCanvasStore.getState().openTab({
            id: event.artifactId,
            title: event.filename,
            type: 'preview',
            content: url,
            mimeType: 'application/pdf',
            pdfVerified: true,
            artifactId: event.artifactId,
            artifactUrl: url,
          });
          const currentMode = useLayoutModeStore.getState().mode;
          if (currentMode !== 'canvas') {
            useLayoutModeStore.getState().setMode('canvas');
          }
          requestCanvasViewMode();
          return;
        }
        const content = await response.text();

        const isHtmlFile =
          event.filename.toLowerCase().endsWith('.html') || event.mimeType === 'text/html';

        if (isHtmlFile) {
          useCanvasStore.getState().openTab({
            id: event.artifactId,
            title: event.filename,
            type: 'preview',
            content,
            artifactId: event.artifactId,
            artifactUrl: url,
          });
        } else {
          const contentType = getCanvasContentTypeForArtifact(
            event.filename,
            responseType || mime,
            event.category
          );
          const ext = event.filename.split('.').pop()?.toLowerCase();

          useCanvasStore.getState().openTab({
            id: event.artifactId,
            title: event.filename,
            type: contentType,
            content,
            language: ext ? EXTENSION_LANG_MAP[ext] : undefined,
            artifactId: event.artifactId,
            artifactUrl: url,
          });
        }

        const currentMode = useLayoutModeStore.getState().mode;
        if (currentMode !== 'canvas') {
          useLayoutModeStore.getState().setMode('canvas');
        }
        requestCanvasViewMode();
      } catch {
        message.error(t('agent.artifact.openInCanvasFailed', 'Failed to open in Canvas'));
      }
    }, [
      artifactUrl,
      artifactPreviewUrl,
      event.artifactId,
      event.filename,
      event.category,
      event.mimeType,
      t,
    ]);

    const isImage = event.category === 'image';
    const url = artifactUrl || artifactPreviewUrl;
    const hasError = artifactStatus === 'error';

    return (
      <div className="flex flex-col gap-1">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-emerald-200 bg-emerald-50 dark:border-emerald-800/55 dark:bg-emerald-950/35">
            {(() => {
              const Icon = getCategoryIcon(event.category);
              return <Icon size={17} className="text-emerald-600 dark:text-emerald-400" />;
            })()}
          </div>
          <div className="flex-1 min-w-0">
            <div className="rounded-md bg-white p-4 shadow-[0_0_0_1px_rgba(15,23,42,0.08),0_8px_20px_-16px_rgba(15,23,42,0.28)] dark:bg-slate-950 dark:shadow-[0_0_0_1px_rgba(148,163,184,0.18)]">
              <div className="mb-3 flex min-w-0 items-center gap-2">
                {(() => {
                  const Icon = getCategoryIcon(event.category);
                  return <Icon size={17} className="text-emerald-600 dark:text-emerald-400" />;
                })()}
                <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                  {t('agent.artifact.fileGenerated', 'File generated')}
                </span>
                {event.sourceTool && (
                  <span className="max-w-[180px] truncate rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700 ring-1 ring-emerald-100 dark:bg-emerald-950/45 dark:text-emerald-300 dark:ring-emerald-800/60">
                    {event.sourceTool}
                  </span>
                )}
              </div>

              {isImage && url && !imageError && (
                <div className="relative mb-3 overflow-hidden rounded-md border border-slate-200 bg-slate-50 dark:border-slate-800 dark:bg-slate-900">
                  {!imageLoaded && (
                    <div className="absolute inset-0 flex min-h-[100px] items-center justify-center bg-slate-100 dark:bg-slate-800">
                      <LoaderCircle
                        size={24}
                        className="animate-spin motion-reduce:animate-none text-slate-400"
                      />
                    </div>
                  )}
                  <img
                    src={url}
                    alt={event.filename}
                    className={`max-h-75 max-w-full object-contain ${
                      imageLoaded ? 'opacity-100' : 'opacity-0'
                    } transition-opacity duration-300`}
                    onLoad={() => {
                      setImageLoaded(true);
                    }}
                    onError={() => {
                      setImageError(true);
                    }}
                  />
                </div>
              )}

              {hasError && (
                <div className="mb-3 flex items-center gap-2 rounded-md border border-red-200/50 bg-red-50 p-2 dark:border-red-700/50 dark:bg-red-900/30">
                  <AlertCircle size={16} className="text-red-500 dark:text-red-400" />
                  <span className="text-xs text-red-600 dark:text-red-400">{artifactError}</span>
                </div>
              )}

              <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm dark:border-slate-800 dark:bg-slate-900/70">
                <div className="flex min-w-[220px] flex-1 items-center gap-2">
                  <FileIcon size={16} className="shrink-0 text-emerald-600 dark:text-emerald-400" />
                  <span className="min-w-0 truncate font-medium text-slate-800 dark:text-slate-200">
                    {event.filename}
                  </span>
                </div>
                <span className="text-xs text-slate-500 dark:text-slate-400 whitespace-nowrap">
                  {formatSize(event.sizeBytes)}
                </span>
                {url && (
                  <a
                    href={url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 rounded text-xs font-medium text-emerald-700 transition-colors hover:text-emerald-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 dark:text-emerald-300 dark:hover:text-emerald-200"
                    download={event.filename}
                  >
                    <Download size={16} />
                    {t('agent.artifact.download', 'Download')}
                  </a>
                )}
                {canOpenInCanvas && url && (
                  <button
                    type="button"
                    onClick={() => {
                      void handleOpenInCanvas();
                    }}
                    className="inline-flex items-center gap-1 rounded text-xs font-medium text-primary transition-colors hover:text-primary/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1"
                  >
                    <PanelRight size={14} />
                    {t('agent.artifact.openInCanvas', 'Open in Canvas')}
                  </button>
                )}
                {!url && artifactStatus === 'uploading' && (
                  <span className="flex items-center gap-1 text-xs text-slate-400 dark:text-slate-500">
                    <Loader2 size={14} className="animate-spin motion-reduce:animate-none" />
                    {t('agent.artifact.uploading', 'Uploading…')}
                  </span>
                )}
              </div>

              <div className="mt-2.5 flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
                <span className="rounded border border-slate-200 bg-slate-50 px-2 py-0.5 dark:border-slate-800 dark:bg-slate-900">
                  {event.mimeType}
                </span>
                <span className="rounded border border-slate-200 bg-slate-50 px-2 py-0.5 capitalize dark:border-slate-800 dark:bg-slate-900">
                  {event.category}
                </span>
              </div>
            </div>
          </div>
        </div>
        <div className="pl-12">
          <TimeBadge timestamp={event.timestamp} />
        </div>
      </div>
    );
  },
  (prev, next) => {
    return (
      prev.event.artifactId === next.event.artifactId &&
      prev.event.url === next.event.url &&
      prev.event.error === next.event.error
    );
  }
);
