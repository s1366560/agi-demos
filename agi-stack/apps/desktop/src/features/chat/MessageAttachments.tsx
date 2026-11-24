import { useI18n } from '../../i18n';
import type { AgentTimelineItem } from '../../types';
import { timelineMessageAttachments } from './messageAttachmentModel';
import { MessageFileList } from '@business/agent/ui/desktop/chat/MessageFileList';
export function MessageAttachments({ item }: { item: AgentTimelineItem }) {
  const { t } = useI18n();
  return (
    <MessageFileList
      attachments={timelineMessageAttachments(item)}
      label={t('composer.attachments')}
    />
  );
}
