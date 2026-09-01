import { useMemo } from 'react';

import type { DesktopRuntimeConfig } from '../types';
import { resolveDesktopRendererAuthorityStateV2 } from './desktopRendererAuthorityProjectionV2';
import type { DesktopRendererCompositionPortV2 } from './desktopRendererCompositionPortV2';
import {
  DESKTOP_RENDERER_TARGET_V2,
  type DesktopRendererGenerationActionsV2,
  type DesktopRendererGenerationContextValueV2,
  type DesktopRendererOperationLeaseV2,
} from './desktopRendererGenerationContextV2';
import {
  projectDesktopNavigationRegistryV2,
  projectDesktopRouteRegistryV2,
} from './desktopRendererAuthorityStateV2';
import {
  acquireDesktopRendererServiceOperationLeaseV2,
  type DesktopRendererServiceOperationLeaseRequestV2,
} from './desktopRendererServiceOperationLeaseV2';
import {
  acquireDesktopPluginGenerationLeaseV2,
  useDesktopPluginGenerationV2,
} from './useDesktopPluginGenerationV2';

const AUTHENTICATION_KERNEL_OPERATION_LEASE_V2: DesktopRendererOperationLeaseV2 = Object.freeze({
  digest: undefined,
  kind: 'authentication-kernel',
  release: async () => undefined,
});

export {
  DesktopRendererGenerationProviderV2,
  useDesktopRendererGenerationV2,
} from './desktopRendererGenerationContextV2';
export type {
  DesktopRendererGenerationContextValueV2,
  DesktopRendererGenerationMetaV2,
  DesktopRendererGenerationProviderV2Props,
  DesktopRendererGenerationStateV2,
} from './desktopRendererGenerationContextV2';

export function useDesktopRendererGenerationHostV2(
  config: DesktopRuntimeConfig,
  enabled: boolean,
  composition: DesktopRendererCompositionPortV2,
): DesktopRendererGenerationContextValueV2 {
  const generationState = useDesktopPluginGenerationV2(config, enabled);
  const generation = generationState.generation;
  const generationDigest = generation?.snapshot.digest;
  const generationError = generationState.error;
  const generationStatus = generationState.status;

  return useMemo(() => {
    const authority = resolveDesktopRendererAuthorityStateV2(generationState, enabled);
    const routeRegistry = projectDesktopRouteRegistryV2(composition, authority);
    const navigationRegistry = projectDesktopNavigationRegistryV2(routeRegistry, authority);
    const acquireServiceOperationLease = <TService,>(
      request: DesktopRendererServiceOperationLeaseRequestV2,
    ) =>
      acquireDesktopRendererServiceOperationLeaseV2<TService>(
        generation,
        request,
        acquireDesktopPluginGenerationLeaseV2,
      );
    const actions: DesktopRendererGenerationActionsV2 = Object.freeze({
      acquireOperationLease: () => {
        if (generation === undefined) return AUTHENTICATION_KERNEL_OPERATION_LEASE_V2;
        const lease = acquireDesktopPluginGenerationLeaseV2(generation);
        return Object.freeze({
          digest: generation.snapshot.digest,
          kind: 'generation' as const,
          release: () => lease.release(),
        });
      },
      acquireServiceOperationLease,
    });
    return Object.freeze({
      actions,
      composition,
      meta: Object.freeze({
        digest: generationDigest,
        error: generationError,
        status: generationStatus,
        target: DESKTOP_RENDERER_TARGET_V2,
      }),
      state: Object.freeze({ authority, navigationRegistry, routeRegistry }),
    });
  }, [
    composition,
    enabled,
    generation,
    generationDigest,
    generationError,
    generationState,
    generationStatus,
  ]);
}
