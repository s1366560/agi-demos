import { Suspense, useEffect, useState, useSyncExternalStore } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { useTenantStore } from '@/stores/tenant';

import { projectAPI } from '@/services/api';

import { businessLocation } from '@/projectPackages/businessLocation';
import { useWebPackageSession } from '@/projectPackages/useWebPackageSession';
import { WebProjectMarket } from '@/projectPackages/WebProjectMarket';
import { getAuthToken, subscribeCloudIdentity } from '@/utils/tokenResolver';

import { RichPackagePages } from '../../../../agi-stack/packages/plugin-marketplace-ui/src/RichPackagePages';

import type { Project } from '@/types/memory';

export function PluginHubView({
  integrationSettings,
  onChanged,
}: {
  integrationSettings: React.ReactNode;
  onChanged?: () => void;
}) {
  const { t, i18n } = useTranslation();
  const { tenantId: routeTenant } = useParams();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const tenant = useTenantStore((state) => state.currentTenant);
  const tenantId = routeTenant || tenant?.id;
  const token = useSyncExternalStore(subscribeCloudIdentity, getAuthToken);
  const session = useWebPackageSession(token);
  const [listing, setListing] = useState<{
    tenantId: string;
    token: string;
    projects: Project[];
    error?: string;
  } | null>(null);
  const [reload, retry] = useState(0);
  useEffect(() => {
    if (!tenantId || !token) return;
    let active = true;
    const scope = { tenantId, token };
    async function loadProjects() {
      const all: Project[] = [];
      let page = 1;
      while (active) {
        const result = await projectAPI.list(scope.tenantId, { page, page_size: 100 });
        all.push(...result.projects);
        if (!result.projects.length || all.length >= result.total) break;
        page++;
      }
      if (active) setListing({ ...scope, projects: all });
    }
    void loadProjects().catch((cause: unknown) => {
      if (active)
        setListing({
          ...scope,
          projects: [],
          error: cause instanceof Error ? cause.message : t('common.error'),
        });
    });
    return () => {
      active = false;
    };
  }, [tenantId, token, reload, t]);
  const scopedListing =
    listing && listing.tenantId === tenantId && listing.token === token ? listing : null;
  const error = scopedListing?.error;
  const options = (scopedListing?.projects ?? []).filter((p) => p.tenant_id === tenantId);
  const requested = params.get('projectId');
  const selected = options.find((project) => project.id === requested);
  const projectId = selected?.id ?? null;
  const settings = params.get('settings') === 'integrations';
  const businessPage = params.get('marketPage');

  function change(values: Record<string, string | null>) {
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        for (const [key, value] of Object.entries(values)) {
          if (value === null) next.delete(key);
          else next.set(key, value);
        }
        return next;
      },
      { preventScrollReset: true }
    );
  }

  return (
    <div className="mx-auto w-full max-w-screen-xl p-4 md:p-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        {!settings && (
          <label className="flex flex-wrap items-center gap-2">
            {t('tenant.pluginHub.installationScope')}
            <select
              className="rounded border px-2 py-1"
              value={selected?.id ?? ''}
              onChange={(e) => {
                change({
                  projectId: e.target.value || null,
                  marketPage: null,
                  marketPlugin: null,
                  optionalPlugin: null,
                  returnTo: null,
                });
              }}
            >
              <option value="">{t('tenant.pluginHub.tenantScope')}</option>
              {options.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
        )}
        <button
          type="button"
          className="rounded border px-3 py-1"
          onClick={() => {
            if (businessPage || settings) change({ marketPage: null, settings: null });
            else change({ settings: 'integrations', marketPlugin: null });
          }}
        >
          {t(
            settings || businessPage
              ? 'tenant.pluginHub.backToMarket'
              : 'tenant.pluginHub.integrationSettings'
          )}
        </button>
      </div>
      {settings ? (
        <Suspense fallback={<p role="status">{t('common.loading')}</p>}>
          {integrationSettings}
        </Suspense>
      ) : error && requested ? (
        <p role="alert">
          {error}{' '}
          <button
            type="button"
            onClick={() => {
              retry((n) => n + 1);
            }}
          >
            {t('common.retry')}
          </button>
        </p>
      ) : tenantId && (!requested || selected) ? (
        businessPage ? (
          <RichPackagePages
            key={JSON.stringify([tenantId, projectId])}
            scope={{ tenantId, projectId }}
            target="web"
            locale={i18n.language}
            // Reviewing a release keeps its digests and load errors in view.
            diagnostics
            pathname={businessPage}
            navigate={(path) => {
              change({ marketPage: path });
            }}
            transport={session.transport}
            openVoiceSocket={session.openVoiceSocket}
        streamCommand={session.stream}
          />
        ) : (
          <WebProjectMarket
            key={JSON.stringify([tenantId, projectId])}
            tenantId={tenantId}
            projectId={projectId}
            transport={session.transport}
            scopeParams={projectId ? { projectId } : {}}
            {...(onChanged ? { onChanged } : {})}
            onOpen={(path) => {
              const plugin = params.get('marketPlugin') ?? params.get('optionalPlugin');
              if (plugin)
                void navigate(businessLocation(path, tenantId, projectId, plugin), {
                  state: { fromPackageMarket: true },
                });
            }}
          />
        )
      ) : (
        <p role="status">{t('tenant.pluginHub.selectProjectPlaceholder')}</p>
      )}
    </div>
  );
}
