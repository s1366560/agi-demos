import { createRoot } from 'react-dom/client';
import { ProjectPlaybooksView } from '../desktop/project-playbooks/ProjectPlaybooksView';
import type { ProjectPlaybooksViewModel } from '../desktop/project-playbooks/projectPlaybooksController';
import { useReflectionLibrary } from './useReflectionLibrary';
import translations from '../desktop/project-playbooks/locales.json';

function Playbooks({
  projectId,
  tenantId,
  locale,
}: {
  projectId: string;
  tenantId: string;
  locale: string;
}) {
  const { playbooks, verdicts, loading, error, onRefresh } = useReflectionLibrary();
  const strings: Record<string, string> = translations[locale.startsWith('zh') ? 'zh' : 'en'];
  const model: ProjectPlaybooksViewModel = {
    routeId: 'project-playbooks',
    state: loading
      ? 'loading'
      : error
        ? 'error'
        : playbooks.length || verdicts.length
          ? 'ready'
          : 'empty',
    reasonCode: error ? 'project_playbooks_request_failed' : null,
    allowedActions: [],
    retryVisible: !!error,
    scope: { projectId, tenantId, authority: 'cloud' },
    playbooks: playbooks.map((row) => ({
      ...row,
      projectId: row.project_id,
      hitCount: row.hit_count,
      createdAt: row.created_at,
      updatedAt: row.updated_at,
      lastUsedAt: row.last_used_at,
      trigger: {
        description: row.trigger.description,
        frictionKinds: row.trigger.friction_kinds,
        laneTransitions: row.trigger.lane_transitions,
      },
    })),
    verdicts: verdicts.map((row) => ({
      ...row,
      projectId: row.project_id,
      playbookId: row.playbook_id,
      proposedPayload: null,
      createdAt: row.created_at,
    })),
  };
  return (
    <ProjectPlaybooksView model={model} onRetry={onRefresh} t={(key) => strings[key] ?? key} />
  );
}

void window.memstack.getContext().then(({ tenantId, projectId, locale }) => {
  if (!projectId) throw new Error('project_scope_required');
  createRoot(document.getElementById('root')!).render(
    <Playbooks projectId={projectId} tenantId={tenantId} locale={locale} />
  );
});
