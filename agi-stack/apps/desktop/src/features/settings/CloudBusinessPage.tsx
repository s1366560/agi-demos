import { useEffect, useRef, useState } from 'react';
import type {
  MarketplaceClient,
  MarketplaceInstallation,
} from '../../../../../packages/plugin-marketplace-ui/src/client';
import type { SignedSlotResourceV2 } from '@agistack/plugin-slots';
import { DesktopSignedBusinessMount } from '../../plugins/DesktopSignedBusinessMount';

export function CloudBusinessPage({
  client,
  item,
  digest,
  label,
  canExecute = true,
}: {
  client: MarketplaceClient;
  item: Pick<MarketplaceInstallation, 'plugin_id' | 'commands'>;
  digest: string;
  label: string;
  canExecute?: boolean;
}) {
  const [resource, setResource] = useState<Omit<SignedSlotResourceV2, 'target'> | null>(null);
  const [result, setResult] = useState('');
  const [busy, setBusy] = useState(false);
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), [client, digest]);

  async function run(action?: string, payload?: Record<string, unknown>) {
    if (busy || (action !== undefined && (!canExecute || !item.commands?.includes(action)))) return;
    const controller = new AbortController();
    request.current?.abort();
    request.current = controller;
    setBusy(true);
    try {
      if (action !== undefined) {
        const value = await client.businessCommand(
          item.plugin_id,
          digest,
          action,
          controller.signal,
          payload,
        );
        if (!controller.signal.aborted) setResult(JSON.stringify(value, null, 2));
      } else {
        const value = await client.businessPage(item.plugin_id, digest, controller.signal);
        if (!controller.signal.aborted)
          setResource({
            moduleRef: value.module_ref,
            digest: value.digest,
            source: value.source,
            bytes: Uint8Array.from(atob(value.bytes_base64), (c) => c.charCodeAt(0)),
          });
      }
    } catch (error) {
      if (!controller.signal.aborted)
        setResult(error instanceof Error ? error.message : String(error));
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  return (
    <>
      {!resource && (
        <button type="button" disabled={busy} onClick={() => void run()}>
          {label}
        </button>
      )}
      <DesktopSignedBusinessMount resource={resource} onAction={(id, input) => void run(id, input)} />
      {result && <pre aria-live="polite">{result}</pre>}
    </>
  );
}
