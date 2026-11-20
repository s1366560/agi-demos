import { act, renderHook, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';

import { DesktopApiClient } from '../../../../agi-stack/apps/desktop/src/api/client';
import { initialDesktopRuntimeConfig } from '../../../../agi-stack/apps/desktop/src/features/auth/loginRuntimeModel';
import {
  acquireDesktopPluginGenerationLeaseV2,
  activateDesktopPluginGenerationRootV2,
  deactivateDesktopPluginGenerationRootV2,
  useDesktopPluginGenerationV2,
} from '../../../../agi-stack/apps/desktop/src/plugins/useDesktopPluginGenerationV2';
import { acquireDesktopRendererServiceOperationLeaseV2 } from '../../../../agi-stack/apps/desktop/src/plugins/desktopRendererServiceOperationLeaseV2';
import {
  DESKTOP_WORKSPACE_CATALOG_AUTHORITY_SERVICE_V2,
  type DesktopWorkspaceCatalogAuthorityServiceV2,
} from '../../../../agi-stack/apps/desktop/src/plugins/desktopWorkspaceCatalogAuthorityModuleV2';
import bootstrapProfile from '../../../../shared/profiles/memstack-default-bootstrap.v2.json';

// Desktop and Web install React separately; use the test renderer's real React dispatcher.
vi.mock('../../../../agi-stack/apps/desktop/node_modules/react', async () => import('react'));

it('admits a real workspace service lease only after the complete native baseline is ready', async () => {
  let deliver!: (value: unknown) => void;
  const pendingDistribution = new Promise<unknown>((resolve) => {
    deliver = resolve;
  });
  const view = vi
    .spyOn(DesktopApiClient.prototype, 'localRendererViewV2')
    .mockImplementation(() => new Promise(() => undefined));
  const invoke = vi.fn((command: string) => {
    if (command === 'platform_plugin_renderer_owner_retire_v2') return Promise.resolve();
    if (command === 'platform_plugin_renderer_delivery_current_v2') return pendingDistribution;
    if (command === 'platform_plugin_renderer_receipt_submit_v2') return Promise.resolve();
    throw new Error(`unexpected_desktop_command:${command}`);
  });
  const originalBridge = Object.getOwnPropertyDescriptor(window, '__MEMSTACK_DESKTOP__');
  Object.defineProperty(window, '__MEMSTACK_DESKTOP__', {
    configurable: true,
    value: { runtime: 'electron', core: { invoke } },
  });
  const config = initialDesktopRuntimeConfig();
  activateDesktopPluginGenerationRootV2();
  const hook = renderHook(({ enabled }) => useDesktopPluginGenerationV2(config, enabled), {
    initialProps: { enabled: false },
  });
  const request = {
    service: DESKTOP_WORKSPACE_CATALOG_AUTHORITY_SERVICE_V2,
    scope: { kind: 'root' as const },
    version: '1.0.0',
  };
  try {
    expect(hook.result.current.status).toBe('empty');
    expect(invoke).not.toHaveBeenCalled();
    expect(view).not.toHaveBeenCalled();
    hook.rerender({ enabled: true });
    await waitFor(() =>
      expect(invoke).toHaveBeenCalledWith('platform_plugin_renderer_delivery_current_v2')
    );
    expect(view).not.toHaveBeenCalled();
    expect(hook.result.current.status).toBe('loading');
    await expect(
      acquireDesktopRendererServiceOperationLeaseV2(
        hook.result.current.generation,
        request,
        acquireDesktopPluginGenerationLeaseV2
      )
    ).resolves.toEqual({
      status: 'rejected',
      reasonCode: 'desktop_renderer_service_generation_required',
    });

    // Use the entire generated production baseline and the hook's entire definition catalog.
    await act(async () => {
      deliver(cloudRendererDelivery(bootstrapProfile));
    });
    await waitFor(() => expect(hook.result.current.status).toBe('ready'));
    expect(invoke).toHaveBeenCalledWith(
      'platform_plugin_renderer_receipt_submit_v2',
      expect.objectContaining({
        delivery_token: 'delivery-1',
        receipt: expect.objectContaining({ status: 'ack' }),
      })
    );
    expect(view).not.toHaveBeenCalled();
    const generation = hook.result.current.generation;
    expect(generation?.snapshot.digest).toBe(bootstrapProfile.digest);
    expect(generation?.snapshot.entries).toHaveLength(bootstrapProfile.entries.length);
    expect(
      generation?.fibers.some(
        ({ entry }) => entry.module_ref === 'builtin://memstack/desktop/workspace-catalog-authority'
      )
    ).toBe(true);
    const admission =
      await acquireDesktopRendererServiceOperationLeaseV2<DesktopWorkspaceCatalogAuthorityServiceV2>(
        generation,
        request,
        acquireDesktopPluginGenerationLeaseV2
      );
    expect(admission.status).toBe('accepted');
    if (admission.status !== 'accepted') throw new Error(admission.reasonCode);
    try {
      expect(admission.digest).toBe(bootstrapProfile.digest);
      admission.useService((service) => {
        expect(typeof service.bindOperation).toBe('function');
        expect(typeof service.bindOperation(config).listWorkspacesForProject).toBe('function');
      });
    } finally {
      await admission.release();
    }
  } finally {
    deliver(cloudRendererDelivery(bootstrapProfile));
    hook.unmount();
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
      await deactivateDesktopPluginGenerationRootV2();
    });
    if (originalBridge) Object.defineProperty(window, '__MEMSTACK_DESKTOP__', originalBridge);
    else Reflect.deleteProperty(window, '__MEMSTACK_DESKTOP__');
    view.mockRestore();
  }
});

function cloudRendererDelivery(profile: typeof bootstrapProfile) {
  return {
    source: 'cloud' as const,
    authority_id: 'authority-1',
    delivery_token: 'delivery-1',
    distribution: {
      schema_version: 2 as const,
      descriptor: {
        profile_id: profile.profile_id,
        generation: profile.generation,
        digest: profile.digest,
      },
      snapshot: structuredClone(profile),
      envelope: {
        version: 1,
        nonce: 'nonce-1',
        snapshot_digest: profile.digest,
        type_url: 'types.memstack.ai/plugin.profile.v2',
      },
    },
  };
}
