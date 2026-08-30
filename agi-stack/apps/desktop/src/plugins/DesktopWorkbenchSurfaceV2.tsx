import type { ComponentProps } from 'react';

import { ChatPanel } from '../features/chat/ChatPanel';
import { PlatformPluginConversationSlots } from '../features/chat/PlatformPluginConversationSlots';
import { SessionWorkspace } from '../features/session/SessionWorkspace';
import { NewThreadComposer } from '../features/task/NewThreadComposer';
import { WorkspaceCollaborationCanvas } from '../features/workspace/WorkspaceCollaborationCanvas';
import { WorkspaceOverview } from '../features/workspace/WorkspaceOverview';
import { useI18n } from '../i18n';
import type { DesktopActivityInboxInputV2 } from './DesktopActivityInboxSurfaceV2';
import type { DesktopMyWorkQueueInputV2 } from './DesktopMyWorkQueueSurfaceV2';
import { DesktopRendererActivityInboxV2 } from './DesktopRendererActivityInboxV2';
import { DesktopRendererMyWorkQueueV2 } from './DesktopRendererMyWorkQueueV2';

type DesktopWorkbenchWorkspaceViewV2 = Readonly<{
  kind: 'workspace';
  overview: Readonly<ComponentProps<typeof WorkspaceOverview>>;
  collaboration: Readonly<ComponentProps<typeof WorkspaceCollaborationCanvas>> | null;
}>;

type DesktopWorkbenchChatViewV2 = Readonly<{
  kind: 'chat';
  chatPanel: Readonly<ComponentProps<typeof ChatPanel>>;
}>;

type DesktopWorkbenchBoardViewV2 = Readonly<{
  kind: 'board';
  myWorkQueue: DesktopMyWorkQueueInputV2;
}>;

type DesktopWorkbenchActivityViewV2 = Readonly<{
  kind: 'activity';
  activityInbox: DesktopActivityInboxInputV2;
}>;

type DesktopWorkbenchHomeViewV2 = Readonly<{
  kind: 'home';
  composerScopeKey: string;
  composer: Readonly<ComponentProps<typeof NewThreadComposer>>;
}>;

export type DesktopWorkbenchViewV2 =
  | DesktopWorkbenchWorkspaceViewV2
  | DesktopWorkbenchChatViewV2
  | DesktopWorkbenchBoardViewV2
  | DesktopWorkbenchActivityViewV2
  | DesktopWorkbenchHomeViewV2;

export type DesktopWorkbenchSessionFrameV2 = Readonly<
  Omit<ComponentProps<typeof SessionWorkspace>, 'thread'>
>;

export interface DesktopWorkbenchSurfaceViewModelV2 {
  readonly error: Readonly<{
    message: string;
    onRetry: (() => void) | null;
  }> | null;
  readonly paneStageClassName: string;
  readonly session: DesktopWorkbenchSessionFrameV2 | null;
  readonly view: DesktopWorkbenchViewV2;
}

export interface DesktopWorkbenchSurfaceV2Props {
  readonly viewModel: DesktopWorkbenchSurfaceViewModelV2;
}

export function DesktopWorkbenchSurfaceV2({ viewModel }: DesktopWorkbenchSurfaceV2Props) {
  const { t } = useI18n();
  const view = renderDesktopWorkbenchViewV2(viewModel.view);
  return (
    <>
      {viewModel.error ? (
        <div className="workbench-error" role="alert" aria-live="polite">
          <span>{viewModel.error.message}</span>
          {viewModel.error.onRetry ? (
            <button type="button" onClick={viewModel.error.onRetry}>
              {t('runtime.retryWorkspace')}
            </button>
          ) : null}
        </div>
      ) : null}
      {viewModel.session ? (
        <SessionWorkspace
          {...viewModel.session}
          thread={<section className={viewModel.paneStageClassName}>{view}</section>}
        />
      ) : (
        <section className="workbench-layout">
          <section className={viewModel.paneStageClassName}>{view}</section>
        </section>
      )}
    </>
  );
}

function renderDesktopWorkbenchViewV2(view: DesktopWorkbenchViewV2) {
  switch (view.kind) {
    case 'workspace':
      return (
        <>
          <WorkspaceOverview {...view.overview} />
          {view.collaboration ? <WorkspaceCollaborationCanvas {...view.collaboration} /> : null}
        </>
      );
    case 'chat':
      return (
        <>
          <ChatPanel {...view.chatPanel} />
          <PlatformPluginConversationSlots active />
        </>
      );
    case 'board':
      return <DesktopRendererMyWorkQueueV2 input={view.myWorkQueue} />;
    case 'activity':
      return <DesktopRendererActivityInboxV2 input={view.activityInbox} />;
    case 'home':
      return <NewThreadComposer key={view.composerScopeKey} {...view.composer} />;
  }
}
