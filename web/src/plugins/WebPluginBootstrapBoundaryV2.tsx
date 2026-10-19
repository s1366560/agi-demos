import { useState } from 'react';

import { useTranslation } from 'react-i18next';

import { PluginInstancesV2 } from '../components/plugins/PluginInstancesV2';
import { WebRoutePageLoaderV2 } from '../routes/v2/WebRoutePageLoaderV2';
import { useAuthStore } from '../stores/auth';
import { useProjectStore } from '../stores/project';
import { useTenantStore } from '../stores/tenant';

import { useCurrentWebPluginGenerationStateV2 } from './WebPluginGenerationHostV2';
import { refreshWebPluginGenerationV2 } from './webPluginGenerationV2';

/** Recovery belongs to the kernel so a rejected feature view cannot hide it. */
export function WebPluginBootstrapBoundaryV2({
  unavailable = false,
}: {
  readonly unavailable?: boolean;
}) {
  const { t } = useTranslation();
  const renderer = useCurrentWebPluginGenerationStateV2();
  const tenant = useTenantStore((state) => state.currentTenant);
  const project = useProjectStore((state) => state.currentProject);
  const user = useAuthStore((state) => state.user);
  const [busy, setBusy] = useState(false);
  const [showConfiguration, setShowConfiguration] = useState(false);
  const failed = unavailable || renderer?.status === 'error' || renderer?.status === 'empty';
  if (!failed && !showConfiguration) return <WebRoutePageLoaderV2 />;

  const retry = async () => {
    setBusy(true);
    try {
      await refreshWebPluginGenerationV2();
    } catch {
      // The generation status retains the failure; keep the recovery controls available.
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="mx-auto max-w-5xl space-y-6 p-6">
      <section role="alert" className="space-y-3 rounded-lg border p-5">
        <h1 className="text-lg font-semibold">{t('plugins.bootstrapFailed')}</h1>
        <p>{t('plugins.bootstrapFailedDescription')}</p>
        <div className="flex gap-3">
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              void retry();
            }}
          >
            {t('common.retry')}
          </button>
          {tenant ? (
            <button
              type="button"
              onClick={() => {
                setShowConfiguration(true);
              }}
            >
              {t('plugins.openConfiguration')}
            </button>
          ) : null}
        </div>
      </section>
      {showConfiguration && tenant ? (
        <PluginInstancesV2
          tenantId={tenant.id}
          projectId={project?.tenant_id === tenant.id ? project.id : null}
          canManage={Boolean(user)}
        />
      ) : null}
    </main>
  );
}
