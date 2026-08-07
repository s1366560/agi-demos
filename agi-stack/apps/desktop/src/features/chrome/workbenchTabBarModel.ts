import type { WorkbenchSection } from '../../types';

/**
 * Workbench tab model for the orca-style tab row. Pure and immutable: every
 * helper returns new arrays and never mutates its input.
 *
 * Ordering decision: view tabs always come first in the fixed declaration
 * order below (workspace is the landing view, board/automations/search/
 * activity follow the sidebar nav order), conversation tabs append after in
 * the order they were opened. This keeps the row predictable — views never
 * move, conversations queue up at the trailing edge.
 */

export type WorkbenchTabViewSection = Exclude<WorkbenchSection, 'chat' | 'settings'>;

export type WorkbenchTab =
  | { kind: 'view'; section: WorkbenchTabViewSection }
  | {
      kind: 'conversation';
      projectId: string;
      workspaceId: string;
      conversationId: string;
      title: string;
    };

export const WORKBENCH_VIEW_TAB_ORDER: readonly WorkbenchTabViewSection[] = [
  'workspace',
  'home',
  'board',
  'automations',
  'search',
  'activity',
];

/** Closing the last tab falls back to the landing view. */
export const WORKBENCH_FALLBACK_VIEW_SECTION: WorkbenchTabViewSection = 'workspace';

export function tabKey(tab: WorkbenchTab): string {
  return tab.kind === 'view'
    ? `view:${tab.section}`
    : `conversation:${tab.conversationId}`;
}

export function isSameTab(left: WorkbenchTab, right: WorkbenchTab): boolean {
  return tabKey(left) === tabKey(right);
}

export function isViewTabSection(section: WorkbenchSection): section is WorkbenchTabViewSection {
  return section !== 'chat' && section !== 'settings';
}

export function ensureViewTab(
  tabs: readonly WorkbenchTab[],
  section: WorkbenchTabViewSection,
): WorkbenchTab[] {
  if (tabs.some((tab) => tab.kind === 'view' && tab.section === section)) {
    return [...tabs];
  }
  const next: WorkbenchTab = { kind: 'view', section };
  const conversationTabs = tabs.filter((tab) => tab.kind === 'conversation');
  const viewTabs = tabs.filter(
    (tab): tab is Extract<WorkbenchTab, { kind: 'view' }> => tab.kind === 'view',
  );
  const insertBefore = viewTabs.findIndex(
    (tab) =>
      WORKBENCH_VIEW_TAB_ORDER.indexOf(tab.section) >
      WORKBENCH_VIEW_TAB_ORDER.indexOf(section),
  );
  const orderedViewTabs =
    insertBefore === -1
      ? [...viewTabs, next]
      : [...viewTabs.slice(0, insertBefore), next, ...viewTabs.slice(insertBefore)];
  return [...orderedViewTabs, ...conversationTabs];
}

export function ensureConversationTab(
  tabs: readonly WorkbenchTab[],
  conversation: {
    projectId: string;
    workspaceId: string;
    conversationId: string;
    title: string;
  },
): WorkbenchTab[] {
  const existing = tabs.find(
    (tab) => tab.kind === 'conversation' && tab.conversationId === conversation.conversationId,
  );
  if (existing) {
    // Refresh a stale title (e.g. after a rename) without moving the tab.
    if (existing.kind === 'conversation' && existing.title !== conversation.title) {
      return tabs.map((tab) => (isSameTab(tab, existing) ? { ...existing, title: conversation.title } : tab));
    }
    return [...tabs];
  }
  return [...tabs, { kind: 'conversation', ...conversation }];
}

export type CloseTabResult = {
  tabs: WorkbenchTab[];
  /** Tab to activate after closing the active one; null = activation unchanged. */
  fallback: WorkbenchTab | null;
};

export function closeTab(
  tabs: readonly WorkbenchTab[],
  tab: WorkbenchTab,
  activeTabKey: string,
): CloseTabResult {
  const index = tabs.findIndex((candidate) => isSameTab(candidate, tab));
  if (index === -1) return { tabs: [...tabs], fallback: null };
  const nextTabs = tabs.filter((candidate) => !isSameTab(candidate, tab));
  if (tabKey(tab) !== activeTabKey) return { tabs: nextTabs, fallback: null };
  // Prefer the tab that slides into the closed slot (the former right
  // neighbor), then the left neighbor, then the landing view.
  const fallback =
    nextTabs[index] ??
    nextTabs[index - 1] ?? {
      kind: 'view',
      section: WORKBENCH_FALLBACK_VIEW_SECTION,
    };
  return { tabs: nextTabs, fallback };
}

/** Project/tenant switches invalidate every conversation; view tabs survive. */
export function clearConversationTabs(tabs: readonly WorkbenchTab[]): WorkbenchTab[] {
  return tabs.filter((tab) => tab.kind === 'view');
}

export function removeTab(tabs: readonly WorkbenchTab[], tab: WorkbenchTab): WorkbenchTab[] {
  return tabs.filter((candidate) => !isSameTab(candidate, tab));
}
