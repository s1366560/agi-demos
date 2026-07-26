import {
  FileIcon,
  FileTextIcon,
  ImageIcon,
  SpeakerLoudIcon,
  VideoIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type { AgentTimelineItem } from '../../types';
import {
  formatTimelineAttachmentSize,
  timelineMessageAttachments,
  type TimelineMessageAttachment,
} from './messageAttachmentModel';

function AttachmentTypeIcon({ mimeType }: { mimeType: string }) {
  if (mimeType.startsWith('image/')) return <ImageIcon />;
  if (mimeType.startsWith('video/')) return <VideoIcon />;
  if (mimeType.startsWith('audio/')) return <SpeakerLoudIcon />;
  if (mimeType.startsWith('text/') || mimeType === 'application/pdf') {
    return <FileTextIcon />;
  }
  return <FileIcon />;
}

function MessageAttachment({ attachment }: { attachment: TimelineMessageAttachment }) {
  return (
    <li className="message-attachment" data-testid="message-attachment">
      <span className="message-attachment-icon" aria-hidden="true">
        <AttachmentTypeIcon mimeType={attachment.mimeType} />
      </span>
      <span className="message-attachment-name" title={attachment.filename}>
        {attachment.filename}
      </span>
      <span className="message-attachment-size">
        {formatTimelineAttachmentSize(attachment.sizeBytes)}
      </span>
    </li>
  );
}

export function MessageAttachments({ item }: { item: AgentTimelineItem }) {
  const { t } = useI18n();
  const attachments = timelineMessageAttachments(item);
  if (attachments.length === 0) return null;

  return (
    <ul className="message-attachments" aria-label={t('composer.attachments')}>
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
