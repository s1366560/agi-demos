import type { ComponentProps } from 'react';

import { WorkspaceReviewPanel } from '../features/session/WorkspaceReviewPanel';
import type { SessionCanvasControls } from '../features/session/workspaceReviewPanelModel';

type WorkspaceReviewPanelPropsV2 = ComponentProps<typeof WorkspaceReviewPanel>;

type DesktopSessionCanvasActionKeyV2 =
  | 'onAddChangeComment'
  | 'onApprovePlan'
  | 'onArtifactAction'
  | 'onAuthorityAction'
  | 'onChangeScope'
  | 'onCloseMCPAppCanvasTab'
  | 'onOpenAgentSession'
  | 'onRefreshChanges'
  | 'onRemoveChangeComment'
  | 'onRespondToHitl'
  | 'onResumeTaskListReview'
  | 'onSelectArtifactCanvasTab'
  | 'onSelectMCPAppCanvasTab'
  | 'onSendChangeComments'
  | 'onSendMCPAppMessage'
  | 'onStartTerminal'
  | 'onTabChange'
  | 'onTerminalInput'
  | 'onTerminalResize'
  | 'onToggleChangeReference';

type DesktopSessionCanvasMetaKeyV2 =
  | 'artifactClient'
  | 'mcpAppApi'
  | 'mcpAppProjectId'
  | 'mcpAppSandboxProxyUrl'
  | 'sandboxRuntime'
  | 'terminalInteractiveCapability';

type DesktopSessionCanvasStateKeyV2 = Exclude<
  keyof WorkspaceReviewPanelPropsV2,
  DesktopSessionCanvasActionKeyV2 | DesktopSessionCanvasMetaKeyV2 | 'sessionControls'
>;

export interface DesktopSessionCanvasInputV2 {
  readonly actions: Readonly<Pick<WorkspaceReviewPanelPropsV2, DesktopSessionCanvasActionKeyV2>>;
  readonly meta: Readonly<Pick<WorkspaceReviewPanelPropsV2, DesktopSessionCanvasMetaKeyV2>>;
  readonly state: Readonly<Pick<WorkspaceReviewPanelPropsV2, DesktopSessionCanvasStateKeyV2>>;
}

export interface DesktopSessionCanvasSurfacePropsV2 {
  readonly controls: SessionCanvasControls;
  readonly input: DesktopSessionCanvasInputV2;
}

export function DesktopSessionCanvasSurfaceV2({
  controls,
  input,
}: DesktopSessionCanvasSurfacePropsV2) {
  return (
    <WorkspaceReviewPanel
      {...input.state}
      {...input.meta}
      {...input.actions}
      sessionControls={controls}
    />
  );
}
