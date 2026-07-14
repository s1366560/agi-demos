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
  hasSessionControls: boolean,
): WorkspaceReviewPanelChrome {
  return {
    showHeader: false,
    showOverflowMenus: false,
    showPanelModeActions: false,
    showSessionLayoutActions: hasSessionControls,
  };
}
