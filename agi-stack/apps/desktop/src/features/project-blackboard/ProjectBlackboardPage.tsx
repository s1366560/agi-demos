import { Button } from '@radix-ui/themes';

import { useI18n } from '../../i18n';
import { WorkspaceCollaborationCanvas } from '../workspace/WorkspaceCollaborationCanvas';
import type { ProjectBlackboardViewModel } from './projectBlackboardPresentationModel';

export function ProjectBlackboardPage({
  model,
  onRetry,
}: Readonly<{
  model: ProjectBlackboardViewModel;
  onRetry: () => void;
}>) {
  const { t } = useI18n();
  if (
    (model.state === 'ready' || model.state === 'degraded') &&
    model.collaborationClient !== null
  ) {
    return (
      <section data-authority={model.authority} data-state={model.state}>
        {model.reasonCode ? <code>{model.reasonCode}</code> : null}
        <WorkspaceCollaborationCanvas
          workspaceId={model.scope.workspaceId}
          client={model.collaborationClient}
          initialSurface={model.initialSurface}
        />
      </section>
    );
  }
  const stateKey =
    model.state === 'scope_switch' ? 'loading' : model.state === 'forbidden' ? 'forbidden' : model.state;
  return (
    <section className="workspace-collaboration-state" data-state={model.state}>
      <h1>{t(`tenantWorkspaces.state.${stateKey}.title`)}</h1>
      <p>{t(`tenantWorkspaces.state.${stateKey}.description`)}</p>
      {model.reasonCode ? <code>{model.reasonCode}</code> : null}
      {model.retryVisible ? <Button onClick={onRetry}>{t('common.retry')}</Button> : null}
    </section>
  );
}
