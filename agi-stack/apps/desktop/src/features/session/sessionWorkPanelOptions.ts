import type { ReviewTab } from '../../appShellTypes';
import type { DesktopSessionCanvasInputV2 } from '../../plugins/DesktopSessionCanvasSurfaceV2';
import { buildSessionAgentTree } from './sessionAgentTreeModel';
import { sessionCanvasTabs } from './sessionCanvasModel';
import { buildSessionContextWindow } from './sessionContextWindowModel';
import { buildSessionExecutionGraph } from './sessionExecutionGraphModel';
import { buildSessionExecutionInsights } from './sessionExecutionInsightsModel';
import { buildSessionRuntimeInfrastructure } from './sessionRuntimeInfrastructureModel';

export type SessionWorkPanelOption = {
  id: ReviewTab;
  labelKey: string;
  available: boolean;
  reasonKey?: string;
  group: 'work' | 'details';
};

export function getSessionWorkPanelOptions(
  state: DesktopSessionCanvasInputV2['state'],
): SessionWorkPanelOption[] {
  const configured = sessionCanvasTabs(state.capabilityMode);
  const available = new Set<ReviewTab>(
    [...configured.primary, ...configured.secondary].map((tab) => tab.id),
  );
  if (state.artifactCanvas.tabs.length > 0 || state.artifactVersions.length > 0) {
    available.add('artifacts');
  }
  const option = (
    id: ReviewTab,
    labelKey: string,
    enabled: boolean,
    group: SessionWorkPanelOption['group'],
    reasonKey = 'rightbar.awaitingData',
  ): SessionWorkPanelOption => ({
    id,
    labelKey,
    available: enabled,
    ...(enabled ? {} : { reasonKey }),
    group,
  });
  const workTabs = [
    ['plan', 'session.canvasPlan'],
    ['changes', 'session.canvasChanges'],
    ['artifacts', 'session.canvasArtifacts'],
    ['terminal', 'session.canvasTerminal'],
    ['checks', 'session.canvasChecks'],
    ['verification', 'session.canvasVerification'],
    ['sources', 'session.canvasSources'],
  ] as const;
  const timeline = state.timelineItems;
  return [
    ...workTabs.map(([id, label]) =>
      option(id, label, available.has(id), 'work', 'rightbar.unsupportedMode'),
    ),
    option(
      'apps',
      'session.canvasApps',
      state.mcpAppCanvas.tabs.length > 0,
      'work',
      'rightbar.noApps',
    ),
    option('overview', 'session.runSnapshot', true, 'details'),
    option(
      'activity',
      'session.canvasActivity',
      timeline.length > 0 || state.toolInvocations.length > 0,
      'details',
    ),
    option(
      'agents',
      'session.canvasAgents',
      buildSessionAgentTree(timeline).summary.total > 0,
      'details',
    ),
    option(
      'graph',
      'session.canvasGraph',
      Boolean(buildSessionExecutionGraph(timeline).activeRun),
      'details',
    ),
    option(
      'insights',
      'session.canvasInsights',
      Boolean(buildSessionExecutionInsights(timeline).activeTrace),
      'details',
    ),
    option(
      'context',
      'session.canvasContext',
      Boolean(buildSessionContextWindow(timeline).current),
      'details',
    ),
    option(
      'runtime',
      'session.canvasRuntime',
      buildSessionRuntimeInfrastructure(timeline).events.length > 0,
      'details',
    ),
  ];
}
