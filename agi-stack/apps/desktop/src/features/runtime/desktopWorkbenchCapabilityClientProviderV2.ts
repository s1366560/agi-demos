import type { DesktopRuntimeConfig } from '../../types';
import type { DesktopWorkbenchSnapshotOperationsV2 } from '../../plugins/desktopWorkbenchSnapshotAuthorityModuleV2';
import type { DesktopWorkbenchCapabilityClient } from './workbenchCapabilityClient';

export type DesktopWorkbenchCapabilityClientProviderReasonCodeV2 =
  'desktop_workbench_capability_client_unpublished';

export class DesktopWorkbenchCapabilityClientProviderErrorV2 extends Error {
  readonly reasonCode: DesktopWorkbenchCapabilityClientProviderReasonCodeV2;

  constructor(
    reasonCode: DesktopWorkbenchCapabilityClientProviderReasonCodeV2,
  ) {
    super(reasonCode);
    this.name = 'DesktopWorkbenchCapabilityClientProviderErrorV2';
    this.reasonCode = reasonCode;
  }
}

export type DesktopWorkbenchCapabilityClientProviderInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  snapshotOperationsV2: DesktopWorkbenchSnapshotOperationsV2;
}>;

export type DesktopWorkbenchCapabilityClientBindingV2 = Readonly<{
  client: DesktopWorkbenchCapabilityClient;
}>;

export type DesktopWorkbenchCapabilityClientProviderV2 = Readonly<{
  publish: (
    input: DesktopWorkbenchCapabilityClientProviderInputV2,
  ) => DesktopWorkbenchCapabilityClientBindingV2;
  resolve: () => DesktopWorkbenchCapabilityClientBindingV2;
}>;

export function createDesktopWorkbenchCapabilityClientProviderV2(): DesktopWorkbenchCapabilityClientProviderV2 {
  let publication: DesktopWorkbenchCapabilityClientBindingV2 | null = null;

  return Object.freeze({
    publish(input) {
      const next = createDesktopWorkbenchCapabilityClientBindingV2(input);
      publication = next;
      return next;
    },
    resolve() {
      if (publication === null) {
        throw new DesktopWorkbenchCapabilityClientProviderErrorV2(
          'desktop_workbench_capability_client_unpublished',
        );
      }
      return publication;
    },
  });
}

function createDesktopWorkbenchCapabilityClientBindingV2(
  input: DesktopWorkbenchCapabilityClientProviderInputV2,
): DesktopWorkbenchCapabilityClientBindingV2 {
  const config = Object.freeze({ ...input.config });
  const operations = input.snapshotOperationsV2;
  if (!operations || typeof operations.loadSnapshot !== 'function') {
    throw new TypeError('desktop_workbench_snapshot_operations_required');
  }
  const client: DesktopWorkbenchCapabilityClient = Object.freeze({
    loadSnapshot(signal?: AbortSignal) {
      return operations.loadSnapshot({ config, signal: signal ?? new AbortController().signal });
    },
  });
  return Object.freeze({ client });
}
