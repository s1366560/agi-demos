import { useEffect, useState } from 'react';
import { NpmPackageSource } from '../../../../packages/plugin-marketplace-ui/src/NpmPackageSource';
import { openFilesWithDesktopDialog } from '../features/runtime/nativeFileBridge';
import { pluginArchiveBase64 } from '../api/localPluginClient';
import { DevicePluginSettings } from '../features/settings/DevicePluginSettings';
import { messages as t } from './messages';
import { packages, transport } from './transport';

type Release = {
  plugin_id: string;
  running_version: string | null;
  version: string;
  actual_digest: string | null;
  desired_revision: number;
  failure?: string;
};
type Review = {
  plugin_id: string;
  version: string;
  permissions: string[];
  digest: string;
  archive_base64: string;
};
export function PackageManagement({
  tenant,
  project,
  canManage,
  revision,
  refresh,
}: {
  tenant: string;
  project: string;
  canManage: boolean;
  revision: number;
  refresh(): void;
}) {
  const [releases, setReleases] = useState<Release[]>([]);
  const [selected, select] = useState('');
  const [review, setReview] = useState<Review | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const scope = { tenant_id: tenant, project_id: project };
  const release = releases.find((row) => row.plugin_id === selected);
  useEffect(() => {
    const controller = new AbortController();
    transport<{ items: Release[] }>(
      packages + '/?' + new URLSearchParams({ tenant_id: tenant, project_id: project }),
      { signal: controller.signal },
    )
      .then((data) => {
        if (!controller.signal.aborted) setReleases(data.items);
      })
      .catch((reason) => {
        if (!controller.signal.aborted) setError(String(reason));
      });
    return () => controller.abort();
  }, [tenant, project, revision]);
  async function perform(action: () => Promise<void>) {
    setBusy(true);
    setError('');
    try {
      await action();
    } catch (cause) {
      setError(String(cause));
    } finally {
      setBusy(false);
    }
  }
  async function choose() {
    setReview(null);
    const file = await openFilesWithDesktopDialog('plugin_package');
    if (file.status === 'cancelled') return;
    if (file.files.length !== 1 || !file.files[0]) throw new Error('signed_archive_required');
    const archive_base64 = await pluginArchiveBase64(file.files[0]);
    const checked = await transport<Omit<Review, 'archive_base64'>>(packages + '/inspect', {
      method: 'POST',
      body: { ...scope, archive_base64 },
    });
    setReview({ ...checked, archive_base64 });
  }
  async function install() {
    if (!review) return;
    await transport(packages + '/install', {
      method: 'POST',
      body: {
        ...scope,
        archive_base64: review.archive_base64,
        approved_permissions: review.permissions,
      },
    });
    select(review.plugin_id);
    setReview(null);
    refresh();
  }
  async function mutate(action: string) {
    if (!release) return;
    await transport(packages + '/' + encodeURIComponent(release.plugin_id) + '/' + action, {
      method: 'POST',
      body: { ...scope, expected_revision: release.desired_revision },
    });
    refresh();
  }
  return (
    <details>
      <summary>{t.packages}</summary>
      <button onClick={refresh}>{t.retry}</button>
      {canManage && (
        <button disabled={busy} onClick={() => void perform(choose)}>
          {t.import}
        </button>
      )}
      {canManage && (
        <NpmPackageSource
          disabled={busy}
          labels={{ name: t.npmName, version: t.exactVersion, preview: t.previewNpm }}
          onChange={() => { setReview(null); setError(''); }}
          onPreview={(name, version) => void perform(async () => {
            setReview(null);
            const candidate = await transport<Review>(packages + '/npm/resolve', {
              method: 'POST', body: { ...scope, package_name: name, version },
            });
            setReview(candidate);
          })}
        />
      )}
      {review && canManage && (
        <section>
          <p>
            {review.plugin_id} · {review.version} · {review.digest}
          </p>
          <p>
            {t.inspect} · {review.permissions.join(', ')}
          </p>
          <button disabled={busy} onClick={() => void perform(install)}>
            {t.install}
          </button>
        </section>
      )}
      <label>
        {t.choose}
        <select value={selected} onChange={(e) => select(e.target.value)}>
          <option value="">{t.choose}</option>
          {releases.map((row) => (
            <option key={row.plugin_id} value={row.plugin_id}>
              {row.plugin_id}
            </option>
          ))}
        </select>
      </label>
      {release && (
        <section>
          <p>
            {release.version} / {release.running_version} · <code>{release.actual_digest}</code>
          </p>
          {release.failure && <p role="alert">{release.failure}</p>}
          {canManage &&
            (['enable', 'disable', 'rollback'] as const).map((action) => (
              <button
                key={action}
                disabled={busy}
                onClick={() => void perform(() => mutate(action))}
              >
                {t[action]}
              </button>
            ))}
          {release.actual_digest && (
            <details>
              <summary>{t.device}</summary>
              <DevicePluginSettings
                key={release.actual_digest}
                pluginId={selected}
                tenant={tenant}
                project={project}
              />
            </details>
          )}
        </section>
      )}
      {error && <p role="alert">{error}</p>}
    </details>
  );
}
