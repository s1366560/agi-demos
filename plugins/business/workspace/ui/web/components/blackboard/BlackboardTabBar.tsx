import { useCallback, useMemo } from 'react';
import type { KeyboardEvent as ReactKeyboardEvent, RefObject } from 'react';

import { useTranslation } from 'react-i18next';

import {
  Activity,
  FileText,
  GitBranch,
  MessageSquare,
  Network,
  NotebookTabs,
  Settings,
  Target,
  Users,
  Workflow,
} from 'lucide-react';

import { BLACKBOARD_TAB_META } from './blackboardSurfaceContract';

export type BlackboardTab =
  | 'goals'
  | 'discussion'
  | 'collaboration'
  | 'members'
  | 'genes'
  | 'files'
  | 'status'
  | 'notes'
  | 'topology'
  | 'settings';

export interface BlackboardTabBarProps {
  activeTab: BlackboardTab;
  onTabChange: (tab: BlackboardTab) => void;
  tabListRef: RefObject<HTMLDivElement | null>;
  orientation?: 'horizontal' | 'vertical';
  tabSummaries?: Partial<Record<BlackboardTab, string | number>> | undefined;
}

export function BlackboardTabBar({
  activeTab,
  onTabChange,
  tabListRef,
  orientation = 'horizontal',
  tabSummaries,
}: BlackboardTabBarProps) {
  const { t } = useTranslation();

  const tabs = useMemo(
    () =>
      [
        {
          key: 'goals',
          label: t('blackboard.tabs.goals', 'Goals / Tasks'),
          group: 'work',
          icon: Target,
        },
        {
          key: 'discussion',
          label: t('blackboard.tabs.discussion', 'Discussion'),
          group: 'work',
          icon: MessageSquare,
        },
        {
          key: 'status',
          label: t('blackboard.tabs.status', 'Status'),
          group: 'work',
          icon: Activity,
        },
        {
          key: 'collaboration',
          label: t('blackboard.tabs.collaboration', 'Collaboration'),
          group: 'collaboration',
          icon: Workflow,
        },
        {
          key: 'members',
          label: t('blackboard.tabs.members', 'Members'),
          group: 'collaboration',
          icon: Users,
        },
        {
          key: 'genes',
          label: t('blackboard.tabs.genes', 'Genes'),
          group: 'knowledge',
          icon: GitBranch,
        },
        {
          key: 'files',
          label: t('blackboard.tabs.files', 'Files'),
          group: 'knowledge',
          icon: FileText,
        },
        {
          key: 'notes',
          label: t('blackboard.tabs.notes', 'Notes'),
          group: 'knowledge',
          icon: NotebookTabs,
        },
        {
          key: 'topology',
          label: t('blackboard.tabs.topology', 'Topology'),
          group: 'system',
          icon: Network,
        },
        {
          key: 'settings',
          label: t('blackboard.tabs.settings', 'Settings'),
          group: 'system',
          icon: Settings,
        },
      ] as const,
    [t]
  );
  const tabGroups = useMemo(
    () =>
      [
        { key: 'work', label: t('blackboard.tabGroups.work', 'Work') },
        { key: 'collaboration', label: t('blackboard.tabGroups.collaboration', 'People') },
        { key: 'knowledge', label: t('blackboard.tabGroups.knowledge', 'Knowledge') },
        { key: 'system', label: t('blackboard.tabGroups.system', 'System') },
      ] as const,
    [t]
  );

  const moveTabFocus = useCallback(
    (nextIndex: number) => {
      const nextTab = tabs[nextIndex];
      if (!nextTab) {
        return;
      }

      onTabChange(nextTab.key);

      requestAnimationFrame(() => {
        const nextButton = tabListRef.current?.querySelector<HTMLButtonElement>(
          `#blackboard-tab-${nextTab.key}`
        );
        nextButton?.focus();
      });
    },
    [onTabChange, tabListRef, tabs]
  );

  const handleTabKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLButtonElement>, index: number) => {
      const lastIndex = tabs.length - 1;
      const nextKey = orientation === 'vertical' ? 'ArrowDown' : 'ArrowRight';
      const prevKey = orientation === 'vertical' ? 'ArrowUp' : 'ArrowLeft';

      if (event.key === nextKey) {
        event.preventDefault();
        moveTabFocus(index === lastIndex ? 0 : index + 1);
        return;
      }

      if (event.key === prevKey) {
        event.preventDefault();
        moveTabFocus(index === 0 ? lastIndex : index - 1);
        return;
      }

      if (event.key === 'Home') {
        event.preventDefault();
        moveTabFocus(0);
        return;
      }

      if (event.key === 'End') {
        event.preventDefault();
        moveTabFocus(lastIndex);
      }
    },
    [moveTabFocus, orientation, tabs.length]
  );

  const isVertical = orientation === 'vertical';
  const listClassName = isVertical
    ? 'flex min-h-0 w-full flex-col gap-4 overflow-y-auto border-r border-border-light bg-surface-muted/45 p-3 dark:border-border-dark dark:bg-surface-dark-alt/45'
    : 'flex snap-x gap-1 overflow-x-auto border-b border-border-light px-3 py-2 [-ms-overflow-style:none] [scrollbar-width:none] dark:border-border-dark sm:px-4 [&::-webkit-scrollbar]:hidden';
  const buttonBase = isVertical
    ? 'min-h-10 w-full rounded-md px-2.5 py-2 text-left text-sm transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50'
    : 'min-h-11 shrink-0 snap-start whitespace-nowrap rounded-md px-3 py-2 text-sm transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50';

  const renderTabButton = (tab: (typeof tabs)[number]) => {
    const Icon = tab.icon;
    const summary = tabSummaries?.[tab.key];

    return (
      <button
        key={tab.key}
        type="button"
        role="tab"
        id={`blackboard-tab-${tab.key}`}
        aria-selected={activeTab === tab.key}
        aria-controls={`blackboard-panel-${tab.key}`}
        tabIndex={activeTab === tab.key ? 0 : -1}
        onKeyDown={(event) => {
          handleTabKeyDown(
            event,
            tabs.findIndex((item) => item.key === tab.key)
          );
        }}
        onClick={() => {
          onTabChange(tab.key);
        }}
        data-blackboard-boundary={BLACKBOARD_TAB_META[tab.key].boundary}
        data-blackboard-authority={BLACKBOARD_TAB_META[tab.key].authority}
        className={`${buttonBase} ${
          activeTab === tab.key
            ? 'border border-border-light bg-surface-light font-medium text-text-primary shadow-sm dark:border-border-dark dark:bg-surface-elevated dark:text-text-inverse'
            : 'border border-transparent text-text-secondary hover:bg-surface-light hover:text-text-primary dark:text-text-muted dark:hover:bg-surface-elevated dark:hover:text-text-inverse'
        }`}
      >
        <span className="flex min-w-0 items-center gap-2">
          <Icon size={15} className="shrink-0" aria-hidden="true" />
          <span className="truncate">{tab.label}</span>
          {summary !== undefined && summary !== '' && (
            <span className="ml-auto flex min-w-5 shrink-0 items-center justify-center rounded border border-current/15 px-1.5 py-0.5 text-[10px] tabular-nums opacity-70">
              {summary}
            </span>
          )}
        </span>
      </button>
    );
  };

  return (
    <div
      ref={tabListRef}
      role="tablist"
      aria-label={t('blackboard.tabs.ariaLabel', 'Blackboard sections')}
      aria-orientation={orientation}
      className={listClassName}
    >
      {isVertical
        ? tabGroups.map((group) => {
            const groupTabs = tabs.filter((tab) => tab.group === group.key);
            return (
              <div key={group.key} role="group" aria-label={group.label} className="space-y-1">
                <div className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-wide text-text-muted dark:text-text-muted">
                  {group.label}
                </div>
                {groupTabs.map(renderTabButton)}
              </div>
            );
          })
        : tabs.map(renderTabButton)}
    </div>
  );
}

export const BLACKBOARD_TABS = [
  'goals',
  'discussion',
  'collaboration',
  'members',
  'genes',
  'files',
  'status',
  'notes',
  'topology',
  'settings',
] as const;
