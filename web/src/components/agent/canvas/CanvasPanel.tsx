/**
 * CanvasPanel - Side-by-side artifact editing panel
 *
 * Displays a tabbed editor/viewer for code, markdown, and preview content.
 * Inspired by ChatGPT Canvas and Claude Artifacts.
 *
 * Features:
 * - Multiple tabs for open artifacts
 * - Code syntax highlighting (lazy-loaded)
 * - Markdown preview
 * - Copy/Download toolbar per tab
 * - Empty state with guidance
 */

import { memo, useState, useCallback, useRef, useMemo, useEffect } from 'react';

import { useTranslation } from 'react-i18next';
import ReactMarkdown from 'react-markdown';

import {
  X,
  Copy,
  Download,
  FileCode2,
  FileText,
  Eye,
  Table,
  Check,
  PanelLeftClose,
  Pencil,
  Sparkles,
  Undo2,
  Redo2,
  Plus,
  StickyNote,
  Save,
  Loader2,
  AppWindow,
  Pin,
  Music,
} from 'lucide-react';

import {
  useCanvasStore,
  useActiveCanvasTab,
  useCanvasTabs,
  useCanvasActions,
  type CanvasTab,
  type CanvasContentType,
} from '@/stores/canvasStore';
import { useLayoutModeStore } from '@/stores/layoutMode';

import { artifactService } from '@/services/artifactService';

import { ErrorBoundary } from '@/components/common/ErrorBoundary';
import { StandardMCPAppRenderer } from '@/components/mcp-app/StandardMCPAppRenderer';
import type { StandardMCPAppRendererHandle } from '@/components/mcp-app/StandardMCPAppRenderer';

import { useMarkdownPlugins, safeMarkdownComponents } from '../chat/markdownPlugins';
import { MARKDOWN_PROSE_CLASSES } from '../styles';

import { SelectionToolbar } from './SelectionToolbar';
import { isOfficeMimeType, isOfficeExtension } from '@/utils/filePreview';

const typeIcon = (type: CanvasContentType, size = 14) => {
  switch (type) {
    case 'code':
      return <FileCode2 size={size} />;
    case 'markdown':
      return <FileText size={size} />;
    case 'preview':
      return <Eye size={size} />;
    case 'data':
      return <Table size={size} />;
    case 'mcp-app':
      return <AppWindow size={size} />;
  }
};



const isSafePreviewUrl = (src: string): boolean => {
  if (!src) return false;
  if (src.startsWith('/')) return true;
  const lower = src.toLowerCase();
  if (lower.startsWith('data:application/pdf')) return true;
  if (lower.startsWith('data:')) return false;
  try {
    const url = new URL(src, window.location.origin);
    return url.protocol === 'http:' || url.protocol === 'https:' || url.protocol === 'blob:';
  } catch {
    return false;
  }
};

// Tab bar
const CanvasTabBar = memo<{ onBeforeCloseTab?: ((tabId: string) => void) | undefined }>(
  ({ onBeforeCloseTab }) => {
    const tabs = useCanvasStore((s) => s.tabs);
    const activeTabId = useCanvasStore((s) => s.activeTabId);
    const { setActiveTab, closeTab, openTab, togglePin } = useCanvasActions();
    const { t } = useTranslation();
    const setMode = useLayoutModeStore((s) => s.setMode);

    const handleNewTab = useCallback(() => {
      const id = `new-${String(Date.now())}`;
      openTab({ id, title: 'untitled.py', type: 'code', content: '', language: undefined });
    }, [openTab]);

    const handleClose = useCallback(
      (tabId: string) => {
        onBeforeCloseTab?.(tabId);
        closeTab(tabId);
      },
      [onBeforeCloseTab, closeTab]
    );

    if (tabs.length === 0) return null;

    return (
      <div className="flex items-center border-b border-slate-200 dark:border-slate-700 bg-slate-50/80 dark:bg-slate-900/50">
        <div className="flex-1 flex items-center overflow-x-auto scrollbar-none">
          {tabs.map((tab) => (
            <div
              key={tab.id}
              role="tab"
              tabIndex={0}
              onClick={() => {
                setActiveTab(tab.id);
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') setActiveTab(tab.id);
              }}
              className={`
              group flex items-center gap-1.5 px-3 py-2 text-xs font-medium
              border-r border-slate-200/60 dark:border-slate-700/60
              transition-colors whitespace-nowrap max-w-[180px] cursor-pointer
              ${
                tab.id === activeTabId
                  ? 'bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-200'
                  : 'text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800/50'
              }
            `}
            >
              <span className={tab.id === activeTabId ? 'text-primary' : 'text-slate-400'}>
                {typeIcon(tab.type)}
              </span>
              <span className="truncate">{tab.title}</span>
              {tab.dirty && (
                <span className="w-1.5 h-1.5 rounded-full bg-amber-400 flex-shrink-0" />
              )}
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  togglePin(tab.id);
                }}
                className={`ml-0.5 p-0.5 rounded transition-all ${
                  tab.pinned
                    ? 'text-primary opacity-100'
                    : 'opacity-0 group-hover:opacity-100 hover:bg-slate-200 dark:hover:bg-slate-700'
                }`}
              >
                <Pin size={12} fill={tab.pinned ? 'currentColor' : 'none'} />
              </button>
              {!tab.pinned && (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleClose(tab.id);
                  }}
                  className="ml-0.5 p-0.5 rounded opacity-0 group-hover:opacity-100 hover:bg-slate-200 dark:hover:bg-slate-700 transition-all"
                >
                  <X size={12} />
                </button>
              )}
            </div>
          ))}
          <button
            type="button"
            onClick={handleNewTab}
            className="flex-shrink-0 p-2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            title={t('agent.canvas.newTab', 'New tab')}
          >
            <Plus size={14} />
          </button>
        </div>
        <button
          type="button"
          onClick={() => {
            setMode('chat');
          }}
          className="flex-shrink-0 p-2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
          title={t('agent.canvas.backToChat', 'Back to chat')}
        >
          <PanelLeftClose size={16} />
        </button>
      </div>
    );
  }
);
CanvasTabBar.displayName = 'CanvasTabBar';

/**
 * IsolatedPreviewFrame - Renders HTML content in a strictly isolated iframe
 *
 * Uses Blob URL with unique origin for complete style isolation, preventing
 * any CSS leakage from or to the parent page.
 */
const IsolatedPreviewFrame = memo<{
  content: string;
  title: string;
  srcUrl?: string | undefined;
  pdfVerified?: boolean | undefined;
}>(({ content, title, srcUrl, pdfVerified }) => {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const previewSrc = srcUrl || content.trim();
  const lowerPreviewSrc = previewSrc.toLowerCase();
  const canUsePdfSrc = isSafePreviewUrl(previewSrc);
  const shouldSandboxPdf = (() => {
    try {
      const resolved = new URL(previewSrc, window.location.origin);
      const isHttp = resolved.protocol === 'http:' || resolved.protocol === 'https:';
      const isCrossOrigin = isHttp && resolved.origin !== window.location.origin;
      return !isCrossOrigin;
    } catch {
      return true;
    }
  })();
  const wantsPdfPreview =
    pdfVerified === true || lowerPreviewSrc.startsWith('data:application/pdf');
  const isPdfPreview = wantsPdfPreview && canUsePdfSrc;

  useEffect(() => {
    if (isPdfPreview) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setBlobUrl(null);
      return;
    }

    const htmlContent = content.trim();

    // Wrap in full HTML document with isolation
    const wrappedContent =
      htmlContent.startsWith('<!DOCTYPE') || htmlContent.startsWith('<html')
        ? htmlContent
        : `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    html, body { margin: 0; padding: 0; width: 100%; height: 100%; }
  </style>
</head>
<body>
${htmlContent}
</body>
</html>`;

    // Create blob URL for complete isolation (unique origin)
    const blob = new Blob([wrappedContent], { type: 'text/html;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    setBlobUrl(url);

    return () => {
      URL.revokeObjectURL(url);
    };
  }, [content, isPdfPreview]);

  if (wantsPdfPreview && !canUsePdfSrc) {
    return (
      <div className="w-full h-full flex items-center justify-center bg-white rounded-b-lg">
        <div className="text-slate-400">Invalid PDF preview URL</div>
      </div>
    );
  }

  if (isPdfPreview) {
    return (
      <iframe
        ref={iframeRef}
        src={previewSrc}
        {...(shouldSandboxPdf ? { sandbox: 'allow-same-origin allow-downloads' } : {})}
        referrerPolicy="no-referrer"
        className="w-full h-full border-0 bg-white rounded-b-lg"
        title={title}
      />
    );
  }

  if (!blobUrl) {
    return (
      <div className="w-full h-full flex items-center justify-center bg-white rounded-b-lg">
        <div className="text-slate-400">Loading...</div>
      </div>
    );
  }

  return (
    <iframe
      ref={iframeRef}
      src={blobUrl}
      sandbox="allow-scripts allow-same-origin"
      className="w-full h-full border-0 bg-white rounded-b-lg"
      title={title}
    />
  );
});
IsolatedPreviewFrame.displayName = 'IsolatedPreviewFrame';

/** Preview media files (image, video, audio, SVG) directly in canvas */
const CanvasMediaPreview = memo<{
  src: string;
  mimeType: string;
  title: string;
}>(({ src, mimeType, title }) => {
  if (mimeType.startsWith('image/')) {
    return (
      <div className="h-full w-full flex items-center justify-center bg-slate-50 dark:bg-slate-900 overflow-auto p-4">
        <img
          src={src}
          alt={title}
          style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }}
        />
      </div>
    );
  }
  if (mimeType.startsWith('video/')) {
    return (
      <div className="h-full w-full flex items-center justify-center bg-black">
        <video
          src={src}
          controls
          playsInline
          preload="metadata"
          style={{ maxWidth: '100%', maxHeight: '100%' }}
        >
          <track kind="captions" />
          <source src={src} type={mimeType} />
        </video>
      </div>
    );
  }
  if (mimeType.startsWith('audio/')) {
    return (
      <div className="h-full w-full flex items-center justify-center bg-slate-50 dark:bg-slate-900">
        <div className="flex flex-col items-center gap-4 p-8">
          <Music size={48} className="text-slate-300 dark:text-slate-600" />
          <div className="text-sm text-slate-500 dark:text-slate-400 mb-2">{title}</div>
          <audio src={src} controls preload="metadata" style={{ width: 320 }}>
            <track kind="captions" />
            Your browser does not support the audio element.
          </audio>
        </div>
      </div>
    );
  }
  // SVG - render in iframe for safety
  return (
    <iframe
      src={src}
      title={title}
      sandbox="allow-same-origin"
      className="w-full h-full border-0 bg-white rounded-b-lg"
    />
  );
});
CanvasMediaPreview.displayName = 'CanvasMediaPreview';

/** Detect Office sub-type from MIME or filename extension */
const getOfficeFileType = (mime: string, filename: string): 'docx' | 'xlsx' | 'pptx' | 'legacy' => {
  const m = mime.toLowerCase();
  const ext = filename.split('.').pop()?.toLowerCase() || '';
  if (
    m === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' ||
    ext === 'docx'
  )
    return 'docx';
  if (
    m === 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' ||
    ext === 'xlsx'
  )
    return 'xlsx';
  if (
    m === 'application/vnd.openxmlformats-officedocument.presentationml.presentation' ||
    ext === 'pptx'
  )
    return 'pptx';
  // Legacy formats (.doc, .xls, .ppt) and unrecognized
  return 'legacy';
};

/** Download fallback UI for unsupported Office formats */
const OfficeDownloadFallback = memo<{ src: string; title: string; message: string }>(
  ({ src, title, message }) => (
    <div className="h-full w-full flex items-center justify-center bg-slate-50 dark:bg-slate-900">
      <div className="flex flex-col items-center gap-4 p-8 text-center">
        <FileText size={48} className="text-slate-300 dark:text-slate-600" />
        <div className="text-sm text-slate-500 dark:text-slate-400">{title}</div>
        <div className="text-xs text-slate-400 dark:text-slate-500 max-w-xs">{message}</div>
        <a
          href={src}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 transition-colors"
        >
          <Download size={14} />
          Download File
        </a>
      </div>
    </div>
  )
);
OfficeDownloadFallback.displayName = 'OfficeDownloadFallback';

/** Render DOCX files client-side using docx-preview */
const DocxPreview = memo<{ src: string; title: string }>(({ src, title }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const render = async () => {
      try {
        setLoading(true);
        setError(null);
        const resp = await fetch(src);
        if (!resp.ok) throw new Error(`Failed to fetch: ${resp.status}`);
        const buf = await resp.arrayBuffer();
        if (cancelled || !containerRef.current) return;
        const { renderAsync } = await import('docx-preview');
        if (cancelled || !containerRef.current) return;
        containerRef.current.innerHTML = '';
        await renderAsync(buf, containerRef.current, undefined, {
          className: 'docx-preview',
          inWrapper: true,
          ignoreWidth: false,
          ignoreHeight: true,
          breakPages: true,
          renderHeaders: true,
          renderFooters: true,
          renderFootnotes: true,
          renderEndnotes: true,
        });
        if (!cancelled) setLoading(false);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : 'Failed to render document');
          setLoading(false);
        }
      }
    };
    void render();
    return () => {
      cancelled = true;
    };
  }, [src]);

  if (error) {
    return <OfficeDownloadFallback src={src} title={title} message={error} />;
  }

  return (
    <div className="h-full w-full overflow-auto bg-white dark:bg-slate-100 rounded-b-lg relative">
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center bg-white/80 dark:bg-slate-100/80 z-10">
          <Loader2 size={24} className="animate-spin text-blue-500" />
        </div>
      )}
      <div ref={containerRef} className="docx-container p-2" />
    </div>
  );
});
DocxPreview.displayName = 'DocxPreview';

/** Render XLSX files client-side using SheetJS */
const XlsxPreview = memo<{ src: string; title: string }>(({ src, title }) => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sheets, setSheets] = useState<{ name: string; html: string }[]>([]);
  const [activeSheet, setActiveSheet] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const render = async () => {
      try {
        setLoading(true);
        setError(null);
        const resp = await fetch(src);
        if (!resp.ok) throw new Error(`Failed to fetch: ${resp.status}`);
        const buf = await resp.arrayBuffer();
        if (cancelled) return;
        const XLSX = await import('xlsx');
        if (cancelled) return;
        const wb = XLSX.read(buf, { type: 'array' });
        const result = wb.SheetNames.map((name) => {
          const ws = wb.Sheets[name];
          if (!ws) return { name, html: '<p>Empty sheet</p>' };
          const html = XLSX.utils.sheet_to_html(ws, { editable: false });
          return { name, html };
        });
        if (!cancelled) {
          setSheets(result);
          setActiveSheet(0);
          setLoading(false);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : 'Failed to render spreadsheet');
          setLoading(false);
        }
      }
    };
    void render();
    return () => {
      cancelled = true;
    };
  }, [src]);

  if (error) {
    return <OfficeDownloadFallback src={src} title={title} message={error} />;
  }

  return (
    <div className="h-full w-full flex flex-col bg-white dark:bg-slate-900 rounded-b-lg relative">
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center bg-white/80 dark:bg-slate-900/80 z-10">
          <Loader2 size={24} className="animate-spin text-blue-500" />
        </div>
      )}
      {sheets.length > 1 && (
        <div className="flex gap-1 px-2 pt-2 border-b border-slate-200 dark:border-slate-700 overflow-x-auto shrink-0">
          {sheets.map((s, i) => (
            <button
              key={s.name}
              type="button"
              onClick={() => setActiveSheet(i)}
              className={`px-3 py-1.5 text-xs font-medium rounded-t whitespace-nowrap transition-colors ${
                i === activeSheet
                  ? 'bg-white dark:bg-slate-800 text-blue-600 dark:text-blue-400 border border-b-0 border-slate-200 dark:border-slate-700'
                  : 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800'
              }`}
            >
              {s.name}
            </button>
          ))}
        </div>
      )}
      {sheets[activeSheet] && (
        <div
          className="flex-1 overflow-auto p-2 xlsx-preview"
          dangerouslySetInnerHTML={{ __html: sheets[activeSheet].html }}
        />
      )}
    </div>
  );
});
XlsxPreview.displayName = 'XlsxPreview';

/** Preview Office files with client-side rendering (DOCX, XLSX) or download fallback */
const CanvasOfficePreview = memo<{
  src: string;
  title: string;
  mimeType?: string;
}>(({ src, title, mimeType }) => {
  const fileType = getOfficeFileType(mimeType || '', title);

  switch (fileType) {
    case 'docx':
      return <DocxPreview src={src} title={title} />;
    case 'xlsx':
      return <XlsxPreview src={src} title={title} />;
    case 'pptx':
      return (
        <OfficeDownloadFallback
          src={src}
          title={title}
          message="PowerPoint preview is not yet supported. Server-side conversion will be added in a future update."
        />
      );
    case 'legacy':
      return (
        <OfficeDownloadFallback
          src={src}
          title={title}
          message="Legacy Office format (.doc/.xls/.ppt) preview is not supported. Please convert to .docx/.xlsx/.pptx for preview."
        />
      );
  }
});
CanvasOfficePreview.displayName = 'CanvasOfficePreview';

// Content area for a single non-mcp-app tab
// MCP app tabs are rendered separately in CanvasPanel for multi-instance isolation.
const CanvasContent = memo<{
  tab: CanvasTab;
  editMode: boolean;
  onContentChange: (content: string) => void;
}>(({ tab, editMode, onContentChange }) => {
  const { remarkPlugins, rehypePlugins } = useMarkdownPlugins(
    tab.type === 'markdown' ? tab.content : undefined
  );
  if (editMode && (tab.type === 'code' || tab.type === 'markdown' || tab.type === 'data')) {
    const bgClass =
      tab.type === 'code'
        ? 'bg-slate-900 text-slate-200'
        : 'bg-white dark:bg-slate-900 text-slate-800 dark:text-slate-200';
    return (
      <div className={`h-full overflow-auto ${tab.type === 'code' ? 'bg-slate-900' : ''}`}>
        <textarea
          value={tab.content}
          onChange={(e) => {
            onContentChange(e.target.value);
          }}
          className={`w-full h-full font-mono text-sm p-4 resize-none focus:outline-none ${bgClass}`}
          spellCheck={false}
        />
      </div>
    );
  }

  switch (tab.type) {
    case 'code':
      return (
        <div className="h-full overflow-auto bg-slate-900 rounded-b-lg">
          <pre className="p-4 text-sm font-mono text-slate-200 whitespace-pre-wrap break-words leading-relaxed">
            <code>{tab.content}</code>
          </pre>
        </div>
      );
    case 'markdown':
      return (
        <div
          className={`h-full overflow-auto p-6 bg-white dark:bg-slate-900 rounded-b-lg ${MARKDOWN_PROSE_CLASSES}`}
        >
          <ReactMarkdown
            remarkPlugins={remarkPlugins}
            rehypePlugins={rehypePlugins}
            components={safeMarkdownComponents}
          >
            {tab.content}
          </ReactMarkdown>
        </div>
      );
    case 'preview': {
      const mime = tab.mimeType?.toLowerCase() || '';
      const previewSrc = tab.artifactUrl || tab.content;

      // Media files: image, video, audio, SVG
      if (mime.startsWith('image/') || mime.startsWith('video/') || mime.startsWith('audio/')) {
        return <CanvasMediaPreview src={previewSrc} mimeType={mime} title={tab.title} />;
      }

      // Office files: Word, Excel, PowerPoint
      if (isOfficeMimeType(mime) || isOfficeExtension(tab.title)) {
        return <CanvasOfficePreview src={previewSrc} title={tab.title} mimeType={mime} />;
      }

      // PDF and HTML: existing behavior
      return (
        <IsolatedPreviewFrame
          content={tab.content}
          title={tab.title}
          srcUrl={tab.artifactUrl}
          pdfVerified={tab.pdfVerified}
        />
      );
    }
    case 'data':
      return (
        <div className="h-full overflow-auto p-4 bg-white dark:bg-slate-900 rounded-b-lg">
          <pre className="text-sm font-mono text-slate-700 dark:text-slate-300 whitespace-pre-wrap">
            {tab.content}
          </pre>
        </div>
      );
    case 'mcp-app':
      // MCP app tabs are rendered by CanvasPanel directly (multi-instance)
      return null;
  }
});
CanvasContent.displayName = 'CanvasContent';

// Toolbar for copy/download actions
const CanvasToolbar = memo<{
  tab: CanvasTab;
  editMode: boolean;
  onToggleEdit: () => void;
}>(({ tab, editMode, onToggleEdit }) => {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const [saving, setSaving] = useState(false);
  const { undo, redo, canUndo, canRedo } = useCanvasActions();

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(tab.content);
      setCopied(true);
      setTimeout(() => {
        setCopied(false);
      }, 2000);
    } catch {
      // fallback
      const textarea = document.createElement('textarea');
      textarea.value = tab.content;
      document.body.appendChild(textarea);
      textarea.select();
      (document as unknown as { execCommand: (cmd: string) => boolean }).execCommand('copy');
      document.body.removeChild(textarea);
      setCopied(true);
      setTimeout(() => {
        setCopied(false);
      }, 2000);
    }
  }, [tab.content]);

  const handleDownload = useCallback(() => {
    if (tab.artifactUrl) {
      const a = document.createElement('a');
      a.href = tab.artifactUrl;
      a.download = tab.title;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      a.click();
      return;
    }
    const ext =
      tab.type === 'code' ? tab.language || 'txt' : tab.type === 'markdown' ? 'md' : 'txt';
    const blob = new Blob([tab.content], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${tab.title}.${ext}`;
    a.click();
    URL.revokeObjectURL(url);
  }, [tab]);

  const handleSave = useCallback(async () => {
    if (!tab.artifactId || saving) return;
    setSaving(true);
    try {
      const result = await artifactService.updateContent(tab.artifactId, tab.content);
      // Update artifact URL in canvas store and clear dirty flag
      useCanvasStore.getState().openTab({
        ...tab,
        artifactUrl: result.url || tab.artifactUrl,
      });
    } catch {
      // silent fail — user can retry
    } finally {
      setSaving(false);
    }
  }, [tab, saving]);

  const canEdit = tab.type !== 'preview';
  const canSave = tab.artifactId && tab.dirty;

  return (
    <div className="flex items-center gap-1 px-3 py-1.5 border-b border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800">
      <div className="flex-1 flex items-center gap-2">
        <span className="text-primary">{typeIcon(tab.type)}</span>
        <span className="text-xs font-medium text-slate-600 dark:text-slate-300">{tab.title}</span>
        {tab.language && (
          <span className="text-[10px] px-1.5 py-0.5 bg-slate-100 dark:bg-slate-700 text-slate-500 dark:text-slate-400 rounded">
            {tab.language}
          </span>
        )}
      </div>
      {canSave && (
        <button
          type="button"
          onClick={() => {
            void handleSave();
          }}
          disabled={saving}
          className="p-1.5 rounded-md text-primary hover:bg-primary/10 transition-colors disabled:opacity-50"
          title={t('agent.canvas.save', 'Save (Ctrl+S)')}
        >
          {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
        </button>
      )}
      <button
        type="button"
        onClick={() => {
          undo(tab.id);
        }}
        disabled={!canUndo(tab.id)}
        className="p-1.5 rounded-md text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
        title={t('agent.canvas.undo', 'Undo (Ctrl+Z)')}
      >
        <Undo2 size={14} />
      </button>
      <button
        type="button"
        onClick={() => {
          redo(tab.id);
        }}
        disabled={!canRedo(tab.id)}
        className="p-1.5 rounded-md text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
        title={t('agent.canvas.redo', 'Redo (Ctrl+Shift+Z)')}
      >
        <Redo2 size={14} />
      </button>
      {canEdit && (
        <button
          type="button"
          onClick={onToggleEdit}
          className={`p-1.5 rounded-md transition-colors ${
            editMode
              ? 'bg-primary/10 text-primary'
              : 'hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-400'
          }`}
          title={
            editMode
              ? t('agent.canvas.viewMode', 'View mode')
              : t('agent.canvas.editMode', 'Edit mode')
          }
        >
          {editMode ? <Eye size={14} /> : <Pencil size={14} />}
        </button>
      )}
      <button
        type="button"
        onClick={() => {
          void handleCopy();
        }}
        className="p-1.5 rounded-md text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
        title={t('agent.canvas.copy', 'Copy')}
      >
        {copied ? <Check size={14} className="text-emerald-500" /> : <Copy size={14} />}
      </button>
      <button
        type="button"
        onClick={handleDownload}
        className="p-1.5 rounded-md text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
        title={t('agent.canvas.download', 'Download')}
      >
        <Download size={14} />
      </button>
    </div>
  );
});
CanvasToolbar.displayName = 'CanvasToolbar';

// Quick actions toolbar based on content type
const QuickActions = memo<{
  type: CanvasContentType;
  content: string;
  onSendPrompt?: ((prompt: string) => void) | undefined;
}>(({ type, content, onSendPrompt }) => {
  const { t } = useTranslation();

  const actions = useMemo(() => {
    const common = [
      {
        label: t('agent.canvas.actions.summarize', 'Summarize'),
        prompt: `Summarize this:\n\n${content.slice(0, 500)}`,
      },
    ];

    if (type === 'code') {
      return [
        {
          label: t('agent.canvas.actions.explain', 'Explain'),
          prompt: `Explain this code:\n\n${content.slice(0, 500)}`,
        },
        {
          label: t('agent.canvas.actions.optimize', 'Optimize'),
          prompt: `Optimize this code:\n\n${content.slice(0, 500)}`,
        },
        {
          label: t('agent.canvas.actions.addTests', 'Add Tests'),
          prompt: `Write tests for this code:\n\n${content.slice(0, 500)}`,
        },
        {
          label: t('agent.canvas.actions.addComments', 'Add Comments'),
          prompt: `Add comments to this code:\n\n${content.slice(0, 500)}`,
        },
      ];
    }
    if (type === 'markdown') {
      return [
        {
          label: t('agent.canvas.actions.improve', 'Improve'),
          prompt: `Improve this text:\n\n${content.slice(0, 500)}`,
        },
        {
          label: t('agent.canvas.actions.shorten', 'Shorten'),
          prompt: `Make this more concise:\n\n${content.slice(0, 500)}`,
        },
        {
          label: t('agent.canvas.actions.translate', 'Translate'),
          prompt: `Translate this to the other language (if Chinese, translate to English; if English, translate to Chinese):\n\n${content.slice(0, 500)}`,
        },
        ...common,
      ];
    }
    return common;
  }, [type, content, t]);

  if (!onSendPrompt || !content) return null;

  return (
    <div className="flex items-center gap-1 px-3 py-1.5 border-b border-slate-200 dark:border-slate-700 overflow-x-auto scrollbar-none">
      {actions.map((action) => (
        <button
          key={action.label}
          type="button"
          onClick={() => {
            onSendPrompt(action.prompt);
          }}
          className="px-2 py-1 text-xs rounded-md bg-slate-50 dark:bg-slate-700/50 text-slate-600 dark:text-slate-300 hover:bg-primary/10 hover:text-primary transition-colors whitespace-nowrap"
        >
          {action.label}
        </button>
      ))}
    </div>
  );
});
QuickActions.displayName = 'QuickActions';

// Empty state when no tabs
const CanvasEmptyState = memo(() => {
  const { t } = useTranslation();
  const { openTab } = useCanvasActions();

  const handleNew = useCallback(
    (type: CanvasContentType, title: string) => {
      const id = `new-${String(Date.now())}`;
      openTab({ id, title, type, content: '', language: undefined });
    },
    [openTab]
  );

  return (
    <div className="h-full flex flex-col items-center justify-center p-8 text-center">
      <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-violet-100 to-purple-100 dark:from-violet-900/30 dark:to-purple-900/20 flex items-center justify-center mb-4">
        <FileCode2 size={28} className="text-violet-500 dark:text-violet-400" />
      </div>
      <h3 className="text-lg font-semibold text-slate-800 dark:text-slate-200 mb-2">
        {t('agent.canvas.emptyTitle', 'Canvas')}
      </h3>
      <p className="text-sm text-slate-500 dark:text-slate-400 max-w-xs leading-relaxed mb-6">
        {t(
          'agent.canvas.emptyDescription',
          'Code, documents, and previews from the agent will appear here. Ask the agent to generate or edit content.'
        )}
      </p>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => {
            handleNew('code', 'untitled.py');
          }}
          className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
        >
          <FileCode2 size={14} />
          {t('agent.canvas.newCode', 'New Code')}
        </button>
        <button
          type="button"
          onClick={() => {
            handleNew('markdown', 'untitled.md');
          }}
          className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
        >
          <FileText size={14} />
          {t('agent.canvas.newMarkdown', 'New Markdown')}
        </button>
        <button
          type="button"
          onClick={() => {
            handleNew('data', 'notes.txt');
          }}
          className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
        >
          <StickyNote size={14} />
          {t('agent.canvas.newNote', 'New Note')}
        </button>
      </div>
    </div>
  );
});
CanvasEmptyState.displayName = 'CanvasEmptyState';

// Main CanvasPanel component
export const CanvasPanel = memo<{
  onSendPrompt?: ((prompt: string) => void) | undefined;
  onUpdateModelContext?: ((context: Record<string, unknown>) => void) | undefined;
}>(({ onSendPrompt, onUpdateModelContext }) => {
  const activeTab = useActiveCanvasTab();
  const { updateContent } = useCanvasActions();
  const contentRef = useRef<HTMLDivElement>(null);
  const mcpAppRefsMap = useRef<Map<string, StandardMCPAppRendererHandle>>(new Map());
  const [editMode, setEditMode] = useState(false);
  const { t } = useTranslation();
  const prevActiveTabRef = useRef<{ id: string; type: CanvasContentType } | null>(null);
  const activeTabId = activeTab?.id ?? null;
  const activeTabType = activeTab?.type ?? null;
  const allTabs = useCanvasTabs();
  const mcpAppTabs = useMemo(() => allTabs.filter((t) => t.type === 'mcp-app'), [allTabs]);

  // Teardown MCP App when switching away from an mcp-app tab (no longer needed
  // for error isolation since each tab has its own renderer, but still useful to
  // release resources when the user navigates away from a tab).
  useEffect(() => {
    const prev = prevActiveTabRef.current;
    if (prev && prev.type === 'mcp-app' && prev.id !== activeTabId) {
      // Do NOT teardown on tab switch -- multi-instance approach keeps all alive.
      // Teardown only happens on close or unmount.
    }
    prevActiveTabRef.current =
      activeTabId && activeTabType ? { id: activeTabId, type: activeTabType } : null;
  }, [activeTabId, activeTabType]);

  // Teardown ALL MCP App instances on page unload / navigate away
  useEffect(() => {
    const handleBeforeUnload = () => {
      mcpAppRefsMap.current.forEach((handle) => {
        handle.teardown();
      });
    };
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload);
      // Also teardown on component unmount (route change)
      handleBeforeUnload();
    };
  }, []);

  // Teardown specific MCP App on tab close
  const handleBeforeCloseTab = useCallback((tabId: string) => {
    const tabs = useCanvasStore.getState().tabs;
    const tab = tabs.find((t) => t.id === tabId);
    if (tab?.type === 'mcp-app') {
      mcpAppRefsMap.current.get(tabId)?.teardown();
      mcpAppRefsMap.current.delete(tabId);
    }
  }, []);

  const handleSelectionAction = useCallback(
    (prompt: string) => {
      onSendPrompt?.(prompt);
    },
    [onSendPrompt]
  );

  const handleContentChange = useCallback(
    (content: string) => {
      if (activeTab) {
        updateContent(activeTab.id, content);
      }
    },
    [activeTab, updateContent]
  );

  const handleToggleEdit = useCallback(() => {
    setEditMode((prev) => !prev);
  }, []);

  const handleAskRefine = useCallback(() => {
    if (onSendPrompt && activeTab) {
      onSendPrompt(
        `I've edited the content below. Please review and improve it:\n\n${activeTab.content}`
      );
      setEditMode(false);
    }
  }, [onSendPrompt, activeTab]);

  return (
    <div className="h-full flex flex-col bg-gradient-to-br from-slate-50 to-slate-100/50 dark:from-slate-900 dark:to-slate-950/50 overflow-hidden">
      <CanvasTabBar onBeforeCloseTab={handleBeforeCloseTab} />
      {activeTab ? (
        <>
          <CanvasToolbar tab={activeTab} editMode={editMode} onToggleEdit={handleToggleEdit} />
          <QuickActions
            type={activeTab.type}
            content={activeTab.content}
            onSendPrompt={onSendPrompt}
          />
          <div
            ref={contentRef}
            className="flex-1 min-h-0 overflow-hidden relative bg-white dark:bg-slate-900"
          >
            {/* Multi-instance MCP app rendering: each mcp-app tab gets its own isolated renderer */}
            {mcpAppTabs.map((tab) => (
              <div
                key={tab.id}
                style={{
                  display: tab.id === activeTabId ? 'flex' : 'none',
                  flexDirection: 'column',
                  height: '100%',
                  width: '100%',
                }}
              >
                <ErrorBoundary
                  key={`eb-${tab.id}`}
                  context={`MCP App: ${tab.title}`}
                  showHomeButton={false}
                >
                  <StandardMCPAppRenderer
                    ref={(handle) => {
                      if (handle) {
                        mcpAppRefsMap.current.set(tab.id, handle);
                      } else {
                        mcpAppRefsMap.current.delete(tab.id);
                      }
                    }}
                    toolName={tab.mcpToolName || tab.title}
                    resourceUri={tab.mcpResourceUri}
                    html={tab.mcpAppHtml}
                    projectId={tab.mcpProjectId}
                    serverName={tab.mcpServerName}
                    appId={tab.mcpAppId}
                    onMessage={
                      onSendPrompt
                        ? (msg) => {
                            if (msg.content.text) {
                              onSendPrompt(msg.content.text);
                            }
                          }
                        : undefined
                    }
                    onUpdateModelContext={onUpdateModelContext}
                    height="100%"
                  />
                </ErrorBoundary>
              </div>
            ))}
            {/* Non-mcp-app active tab content */}
            {activeTab.type !== 'mcp-app' && (
              <CanvasContent
                tab={activeTab}
                editMode={editMode}
                onContentChange={handleContentChange}
              />
            )}
            {!editMode && (
              <SelectionToolbar containerRef={contentRef} onAction={handleSelectionAction} />
            )}
            {editMode && onSendPrompt && (
              <button
                type="button"
                onClick={handleAskRefine}
                className="absolute bottom-4 right-4 px-3 py-1.5 bg-primary text-white text-xs rounded-lg shadow-lg hover:bg-primary-600 flex items-center gap-1.5"
              >
                <Sparkles size={12} />
                {t('agent.canvas.askRefine', 'Ask Agent to Refine')}
              </button>
            )}
          </div>
        </>
      ) : (
        <CanvasEmptyState />
      )}
    </div>
  );
});
CanvasPanel.displayName = 'CanvasPanel';
