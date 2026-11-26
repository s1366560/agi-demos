import { useEffect, useState } from 'react';
import type { CloudSessionProjection } from '../api/cloudSessionProjectionClient';
import { useI18n } from '../i18n';
import { transport } from '../packageHost/transport';

type Project = {
  project_id: string;
  tenant_id: string;
  project_name: string;
  tenant_name: string;
};

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
  const [projects, setProjects] = useState<Project[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    void transport<Project[]>('/api/v1/project-packages/projects/', { signal: controller.signal })
      .then((items) => setProjects(items.filter((item) => item.tenant_id === tenant)))
      .catch((cause) => {
        if (!controller.signal.aborted) setError(String(cause));
      });
    return () => controller.abort();
  }, [tenant]);
  const current = session?.workspaceContext.projectId ?? null;
  async function openProject(project: Project) {
    setBusy(true);
    setError('');
    try {
      await transport('/api/v1/workspace-context/switch', {
        method: 'POST',
        body: {
          tenant_id: project.tenant_id,
          project_id: project.project_id,
          expected_revision: session?.workspaceContext.revision ?? 0,
          idempotency_key: crypto.randomUUID(),
        },
      });
      window.location.hash =
        '/tenant/' +
        encodeURIComponent(project.tenant_id) +
        '/project/' +
        encodeURIComponent(project.project_id);
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
          <li key={project.project_id}>
            <button
              type="button"
              aria-current={project.project_id === current ? 'true' : undefined}
              disabled={busy}
              onClick={() => void openProject(project)}
            >
              {project.project_name}
            </button>
          </li>
        ))}
      </ul>
      {!projects.length && !error ? <p role="status">{t('settings.noProjectSelected')}</p> : null}
    </main>
  );
}
