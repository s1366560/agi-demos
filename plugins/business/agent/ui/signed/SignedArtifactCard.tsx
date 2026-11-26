import { useEffect, useRef, useState } from 'react';
import {
  Archive,
  Download,
  File,
  FileCode,
  FileOutput,
  FileText,
  Film,
  ImageIcon,
  Loader2,
  Music,
  Paperclip,
  RefreshCw,
  Table,
  XCircle,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { formatFileSize } from '../../../../../sdk/memstack-plugin-sdk/ui/formatFileSize';
import type { RichPageContext } from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';
import { WIDE_MESSAGE_MAX_WIDTH_CLASSES } from '../web/chat/styles';
import { invoke } from './reviewAuthority';
import type { InteractionEvent } from './useInteractions';

/** A file the agent produced, as the page can show it: its address as the storage signed it anew. */
interface ArtifactFile {
  id: string;
  status?: string;
  url?: string;
  preview?: string;
}

function categoryIcon(category: string) {
  switch (category) {
    case 'image':
      return ImageIcon;
    case 'video':
      return Film;
    case 'audio':
      return Music;
    case 'document':
      return FileText;
    case 'code':
      return FileCode;
    case 'data':
      return Table;
    case 'archive':
      return Archive;
    default:
      return Paperclip;
  }
}

/**
 * The card of a file the agent produced, as the transcript of the original workbench
 * shows it. The page reaches no storage of its own: the package signs the address of
 * the file anew, and carries a small picture into the page. A link of the card to the
 * file is opened by the workbench.
 */
export function SignedArtifactCard({
  event,
  conversation,
  scope,
}: {
  event: InteractionEvent;
  conversation: string;
  scope: RichPageContext;
}) {
  const { t } = useTranslation();
  const [file, setFile] = useState<ArtifactFile>();
  const [failure, setFailure] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [near, setNear] = useState(false);
  const card = useRef<HTMLDivElement>(null);
  const artifactId = event.artifactId;
  // The file is read when its card comes into view, and not for every card of a long history.
  useEffect(() => {
    const element = card.current;
    if (!element || near || typeof IntersectionObserver === 'undefined') return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) setNear(true);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [near]);
  const readable = scope.commands.includes('chat-interactions') && !!artifactId;
  useEffect(() => {
    if (!near || !readable) return;
    const controller = new AbortController();
    setFailure('');
    void invoke<{ artifact?: ArtifactFile }>(
      'chat-interactions',
      { conversation_id: conversation, view: 'artifact', artifact_id: artifactId },
      { signal: controller.signal }
    )
      .then((value) => {
        if (!controller.signal.aborted) setFile(value.artifact);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted)
          setFailure(error instanceof Error ? error.message : String(error));
      });
    return () => controller.abort();
  }, [near, readable, conversation, artifactId, attempt]);

  const filename = event.filename ?? '';
  const Icon = categoryIcon(event.category ?? 'other');
  const url = file?.url ?? (event.url || undefined);
  const picture = event.category === 'image';
  const failed = failure || !!event.error;
  return (
    <div ref={card} className="flex items-start gap-3 pb-1">
      <div className="w-8 shrink-0" />
      <div className={`flex-1 min-w-0 ${WIDE_MESSAGE_MAX_WIDTH_CLASSES}`}>
        <div className="rounded-md bg-white p-4 shadow-[0_0_0_1px_rgba(15,23,42,0.055),0_6px_16px_-16px_rgba(15,23,42,0.22)] dark:bg-slate-950 dark:shadow-[0_0_0_1px_rgba(148,163,184,0.12)]">
          <div className="mb-3 flex min-w-0 items-center gap-2">
            <Icon size={17} className="shrink-0 text-emerald-600 dark:text-emerald-400" />
            <span className="text-xs font-semibold text-slate-700 dark:text-slate-300">
              {t('agent.messageBubble.fileGenerated', 'File Generated')}
            </span>
            {event.sourceTool && (
              <span className="max-w-[180px] truncate rounded-full bg-emerald-50 px-2 py-0.5 text-2xs font-medium text-emerald-700 ring-1 ring-emerald-100 dark:bg-emerald-950/45 dark:text-emerald-300 dark:ring-emerald-800/60">
                {event.sourceTool}
              </span>
            )}
          </div>
          {picture && file?.preview && (
            <div className="relative mb-3 overflow-hidden rounded-md border border-slate-200 bg-slate-50 dark:border-slate-800 dark:bg-slate-900">
              <img
                src={file.preview}
                alt={filename}
                className="max-w-full max-h-[300px] object-contain"
              />
            </div>
          )}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-md border border-slate-200/55 bg-slate-50/80 px-3 py-2.5 text-xs dark:border-slate-800/60 dark:bg-slate-900/60">
            <div className="flex min-w-[220px] flex-1 items-center gap-2">
              <File size={16} className="shrink-0 text-emerald-600 dark:text-emerald-400" />
              <span
                className="min-w-0 truncate font-medium text-slate-800 dark:text-slate-200"
                title={filename}
              >
                {filename}
              </span>
            </div>
            <span className="whitespace-nowrap text-xs text-slate-500 dark:text-slate-400">
              {formatFileSize(event.sizeBytes ?? 0)}
            </span>
            {url ? (
              <a
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                download={filename}
                data-testid="artifact-download"
                className="touch-target inline-flex items-center gap-1 rounded text-xs font-medium text-emerald-700 transition-colors duration-150 hover:text-emerald-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 dark:text-emerald-300 dark:hover:text-emerald-200"
              >
                <Download size={16} />
                {t('agent.messageBubble.download', 'Download')}
              </a>
            ) : failed ? (
              <>
                <span className="flex items-center gap-1 text-xs text-red-500 dark:text-red-400">
                  <XCircle size={14} />
                  {failure || t('agent.messageBubble.uploadFailed', 'Upload failed')}
                </span>
                {failure && (
                  <button
                    type="button"
                    onClick={() => setAttempt((value) => value + 1)}
                    className="touch-target inline-flex items-center gap-1.5 rounded-md bg-red-100 px-3 py-1.5 text-xs font-medium text-red-700 transition-colors duration-150 hover:bg-red-200 disabled:opacity-50 dark:bg-red-800/50 dark:text-red-300 dark:hover:bg-red-700/50"
                  >
                    <RefreshCw size={12} />
                    {t('agent.messageBubble.refreshLink', 'Refresh Link')}
                  </button>
                )}
              </>
            ) : (
              <span className="flex items-center gap-1 text-xs text-content-tertiary">
                {near && readable ? (
                  <Loader2 size={14} className="animate-spin motion-reduce:animate-none" />
                ) : (
                  <FileOutput size={14} />
                )}
                {file?.status === 'error'
                  ? t('agent.messageBubble.uploadFailed', 'Upload failed')
                  : t('agent.messageBubble.uploading', 'Uploading…')}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
