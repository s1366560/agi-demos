import { useEffect, useRef, useState } from 'react';
import {
  RichPackagePages as PageHost,
  type RichPackagePagesProps,
} from '../../../../packages/plugin-marketplace-ui/src/RichPackagePages';
import type { MarketDetail } from '../../../../packages/plugin-marketplace-ui/src/pluginMarketTypes';
import { DevicePluginSettings } from '../features/settings/DevicePluginSettings';
import { saveBlobWithDesktopDialog } from '../features/runtime/nativeFileBridge';
import { packages, transport } from './transport';

type Review = { plugin: string; digest: string; signal: AbortSignal; finish(): void };

export function RichPackagePages(props: RichPackagePagesProps) {
  const [active, setActive] = useState<Review | null>(null);
  const current = useRef<Review | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const { tenantId, projectId } = props.scope;
  useEffect(() => {
    if (active) dialog.current?.showModal();
  }, [active]);
  useEffect(() => () => current.current?.finish(), [tenantId, projectId, props.pathname]);
  function reviewDevice(plugin: string, digest: string, signal: AbortSignal) {
    signal.throwIfAborted();
    if (!projectId || current.current) throw new Error('device_review_unavailable');
    return new Promise<void>((resolve, reject) => {
      const finish = () => {
        signal.removeEventListener('abort', finish);
        current.current = null;
        setActive(null);
        if (signal.aborted) reject(signal.reason);
        else resolve();
      };
      current.current = { plugin, digest, signal, finish };
      signal.addEventListener('abort', finish, { once: true });
      setActive(current.current);
    });
  }
  const zh = (props.locale ?? navigator.language).startsWith('zh');
  async function loadArchive(review: Review) {
    if (!projectId) throw new Error('device_project_required');
    const scope = { tenant_id: tenantId, project_id: projectId };
    const detail = await transport<MarketDetail>(
      packages + '/npm/detail?' + new URLSearchParams({ ...scope, plugin_id: review.plugin }),
      { signal: review.signal },
    );
    if (
      detail.installation?.actual_digest !== review.digest ||
      !detail.package_name ||
      !detail.installation.running_version
    )
      throw new Error('device_plugin_release_changed');
    const result = await transport<{ archive_base64: string; digest: string }>(
      packages + '/npm/resolve',
      {
        method: 'POST',
        signal: review.signal,
        body: {
          ...scope,
          package_name: detail.package_name,
          version: detail.installation.running_version,
        },
      },
    );
    if (result.digest !== review.digest) throw new Error('device_plugin_release_changed');
    return result.archive_base64;
  }
  return (
    <>
      <PageHost {...props} reviewDevice={reviewDevice}
        saveNativeExport={blob => saveBlobWithDesktopDialog({
          blob, suggestedName: 'export.csv', mimeType: 'text/csv',
        })} />
      {active && projectId && (
        <dialog
          ref={dialog}
          onCancel={active.finish}
          aria-label={zh ? '设备授权' : 'Device approval'}
          style={{ maxWidth: 'min(42rem, 96vw)', maxHeight: '90vh', overflow: 'auto' }}
        >
          <button type="button" autoFocus onClick={active.finish}>
            {zh ? '关闭' : 'Close'}
          </button>
          <DevicePluginSettings
            tenant={tenantId}
            project={projectId}
            pluginId={active.plugin}
            digest={active.digest}
            loadArchive={() => loadArchive(active)}
          />
        </dialog>
      )}
    </>
  );
}
