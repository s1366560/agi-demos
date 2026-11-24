import {
  FileIcon,
  FileTextIcon,
  ImageIcon,
  SpeakerLoudIcon,
  VideoIcon,
} from '@radix-ui/react-icons';

import { formatFileSize } from '../../../../../../sdk/memstack-plugin-sdk/ui/formatFileSize';
type Attachment = {
  filename: string;
  mimeType: string;
  sizeBytes: number;
  sandboxPath?: string | null;
};
function AttachmentTypeIcon({ mimeType }: { mimeType: string }) {
  if (mimeType.startsWith('image/')) return <ImageIcon />;
  if (mimeType.startsWith('video/')) return <VideoIcon />;
  if (mimeType.startsWith('audio/')) return <SpeakerLoudIcon />;
  if (mimeType.startsWith('text/') || mimeType === 'application/pdf') {
    return <FileTextIcon />;
  }
  return <FileIcon />;
}

function MessageAttachment({ attachment }: { attachment: Attachment }) {
  return (
    <li className="message-attachment" data-testid="message-attachment">
      <span className="message-attachment-icon" aria-hidden="true">
        <AttachmentTypeIcon mimeType={attachment.mimeType} />
      </span>
      <span className="message-attachment-name" title={attachment.filename}>
        {attachment.filename}
      </span>
      <span className="message-attachment-size">{formatFileSize(attachment.sizeBytes)}</span>
    </li>
  );
}

export function MessageFileList({
  attachments,
  label,
}: {
  attachments: readonly Attachment[];
  label: string;
}) {
  if (attachments.length === 0) return null;

  return (
    <ul className="message-attachments" aria-label={label}>
      {attachments.map((attachment) => (
        <MessageAttachment
          key={
            attachment.sandboxPath ??
            `${attachment.filename}:${attachment.mimeType}:${attachment.sizeBytes}`
          }
          attachment={attachment}
        />
      ))}
    </ul>
  );
}
