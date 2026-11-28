import { useI18n } from '../../i18n';
import type { SubagentToolActivity } from './subagentToolActivityModel';

import { ToolActivityList } from '@business/agent/ui/desktop/chat/ToolActivityList';
export function SubagentToolActivityList({items}: {items: readonly SubagentToolActivity[]}) {
  const {t}=useI18n();return <ToolActivityList items={items} t={t} />;
}
