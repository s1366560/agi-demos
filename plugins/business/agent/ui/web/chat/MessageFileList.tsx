import {
  Image as ImageIcon,
  Film,
  AudioLines,
  FileText,
  Table as TableIcon,
  Presentation,
  FileArchive,
  Code as CodeIcon,
  File as FileIcon,
} from 'lucide-react';
import { formatFileSize } from '../../../../../../sdk/memstack-plugin-sdk/ui/formatFileSize';
const getFileIconComponent = (mimeType: string) => {
  if (mimeType.startsWith('image/')) return ImageIcon;
  if (mimeType.startsWith('video/')) return Film;
  if (mimeType.startsWith('audio/')) return AudioLines;
  if (mimeType === 'application/pdf') return FileText;
  if (mimeType.includes('spreadsheet') || mimeType.includes('excel')) return TableIcon;
  if (mimeType.includes('presentation') || mimeType.includes('powerpoint')) return Presentation;
  if (mimeType.includes('zip') || mimeType.includes('tar') || mimeType.includes('compress'))
    return FileArchive;
  if (
    mimeType.startsWith('text/') ||
    mimeType.includes('json') ||
    mimeType.includes('xml') ||
    mimeType.includes('javascript') ||
    mimeType.includes('typescript')
  )
    return CodeIcon;
  return FileIcon;
};

export interface MessageFile {
  filename: string;
  size_bytes: number;
  mime_type: string;
}
export function MessageFileList({
  files: fileMetadata,
  spaced,
}: {
  files?: readonly MessageFile[] | undefined;
  spaced?: boolean;
}) {
  return (
    <>
      {' '}
      {fileMetadata && fileMetadata.length > 0 && (
        <div className={`flex flex-col gap-1 ${spaced ? 'mt-2' : 'mt-0.5'}`}>
          {fileMetadata.map((file, idx) => (
            <div
              key={idx.toString()}
              className="inline-flex items-center gap-2 px-3 py-1.5 bg-slate-100 dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-lg"
            >
              {(() => {
                const Icon = getFileIconComponent(file.mime_type);
                return <Icon size={16} className="text-slate-500 dark:text-slate-400" />;
              })()}
              <span className="text-xs text-slate-700 dark:text-slate-300 truncate max-w-50">
                {file.filename}
              </span>
              <span className="text-2xs text-content-tertiary whitespace-nowrap">
                {formatFileSize(file.size_bytes)}
              </span>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
