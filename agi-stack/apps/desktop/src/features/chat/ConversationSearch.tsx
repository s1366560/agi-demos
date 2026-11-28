import { searchEn, searchZh } from '@business/agent/ui/desktop/chat/searchMessages';
import type { ComponentProps } from 'react';
import { useI18n } from '../../i18n';
import { ConversationSearch as PackageConversationSearch } from '@business/agent/ui/desktop/chat/ConversationSearch';

export function ConversationSearch(props: Omit<ComponentProps<typeof PackageConversationSearch>, 't'>) {
  const { t } = useI18n(searchEn, searchZh);
  return <PackageConversationSearch {...props} t={t} />;
}
