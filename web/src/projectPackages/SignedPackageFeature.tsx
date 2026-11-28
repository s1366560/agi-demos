import { useEffect, useRef, useState } from 'react';

import { useTranslation } from 'react-i18next';

import type { OptionalBusinessUiV2 } from '@/services/projectPackageClient';

import {
  SignedBusinessMount,
  type SignedBusinessDocumentV2,
} from '@/components/plugins/SignedBusinessMount';

import {
  packageBase,
  packageScope,
  type Installation,
} from '../../../agi-stack/packages/plugin-marketplace-ui/src/pluginMarketTypes';

import type { MarketplaceTransport } from '../../../agi-stack/packages/plugin-marketplace-ui/src/client';

/** Render and invoke the declarative UI belonging to the actual running release. */
export function SignedPackageFeature({
  installation,
  canExecute,
  transport,
  tenantId,
  projectId,
}: {
  installation: Installation;
  canExecute: boolean;
  transport: MarketplaceTransport;
  tenantId: string;
  projectId: string | null;
}) {
  const { t } = useTranslation();
  const [document, setDocument] = useState<SignedBusinessDocumentV2 | null>(null);
  const [result, setResult] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const command = useRef<AbortController | null>(null);
  const digest = installation.actual_digest;
  const base = packageBase(projectId) + '/' + encodeURIComponent(installation.plugin_id);
  useEffect(() => {
    if (!digest) return;
    const controller = new AbortController();
    const query = new URLSearchParams({
      ...packageScope(tenantId, projectId),
      expected_digest: digest,
      target: 'web',
    });
    void transport<OptionalBusinessUiV2>(base + '/ui?' + query.toString(), { signal: controller.signal })
      .then((resource) => {
        if (!controller.signal.aborted)
          setDocument({
            moduleRef: resource.module_ref,
            digest: resource.digest,
            source: resource.source,
            bytes: Uint8Array.from(atob(resource.bytes_base64), (c) => c.charCodeAt(0)),
          });
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) setError(String(cause));
      });
    return () => {
      controller.abort();
      command.current?.abort();
    };
  }, [base, digest, transport, tenantId, projectId]);

  async function invoke(id: string, payload?: Record<string, unknown>) {
    if (!canExecute || !digest || command.current || !installation.commands?.includes(id)) return;
    const controller = new AbortController();
    command.current = controller;
    setBusy(true);
    setError('');
    try {
      const value = await transport(base + '/commands', {
        method: 'POST',
        signal: controller.signal,
        body: {
          ...packageScope(tenantId, projectId),
          expected_digest: digest,
          command_id: id,
          ...(payload === undefined ? {} : { payload }),
        },
      });
      if (!controller.signal.aborted) setResult(JSON.stringify(value, null, 2));
    } catch (cause) {
      if (!controller.signal.aborted) setError(String(cause));
    } finally {
      if (!controller.signal.aborted) setBusy(false);
      command.current = null;
    }
  }

  return (
    <section className="pm-slot" aria-busy={busy}>
      <div inert={!canExecute || busy}>
        <SignedBusinessMount
          document={document}
          onAction={(id, payload) => void invoke(id, payload)}
        />
      </div>
      {busy && <p role="status">{t('common.loading')}</p>}
      {result && <pre aria-live="polite">{result}</pre>}
      {error && (
        <p role="alert" className="pm-error">
          {error}
        </p>
      )}
    </section>
  );
}
