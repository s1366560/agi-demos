import { memo, useCallback, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Loader2, PanelRight, Image as ImageIcon, Film, AudioLines, FileText, Code as CodeIcon, Table as TableIcon, FileArchive, Paperclip, AlertCircle, File as FileIcon, Download, LoaderCircle } from 'lucide-react';

import { type CanvasContentType, useCanvasStore } from '../../../stores/canvasStore';
import { useLayoutModeStore } from '../../../stores/layoutMode';
import { useSandboxStore } from '../../../stores/sandbox';
import { isOfficeMimeType, isOfficeExtension } from '../../../utils/filePreview';

import { TimeBadge } from './shared';

import type { ArtifactCreatedEvent } from '../../../types/agent';

interface ArtifactCreatedItemProps {
  event: ArtifactCreatedEvent & { error?: string | undefined };
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
        return;
      }

      try {
        const response = await fetch(url);
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
          const contentType: CanvasContentType =
            CATEGORY_CONTENT_TYPE_MAP[event.category] || 'code';
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
      } catch {
        // Silently fail -- user can still download
      }
    }, [
      artifactUrl,
      artifactPreviewUrl,
      event.artifactId,
      event.filename,
      event.category,
      event.mimeType,
    ]);

    const isImage = event.category === 'image';
    const url = artifactUrl || artifactPreviewUrl;
    const hasError = artifactStatus === 'error';

    return (
      <div className="flex flex-col gap-1">
        <div className="flex items-start gap-4">
          <div className="w-8 h-8 rounded-full bg-emerald-100 dark:bg-emerald-900/50 flex items-center justify-center shrink-0 mt-0.5 shadow-sm">
            {(() => { const Icon = getCategoryIcon(event.category); return <Icon size={18} className="text-emerald-600 dark:text-emerald-400" />; })()}
          </div>
          <div className="flex-1 min-w-0">
            <div className="bg-gradient-to-r from-emerald-50 to-teal-50 dark:from-emerald-900/30 dark:to-teal-900/30 rounded-xl p-4 border border-emerald-200/50 dark:border-emerald-700/50">
              <div className="flex items-center gap-2 mb-3">
                {(() => { const Icon = getCategoryIcon(event.category); return <Icon size={18} className="text-emerald-600 dark:text-emerald-400" />; })()}
                <span className="text-sm font-medium text-emerald-700 dark:text-emerald-300">
                  {t('agent.artifact.fileGenerated', 'File generated')}
                </span>
                {event.sourceTool && (
                  <span className="text-xs px-2 py-0.5 bg-emerald-100 dark:bg-emerald-800/50 text-emerald-600 dark:text-emerald-400 rounded">
                    {event.sourceTool}
                  </span>
                )}
              </div>

              {isImage && url && !imageError && (
                <div className="mb-3 relative">
                  {!imageLoaded && (
                    <div className="absolute inset-0 flex items-center justify-center bg-slate-100 dark:bg-slate-800 rounded-lg min-h-[100px]">
                      <LoaderCircle size={24} className="animate-spin motion-reduce:animate-none text-slate-400" />
                    </div>
                  )}
                  <img
                    src={url}
                    alt={event.filename}
                    className={`max-w-full max-h-75 rounded-lg shadow-sm object-contain ${
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
                <div className="mb-3 flex items-center gap-2 p-2 bg-red-50 dark:bg-red-900/30 rounded-lg border border-red-200/50 dark:border-red-700/50">
                  <AlertCircle size={16} className="text-red-500 dark:text-red-400" />
                  <span className="text-xs text-red-600 dark:text-red-400">{artifactError}</span>
                </div>
              )}

              <div className="flex items-center gap-3 text-sm">
                <div className="flex items-center gap-2 flex-1 min-w-0">
                  <FileIcon size={16} className="text-slate-500 dark:text-slate-400" />
                  <span className="truncate text-slate-700 dark:text-slate-300 font-medium">
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
                    className="flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400 hover:text-emerald-700 dark:hover:text-emerald-300 transition-colors"
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
                    className="flex items-center gap-1 text-xs text-primary hover:text-primary/80 transition-colors"
                  >
                    <PanelRight size={14} />
                    {t('agent.artifact.openInCanvas', 'Open in Canvas')}
                  </button>
                )}
                {!url && artifactStatus === 'uploading' && (
                  <span className="flex items-center gap-1 text-xs text-slate-400 dark:text-slate-500">
                    <Loader2 size={14} className="animate-spin motion-reduce:animate-none" />
                    {t('agent.artifact.uploading', 'Uploading...')}
                  </span>
                )}
              </div>

              <div className="mt-2 flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
                <span className="px-2 py-0.5 bg-white/50 dark:bg-slate-800/50 rounded">
                  {event.mimeType}
                </span>
                <span className="capitalize px-2 py-0.5 bg-white/50 dark:bg-slate-800/50 rounded">
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
