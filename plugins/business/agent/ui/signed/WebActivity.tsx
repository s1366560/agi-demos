import { useEffect, useState } from 'react';
import { ProjectActivityInbox } from '../../../../../web/src/components/agent/activity/ProjectActivityInbox';
import { projectWorkService } from './reviewAuthority';
import type { RichPageContext } from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';

export function WebActivity({
  scope,
  onOpen,
}: {
  scope: RichPageContext;
  onOpen: (id: string) => void;
}) {
  const [identity, setIdentity] = useState('');
  const [error, setError] = useState('');
  useEffect(() => {
    if (!scope.projectId || !scope.commands.includes('activity-list')) return;
    const controller = new AbortController();
    void projectWorkService
      .getReadState(scope.projectId, { signal: controller.signal })
      .then((row) => {
        if (!controller.signal.aborted) setIdentity(row.principal_id);
      })
      .catch((cause) => {
        if (!controller.signal.aborted) setError(String(cause));
      });
    return () => controller.abort();
  }, [scope]);
  if (error) return <span role="alert">{error}</span>;
  if (!identity || !scope.projectId) return null;
  return (
    <ProjectActivityInbox
      projectId={scope.projectId}
      principalId={identity}
      tenantId={scope.tenantId}
      onOpenConversation={onOpen}
    />
  );
}
