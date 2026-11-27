import { useEffect, useState } from 'react';
import type { CloudSessionProjection } from '../api/cloudSessionProjectionClient';
import { useI18n } from '../i18n';
import { transport } from '../packageHost/transport';
import { loadTenantProjects, type CatalogProject, type CatalogProjectStats } from './projectCatalog';

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
      <ul className="desktop-project-catalog">
        {projects.map((project) => (
          <li key={project.id}>
            <button
              type="button"
              className="desktop-project-card"
              aria-current={project.id === current ? 'true' : undefined}
              disabled={busy}
              onClick={() => void openProject(project)}
            >
              <span className="desktop-project-card-heading">
                <span>
                  <strong>{project.name}</strong>
                  <small>
                    {t('fullHost.project.id')} {project.id.slice(0, 8)}
                  </small>
                </span>
                {project.is_public === undefined ? null : (
                  <span className="desktop-project-card-badge">
                    {t(project.is_public ? 'fullHost.project.public' : 'fullHost.project.private')}
                  </span>
                )}
              </span>
              {project.stats ? <ProjectUsage stats={project.stats} /> : null}
            </button>
          </li>
        ))}
      </ul>
      {!projects.length && !error ? <p role="status">{t('settings.noProjectSelected')}</p> : null}
    </main>
  );
}

function ProjectUsage({ stats }: { stats: CatalogProjectStats }) {
  const { t } = useI18n();
  const limit = stats.storage_limit > 0 ? stats.storage_limit : 1024 * 1024 * 1024;
  const used = Math.max(0, stats.storage_used);
  const percent = Math.min(100, Math.round((used / limit) * 1000) / 10);
  return (
    <>
      <span className="desktop-project-card-usage">
        <span>{t('fullHost.project.usage')}</span>
        <strong>{formatBytes(used)}</strong>
      </span>
      <span className="desktop-project-card-meter" aria-hidden="true">
        <span style={{ width: `${percent}%` }} />
      </span>
      <span className="desktop-project-card-meta">
        <span>
          {stats.memory_count} {t('fullHost.project.memories')}
        </span>
        <span>
          {stats.node_count} {t('fullHost.project.nodes')}
        </span>
        <span>
          {stats.member_count} {t('fullHost.project.members')}
        </span>
      </span>
    </>
  );
}

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const shown = unit === 0 || value >= 10 ? Math.round(value) : Math.round(value * 10) / 10;
  return `${shown} ${units[unit]}`;
}
