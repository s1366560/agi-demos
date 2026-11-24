import type { ComponentProps } from 'react';
import { useI18n } from '../../i18n';
import { ConversationSearch as PackageConversationSearch } from '@business/agent/ui/desktop/chat/ConversationSearch';

export function ConversationSearch(props: Omit<ComponentProps<typeof PackageConversationSearch>, 't'>) {
  const { t } = useI18n();
  return <PackageConversationSearch {...props} t={t} />;
}
