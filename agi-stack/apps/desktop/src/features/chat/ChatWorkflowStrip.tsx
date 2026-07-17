import type { ReactNode } from 'react';
import {
  ActivityLogIcon,
  ArchiveIcon,
  CodeIcon,
  DotsHorizontalIcon,
  ReaderIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';

export type ChatWorkflowTarget = 'changes' | 'pull' | 'plan' | 'background' | 'artifacts';

export function ChatWorkflowStrip({
  activeTarget,
  workflowCounts,
  onSelect,
}: {
  activeTarget: ChatWorkflowTarget;
  workflowCounts?: Partial<Record<ChatWorkflowTarget, number | string>>;
  onSelect: (target: ChatWorkflowTarget) => void;
}) {
  const { t } = useI18n();
  const items: Array<[ChatWorkflowTarget, string, string, ReactNode]> = [
    ['changes', t('chat.changes'), '+0 -0', <CodeIcon key="changes" />],
    ['pull', t('chat.pullRequest'), t('chat.idle'), <ReaderIcon key="pull" />],
    ['plan', t('chat.plan'), t('chat.idle'), <ActivityLogIcon key="plan" />],
    ['background', t('chat.background'), '0', <DotsHorizontalIcon key="background" />],
    ['artifacts', t('chat.artifacts'), '0', <ArchiveIcon key="artifacts" />],
  ];

  return (
    <div
      className="composer-workflows chat-composer-workflows"
      aria-label={t('chat.workflowShortcuts')}
    >
      {items.map(([target, label, value, icon]) => (
        <button
          className={activeTarget === target ? 'selected' : ''}
          type="button"
          aria-label={`${label} ${workflowCounts?.[target] ?? value}`}
          key={target}
          onClick={() => onSelect(target)}
        >
          <span>{icon}</span>
          <strong>{label}</strong>
          <em>{workflowCounts?.[target] ?? value}</em>
        </button>
      ))}
    </div>
  );
}
