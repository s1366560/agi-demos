import type { SessionCapabilityMode } from './sessionViewModel';

export type SessionCanvasTabId =
  | 'overview'
  | 'plan'
  | 'activity'
  | 'changes'
  | 'terminal'
  | 'checks'
  | 'artifacts'
  | 'sources'
  | 'verification';

export type SessionCanvasTab = {
  id: SessionCanvasTabId;
  labelKey: string;
};

export type SessionCanvasTabs = {
  primary: SessionCanvasTab[];
  secondary: SessionCanvasTab[];
};

export type SessionCanvasVariant = 'workspace' | 'session';

export function hasAuthoritativeChangeReview(input: {
  changedFileCount: number;
  hasPendingHitlRequest: boolean;
}): boolean {
  return input.changedFileCount > 0 || input.hasPendingHitlRequest;
}

const tabs: Record<SessionCanvasTabId, SessionCanvasTab> = {
  overview: { id: 'overview', labelKey: 'session.canvasOverview' },
  plan: { id: 'plan', labelKey: 'session.canvasPlan' },
  activity: { id: 'activity', labelKey: 'session.canvasActivity' },
  changes: { id: 'changes', labelKey: 'session.canvasChanges' },
  terminal: { id: 'terminal', labelKey: 'session.canvasTerminal' },
  checks: { id: 'checks', labelKey: 'session.canvasChecks' },
  artifacts: { id: 'artifacts', labelKey: 'session.canvasArtifacts' },
  sources: { id: 'sources', labelKey: 'session.canvasSources' },
  verification: { id: 'verification', labelKey: 'session.canvasVerification' },
};

export function defaultSessionCanvasTab(
  status: string,
  mode: SessionCapabilityMode,
): SessionCanvasTabId {
  const normalizedStatus = status.trim().toLowerCase();
  if (normalizedStatus === 'needs_input' || normalizedStatus === 'needs_approval') return 'plan';
  if (mode === 'code') return 'changes';
  if (mode === 'work') return 'artifacts';
  return 'plan';
}

export function sessionCanvasTabs(
  mode: SessionCapabilityMode,
  variant: SessionCanvasVariant = 'workspace',
): SessionCanvasTabs {
  if (mode === 'code') {
    return {
      primary: [tabs.overview, tabs.plan, tabs.changes, tabs.terminal, tabs.checks],
      secondary: variant === 'workspace' ? [tabs.activity, tabs.artifacts] : [],
    };
  }
  if (mode === 'work') {
    return {
      primary: [tabs.overview, tabs.plan, tabs.artifacts, tabs.sources, tabs.verification],
      secondary: variant === 'workspace' ? [tabs.activity] : [],
    };
  }
  return {
    primary:
      variant === 'workspace'
        ? [tabs.overview, tabs.plan, tabs.activity, tabs.artifacts]
        : [tabs.overview, tabs.plan, tabs.artifacts],
    secondary: [],
  };
}
