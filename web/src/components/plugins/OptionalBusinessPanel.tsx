import { useEffect, useRef, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router-dom';

import {
  optionalBusinessService,
  type OptionalBusinessPackageFileV2,
  type OptionalBusinessProjectionV2,
  type OptionalBusinessUiV2,
} from '@/services/optionalBusinessService';

import {
  SignedBusinessMount,
  type SignedBusinessDocumentV2,
} from '@/components/plugins/SignedBusinessMount';

type LifecyclePhase =
  | 'idle'
  | 'installing'
  | 'enabling'
  | 'disabling'
  | 'rolling-back'
  | 'uninstalling';

function signedDocumentFromUiV2(ui: OptionalBusinessUiV2): SignedBusinessDocumentV2 {
  const binary = atob(ui.bytes_base64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return {
    moduleRef: ui.module_ref,
    digest: ui.digest,
    source: ui.source,
    bytes,
  };
}

function responseOf(error: unknown): { status?: number; detail: string } {
  if (typeof error === 'object' && error !== null && 'response' in error) {
    const response = (error as { response?: { status?: number; data?: { detail?: unknown } } })
      .response;
    const detail = response?.data?.detail;
    return { status: response?.status, detail: typeof detail === 'string' ? detail : '' };
  }
  return { detail: '' };
}

/** Production optional-business controls. The slot receives only API-verified bytes. */
export function OptionalBusinessPanel({
  tenantId,
  projectId,
}: {
  readonly tenantId: string;
  readonly projectId: string | null;
}) {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const pluginFromQuery = searchParams.get('optionalPlugin') ?? '';
  const [pluginId, setPluginId] = useState(pluginFromQuery);
  const [file, setFile] = useState<OptionalBusinessPackageFileV2 | null>(null);
  const [projection, setProjection] = useState<OptionalBusinessProjectionV2 | null>(null);
  const [document, setDocument] = useState<SignedBusinessDocumentV2 | null>(null);
  const [phase, setPhase] = useState<LifecyclePhase>('idle');
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const refreshGeneration = useRef(0);
  const scope = projectId ? { tenantId, projectId } : null;
  const busy = phase !== 'idle';

  useEffect(() => {
    setPluginId(pluginFromQuery);
  }, [pluginFromQuery]);

  useEffect(() => {
    if (!scope || pluginFromQuery.trim() === '') return;
    void refresh(pluginFromQuery);
    // refresh closes over the latest scope; the query and project are the reload key.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pluginFromQuery, projectId, tenantId]);

  async function refresh(nextPluginId: string) {
    const generation = ++refreshGeneration.current;
    if (!scope || nextPluginId.trim() === '') {
      setProjection(null);
      setDocument(null);
      return;
    }
    try {
      const view = await optionalBusinessService.projection(nextPluginId.trim(), scope);
      if (generation !== refreshGeneration.current) return;
      setProjection(view);
      if (view.runtime_phase === 'active' && view.desired_enabled) {
        const ui = await optionalBusinessService.ui(nextPluginId.trim(), scope);
        if (generation !== refreshGeneration.current) return;
        setDocument(signedDocumentFromUiV2(ui));
      } else {
        setDocument(null);
      }
      setError(null);
    } catch (caught) {
      if (generation !== refreshGeneration.current) return;
      setProjection(null);
      setDocument(null);
      const response = responseOf(caught);
      setError(
        response.status === 404
          ? null
          : response.detail || t('tenant.pluginHub.optionalBusiness.loadFailed')
      );
    }
  }

  async function run(next: LifecyclePhase, targetPluginId: string, work: () => Promise<void>) {
    if (!scope || targetPluginId.trim() === '') return;
    setPhase(next);
    setProgress(next === 'installing' ? 10 : 100);
    setError(null);
    try {
      await work();
      if (next === 'installing') {
        setProgress(100);
        setSearchParams((current) => {
          const params = new URLSearchParams(current);
          params.set('optionalPlugin', targetPluginId);
          return params;
        });
      }
      await refresh(targetPluginId);
    } catch (caught) {
      setError(responseOf(caught).detail || t('tenant.pluginHub.optionalBusiness.actionFailed'));
    } finally {
      setPhase('idle');
      setProgress(0);
    }
  }

  return (
    <section
      data-testid="optional-business-panel"
      data-project={projectId ?? ''}
      data-package-ready={file ? 'yes' : 'no'}
    >
      <h2>{t('tenant.pluginHub.optionalBusiness.title')}</h2>
      <label>
        {t('tenant.pluginHub.optionalBusiness.pluginId')}
        <input
          data-testid="optional-business-plugin-id"
          value={pluginId}
          onChange={(event) => {
            setPluginId(event.target.value);
          }}
          onBlur={(event) => {
            const value = event.target.value.trim();
            if (value) void refresh(value);
          }}
        />
      </label>
      <label>
        {t('tenant.pluginHub.optionalBusiness.packageFile')}
        <input
          data-testid="optional-business-package"
          type="file"
          accept="application/json"
          onChange={(event) => {
            const selected = event.target.files?.[0];
            if (!selected) {
              setFile(null);
              return;
            }
            void selected.text().then((text) => {
              try {
                setFile(JSON.parse(text) as OptionalBusinessPackageFileV2);
                setError(null);
              } catch {
                setFile(null);
                setError(t('tenant.pluginHub.optionalBusiness.packageInvalid'));
              }
            });
          }}
        />
      </label>
      <p data-testid="optional-business-phase">
        {projection?.runtime_phase ?? t('tenant.pluginHub.optionalBusiness.absent')}
      </p>
      {busy ? (
        <progress data-testid="optional-business-progress" max={100} value={progress} />
      ) : null}
      {error ? <p role="alert">{error}</p> : null}
      <button
        type="button"
        data-testid="optional-business-install"
        disabled={busy || !scope || !file}
        onClick={() => {
          if (!file) return;
          setPluginId(file.plugin_id);
          void run('installing', file.plugin_id, async () => {
            if (!scope) return;
            await optionalBusinessService.install(scope, file, setProgress);
          });
        }}
      >
        {t('tenant.pluginHub.optionalBusiness.install')}
      </button>
      <button
        type="button"
        data-testid="optional-business-enable"
        disabled={busy || !scope || pluginId.trim() === ''}
        onClick={() => {
          void run('enabling', pluginId.trim(), async () => {
            if (!scope) return;
            await optionalBusinessService.enable(pluginId.trim(), scope);
          });
        }}
      >
        {t('tenant.pluginHub.optionalBusiness.enable')}
      </button>
      <button
        type="button"
        data-testid="optional-business-disable"
        disabled={busy || !scope || pluginId.trim() === ''}
        onClick={() => {
          void run('disabling', pluginId.trim(), async () => {
            if (!scope) return;
            await optionalBusinessService.disable(pluginId.trim(), scope);
          });
        }}
      >
        {t('tenant.pluginHub.optionalBusiness.disable')}
      </button>
      <button
        type="button"
        data-testid="optional-business-rollback"
        disabled={busy || !scope || pluginId.trim() === ''}
        onClick={() => {
          void run('rolling-back', pluginId.trim(), async () => {
            if (!scope) return;
            await optionalBusinessService.rollback(pluginId.trim(), scope);
          });
        }}
      >
        {t('tenant.pluginHub.optionalBusiness.rollback')}
      </button>
      <button
        type="button"
        data-testid="optional-business-uninstall"
        disabled={busy || !scope || pluginId.trim() === ''}
        onClick={() => {
          void run('uninstalling', pluginId.trim(), async () => {
            if (!scope) return;
            await optionalBusinessService.uninstall(pluginId.trim(), scope);
          });
        }}
      >
        {t('tenant.pluginHub.optionalBusiness.uninstall')}
      </button>
      <SignedBusinessMount document={document} />
    </section>
  );
}
