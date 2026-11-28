import { useEffect, useRef, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router-dom';

import { NpmPackageSource } from '../../../../agi-stack/packages/plugin-marketplace-ui/src/NpmPackageSource';

import { ApiError } from '@/services/client/ApiError';
import {
  type OptionalBusinessService,
  type OptionalBusinessPackageFileV2,
  type OptionalBusinessProjectionV2,
  type OptionalBusinessUiV2,
} from '@/services/projectPackageClient';

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
  if (error instanceof ApiError) {
    return {
      ...(error.statusCode === undefined ? {} : { status: error.statusCode }),
      detail: error.message,
    };
  }
  if (typeof error === 'object' && error !== null && 'response' in error) {
    const response = (error as { response?: { status?: number; data?: { detail?: unknown } } })
      .response;
    const detail = response?.data?.detail;
    const message = typeof detail === 'string' ? detail : '';
    if (response?.status === undefined) return { detail: message };
    return { status: response.status, detail: message };
  }
  return { detail: '' };
}

/** Production optional-business controls. The slot receives only API-verified bytes. */
export function OptionalBusinessPanel({
  tenantId,
  projectId,
  service: optionalBusinessService,
  canManage = true,
  canExecute = true,
}: {
  readonly service: OptionalBusinessService;
  readonly canManage?: boolean;
  readonly canExecute?: boolean;
  readonly tenantId: string;
  readonly projectId: string | null;
}) {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const pluginFromQuery = searchParams.get('optionalPlugin') ?? '';
  const [available, setAvailable] = useState<readonly string[]>([]);
  const [revision, setRevision] = useState(0);
  const [pluginId, setPluginId] = useState(pluginFromQuery);
  const [file, setFile] = useState<OptionalBusinessPackageFileV2 | null>(null);
  const [projection, setProjection] = useState<OptionalBusinessProjectionV2 | null>(null);
  const [document, setDocument] = useState<SignedBusinessDocumentV2 | null>(null);
  const [phase, setPhase] = useState<LifecyclePhase>('idle');
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const refreshGeneration = useRef(0);
  const inspection = useRef(0);
  const scopeGeneration = useRef(0);
  const [commandResult, setCommandResult] = useState<string | null>(null);
  useEffect(() => {
    setFile(null);
    setPhase('idle');
    setProgress(0);
    setError(null);
    setCommandResult(null);
    setDocument(null);
    setProjection(null);
    return () => {
      scopeGeneration.current++;
      inspection.current++;
      refreshGeneration.current++;
    };
  }, [tenantId, projectId]);
  const scope = projectId ? { tenantId, projectId } : null;
  const busy = phase !== 'idle';
  const selected =
    projection?.plugin_id === pluginId.trim() && projection.package_recorded ? projection : null;

  useEffect(() => {
    setPluginId(pluginFromQuery);
  }, [pluginFromQuery]);

  useEffect(() => {
    if (!scope || pluginFromQuery.trim() === '') return;
    void refresh(pluginFromQuery);
    // refresh closes over the latest scope; the query and project are the reload key.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pluginFromQuery, projectId, tenantId]);

  useEffect(() => {
    let current = true;
    if (projectId) {
      void optionalBusinessService.list({ projectId, tenantId }).then(
        ({ items }) => {
          if (current) setAvailable(items.map((item) => item.plugin_id));
        },
        () => {
          if (current) setAvailable([]);
        }
      );
    }
    return () => {
      current = false;
    };
  }, [tenantId, projectId, revision, optionalBusinessService]);

  function clearCandidate() {
    inspection.current++;
    setFile(null);
    setError(null);
  }

  async function inspectCandidate(candidate: Promise<OptionalBusinessPackageFileV2>) {
    clearCandidate();
    const current = inspection.current;
    try {
      const verified = await candidate;
      if (current === inspection.current) setFile(verified);
    } catch (caught) {
      if (current === inspection.current) {
        setError(
          responseOf(caught).detail || t('tenant.pluginHub.optionalBusiness.packageInvalid')
        );
      }
    }
  }

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
      setDocument(null);
      setProjection(view);
      setCommandResult(null);
      if (
        view.runtime_phase === 'active' &&
        view.desired_enabled &&
        view.has_web_ui &&
        view.actual_digest
      ) {
        const ui = await optionalBusinessService.ui(nextPluginId.trim(), scope, view.actual_digest);
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
    const started = scopeGeneration.current;
    setPhase(next);
    setProgress(next === 'installing' ? 10 : 100);
    setError(null);
    try {
      await work();
      if (started !== scopeGeneration.current) return;
      if (next === 'installing') {
        setProgress(100);
        setSearchParams((current) => {
          const params = new URLSearchParams(current);
          params.set('optionalPlugin', targetPluginId);
          return params;
        });
      }
      setRevision((value) => value + 1);
      await refresh(targetPluginId);
    } catch (caught) {
      if (started !== scopeGeneration.current) return;
      const response = responseOf(caught);
      if (response.status === 409) await refresh(targetPluginId);
      if (started === scopeGeneration.current)
        setError(response.detail || t('tenant.pluginHub.optionalBusiness.actionFailed'));
    } finally {
      if (started === scopeGeneration.current) {
        setPhase('idle');
        setProgress(0);
      }
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
          list="project-signed-package-ids"
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
      <datalist id="project-signed-package-ids">
        {available.map((id) => (
          <option key={id} value={id} />
        ))}
      </datalist>
      <label>
        {t('tenant.pluginHub.optionalBusiness.packageFile')}
        <input
          data-testid="optional-business-package"
          type="file"
          accept=".mspkg,.zip,application/zip"
          disabled={!canManage || busy || !scope}
          onChange={(event) => {
            const selected = event.target.files?.[0];
            if (selected && scope)
              void inspectCandidate(optionalBusinessService.inspect(selected, scope));
            else clearCandidate();
          }}
        />
      </label>
      <NpmPackageSource
        key={JSON.stringify([tenantId, projectId])}
        disabled={!canManage || busy || !scope}
        labels={{
          name: t('tenant.pluginHub.optionalBusiness.npmName'),
          version: t('tenant.pluginHub.optionalBusiness.exactVersion'),
          preview: t('tenant.pluginHub.optionalBusiness.previewNpm'),
        }}
        onChange={clearCandidate}
        onPreview={(name, version) => {
          if (scope && canManage)
            void inspectCandidate(optionalBusinessService.resolveNpm(scope, name, version));
        }}
      />
      {file && (
        <p>
          {t('tenant.pluginHub.optionalBusiness.approval', {
            plugin: file.plugin_id,
            version: file.version,
            permissions: file.permissions.join(', '),
            digest: file.digest,
          })}
        </p>
      )}
      {file?.requires?.map(({ alias, service, version }) => (
        <p key={alias}>
          {t('tenant.pluginHub.optionalBusiness.requiresService', { alias, service, version })}
        </p>
      ))}
      {file?.provides?.map(({ service, version }) => (
        <p key={service}>
          {t('tenant.pluginHub.optionalBusiness.providesService', { service, version })}
        </p>
      ))}
      {projection?.package_recorded && (
        <p>
          {t('tenant.pluginHub.optionalBusiness.versions', {
            installed: projection.installed_version,
            running: projection.running_version ?? '—',
          })}
        </p>
      )}
      {projection?.kind && (
        <p>
          {t(`tenant.pluginHub.optionalBusiness.kind.${projection.kind}`)}
          {projection.targets?.length ? ` · ${projection.targets.join(', ')}` : ''}
        </p>
      )}
      {projection?.failure && <p role="alert">{projection.failure}</p>}
      <p data-testid="optional-business-phase">
        {projection?.package_recorded
          ? projection.runtime_phase
          : t('tenant.pluginHub.optionalBusiness.absent')}
      </p>
      {busy ? (
        <progress data-testid="optional-business-progress" max={100} value={progress} />
      ) : null}
      {error ? <p role="alert">{error}</p> : null}
      <button
        type="button"
        data-testid="optional-business-install"
        disabled={!canManage || busy || !scope || !file}
        onClick={() => {
          if (!file) return;
          setPluginId(file.plugin_id);
          void run('installing', file.plugin_id, async () => {
            if (!scope) return;
            const generation = scopeGeneration.current;
            await optionalBusinessService.install(scope, file, (value) => {
              if (generation === scopeGeneration.current) setProgress(value);
            });
          });
        }}
      >
        {t('tenant.pluginHub.optionalBusiness.install')}
      </button>
      <button
        type="button"
        data-testid="optional-business-enable"
        disabled={!canManage || busy || !scope || !selected}
        onClick={() => {
          void run('enabling', pluginId.trim(), async () => {
            if (!scope || !selected) return;
            await optionalBusinessService.mutate(
              selected.plugin_id,
              scope,
              'enable',
              selected.desired_revision
            );
          });
        }}
      >
        {t('tenant.pluginHub.optionalBusiness.enable')}
      </button>
      <button
        type="button"
        data-testid="optional-business-disable"
        disabled={!canManage || busy || !scope || !selected}
        onClick={() => {
          void run('disabling', pluginId.trim(), async () => {
            if (!scope || !selected) return;
            await optionalBusinessService.mutate(
              selected.plugin_id,
              scope,
              'disable',
              selected.desired_revision
            );
          });
        }}
      >
        {t('tenant.pluginHub.optionalBusiness.disable')}
      </button>
      <button
        type="button"
        data-testid="optional-business-rollback"
        disabled={!canManage || busy || !scope || !selected}
        onClick={() => {
          void run('rolling-back', pluginId.trim(), async () => {
            if (!scope || !selected) return;
            await optionalBusinessService.mutate(
              selected.plugin_id,
              scope,
              'rollback',
              selected.desired_revision
            );
          });
        }}
      >
        {t('tenant.pluginHub.optionalBusiness.rollback')}
      </button>
      <button
        type="button"
        data-testid="optional-business-uninstall"
        disabled={!canManage || busy || !scope || !selected}
        onClick={() => {
          void run('uninstalling', pluginId.trim(), async () => {
            if (!scope || !selected) return;
            await optionalBusinessService.mutate(
              selected.plugin_id,
              scope,
              'uninstall',
              selected.desired_revision
            );
          });
        }}
      >
        {t('tenant.pluginHub.optionalBusiness.uninstall')}
      </button>
      <SignedBusinessMount
        key={projection?.actual_digest ?? ''}
        document={document}
        onAction={(command, payload) => {
          if (
            !canExecute ||
            !scope ||
            !projection?.actual_digest ||
            !projection.commands?.includes(command)
          )
            return;
          const generation = refreshGeneration.current;
          void optionalBusinessService
            .command(projection.plugin_id, scope, command, projection.actual_digest, payload)
            .then((result) => {
              if (generation === refreshGeneration.current)
                setCommandResult(JSON.stringify(result, null, 2));
            })
            .catch((caught: unknown) => {
              if (generation === refreshGeneration.current)
                setError(
                  responseOf(caught).detail || t('tenant.pluginHub.optionalBusiness.actionFailed')
                );
            });
        }}
      />
      {commandResult && <pre aria-live="polite">{commandResult}</pre>}
    </section>
  );
}
