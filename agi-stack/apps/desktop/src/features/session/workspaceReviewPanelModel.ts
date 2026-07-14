export type WorkspaceReviewPanelVariant = 'workspace' | 'session';

export type SessionCanvasLayout = 'split' | 'focus';

export type SessionCanvasControls = {
  layout: SessionCanvasLayout;
  onLayoutChange: (layout: SessionCanvasLayout) => void;
  onClose: () => void;
};

export type WorkspaceReviewPanelChrome = {
  showHeader: boolean;
  showOverflowMenus: boolean;
  showPanelModeActions: boolean;
  showSessionLayoutActions: boolean;
};

export function workspaceReviewPanelChrome(
  variant: WorkspaceReviewPanelVariant,
  hasSessionControls: boolean,
): WorkspaceReviewPanelChrome {
  if (variant === 'session') {
    return {
      showHeader: false,
      showOverflowMenus: false,
      showPanelModeActions: false,
      showSessionLayoutActions: hasSessionControls,
    };
  }

  return {
    showHeader: true,
    showOverflowMenus: true,
    showPanelModeActions: true,
    showSessionLayoutActions: false,
  };
}

export function visibleWorkspaceReviewTabs<T extends { tab: string }>(
  variant: WorkspaceReviewPanelVariant,
  primary: T[],
  secondary: T[],
  activeTab: string,
): T[] {
  if (variant === 'session') return [...primary, ...secondary];

  const pinned = primary.slice(0, 4);
  const active = [...primary, ...secondary].find(({ tab }) => tab === activeTab);
  if (!active || pinned.some(({ tab }) => tab === active.tab)) return pinned;
  return [...primary.slice(0, 3), active];
}
