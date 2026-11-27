import { useEffect, useState } from 'react';
import type { CloudSessionProjection } from '../api/cloudSessionProjectionClient';
import { useI18n } from '../i18n';
import { transport } from '../packageHost/transport';
import { loadTenantProjects, type CatalogProject } from './projectCatalog';

export function ProjectDirectory({
  session,
  tenant,
  reload,
}: {
  session: CloudSessionProjection | null;
  tenant: string;
  reload(): Promise<void>;
}) {
  const { t } = useI18n();
  const [projects, setProjects] = useState<CatalogProject[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!tenant) return;
    const controller = new AbortController();
    void loadTenantProjects(transport, tenant, controller.signal)
      .then(setProjects)
      .catch((cause) => {
        if (!controller.signal.aborted) setError(String(cause));
      });
    return () => controller.abort();
  }, [tenant]);
  const current = session?.workspaceContext.projectId ?? null;
  async function openProject(project: CatalogProject) {
    setBusy(true);
    setError('');
    try {
      await transport('/api/v1/workspace-context/switch', {
        method: 'POST',
        body: {
          tenant_id: project.tenant_id,
          project_id: project.id,
          expected_revision: session?.workspaceContext.revision ?? 0,
          idempotency_key: crypto.randomUUID(),
        },
      });
      window.location.hash =
        '/tenant/' +
        encodeURIComponent(project.tenant_id) +
        '/project/' +
        encodeURIComponent(project.id);
      await reload();
    } catch (cause) {
      setError(String(cause));
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="desktop-host-administration">
      <h1>{t('nav.projects')}</h1>
      {error ? <p role="alert">{error}</p> : null}
      <ul>
        {projects.map((project) => (
          <li key={project.id}>
            <button
              type="button"
              aria-current={project.id === current ? 'true' : undefined}
              disabled={busy}
              onClick={() => void openProject(project)}
            >
              {project.name}
            </button>
          </li>
        ))}
      </ul>
      {!projects.length && !error ? <p role="status">{t('settings.noProjectSelected')}</p> : null}
    </main>
  );
}
