import { useEffect, useRef, useState } from 'react';
import { ChevronDownIcon, DownloadIcon, FileTextIcon } from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import { saveBlobWithDesktopDialog } from '../runtime/nativeFileBridge';
import {
  cloneConversationExportSnapshot,
  conversationExportFilename,
  conversationExportToHtml,
  conversationExportToMarkdown,
} from './conversationExportModel';
import type { ConversationExportSnapshot } from './conversationExportModel';

type Html2PdfOptions = {
  margin?: number | [number, number] | [number, number, number, number];
  html2canvas?: Record<string, unknown>;
  jsPDF?: {
    unit?: string;
    format?: string | [number, number];
    orientation?: 'portrait' | 'landscape';
  };
  pagebreak?: { mode?: string[] };
};

type ExportFormat = 'markdown' | 'pdf';

type ExportNotice = {
  kind: 'success' | 'error';
  message: string;
};

async function downloadConversationMarkdown(
  snapshot: ConversationExportSnapshot,
): Promise<DesktopFileSaveResult> {
  const markdown = conversationExportToMarkdown(snapshot);
  const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' });
  return saveBlobWithDesktopDialog({
    suggestedName: conversationExportFilename(snapshot, 'markdown'),
    mimeType: 'text/markdown;charset=utf-8',
    blob,
  });
}

async function downloadConversationPdf(
  snapshot: ConversationExportSnapshot,
): Promise<DesktopFileSaveResult> {
  const { default: html2pdf } = await import('html2pdf.js');
  const container = document.createElement('div');
  container.innerHTML = conversationExportToHtml(snapshot);
  container.style.position = 'absolute';
  container.style.left = '-9999px';
  document.body.appendChild(container);

  try {
    const options: Html2PdfOptions = {
      margin: [10, 10, 10, 10],
      html2canvas: { scale: 2, useCORS: true },
      jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' },
      pagebreak: { mode: ['avoid-all', 'css', 'legacy'] },
    };
    const pdf = await html2pdf().set(options).from(container).outputPdf('blob');
    if (!(pdf instanceof Blob)) throw new Error('conversation PDF output is invalid');
    return await saveBlobWithDesktopDialog({
      suggestedName: conversationExportFilename(snapshot, 'pdf'),
      mimeType: 'application/pdf',
      blob: pdf,
    });
  } finally {
    document.body.removeChild(container);
  }
}

export function ConversationExportMenu({
  snapshot,
}: {
  snapshot: ConversationExportSnapshot;
}) {
  const { t } = useI18n();
  const detailsRef = useRef<HTMLDetailsElement>(null);
  const summaryRef = useRef<HTMLElement>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [exportingFormat, setExportingFormat] = useState<ExportFormat | null>(null);
  const [notice, setNotice] = useState<ExportNotice | null>(null);

  const closeMenu = (restoreFocus = false) => {
    detailsRef.current?.removeAttribute('open');
    setMenuOpen(false);
    if (restoreFocus) {
      window.requestAnimationFrame(() => summaryRef.current?.focus());
    }
  };

  useEffect(() => {
    if (!menuOpen) return;
    const closeIfOutside = (event: PointerEvent) => {
      const target = event.target;
      if (target instanceof Node && !detailsRef.current?.contains(target)) closeMenu();
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      closeMenu(true);
    };
    document.addEventListener('pointerdown', closeIfOutside, true);
    document.addEventListener('keydown', closeOnEscape, true);
    return () => {
      document.removeEventListener('pointerdown', closeIfOutside, true);
      document.removeEventListener('keydown', closeOnEscape, true);
    };
  }, [menuOpen]);

  const exportConversation = async (format: ExportFormat) => {
    if (exportingFormat !== null) return;
    const invocationSnapshot = cloneConversationExportSnapshot(snapshot);
    closeMenu();
    setExportingFormat(format);
    setNotice(null);
    try {
      const result =
        format === 'markdown'
          ? await downloadConversationMarkdown(invocationSnapshot)
          : await downloadConversationPdf(invocationSnapshot);
      if (result.status === 'cancelled') return;
      setNotice({ kind: 'success', message: t('chat.exportReady') });
    } catch {
      setNotice({ kind: 'error', message: t('chat.exportFailed') });
    } finally {
      setExportingFormat(null);
      window.requestAnimationFrame(() => summaryRef.current?.focus());
    }
  };

  return (
    <div className="chat-conversation-export" aria-busy={exportingFormat !== null}>
      <details
        ref={detailsRef}
        onToggle={(event) => setMenuOpen(event.currentTarget.open)}
      >
        <summary ref={summaryRef} aria-label={t('chat.exportConversation')}>
          <DownloadIcon aria-hidden="true" />
          <span>{t('chat.exportConversation')}</span>
          <ChevronDownIcon aria-hidden="true" />
        </summary>
        <div className="chat-conversation-export-menu">
          <button
            type="button"
            disabled={exportingFormat !== null}
            onClick={() => void exportConversation('markdown')}
          >
            <FileTextIcon aria-hidden="true" />
            <span>
              <strong>{t('chat.exportMarkdown')}</strong>
              <small>.md</small>
            </span>
          </button>
          <button
            type="button"
            disabled={exportingFormat !== null}
            onClick={() => void exportConversation('pdf')}
          >
            <FileTextIcon aria-hidden="true" />
            <span>
              <strong>{t('chat.exportPdf')}</strong>
              <small>.pdf</small>
            </span>
          </button>
        </div>
      </details>
      {exportingFormat ? (
        <span className="chat-conversation-export-notice" role="status">
          {t('chat.exportingConversation')}
        </span>
      ) : notice ? (
        <span
          className={`chat-conversation-export-notice is-${notice.kind}`}
          role={notice.kind === 'error' ? 'alert' : 'status'}
        >
          {notice.message}
        </span>
      ) : null}
    </div>
  );
}
