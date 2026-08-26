import { createContext, use, useMemo, type ReactNode } from 'react';

import type { RendererPluginGenerationStateV2 } from '@agistack/plugin-runtime';

import type { AppRouteRegistryRefs } from '../features/navigation/appRouteRegistry';
import type { DesktopRouteModule } from '../features/navigation/desktopRouteModule';
import type { DesktopRouteRegistry } from '../features/navigation/desktopRouteRegistry';
import type { DesktopRuntimeConfig } from '../types';
import { resolveDesktopRendererAuthorityStateV2 } from './desktopRendererAuthorityProjectionV2';
import {
  DesktopRendererAuthorityContextV2,
  projectDesktopNavigationRegistryV2,
  projectDesktopRouteRegistryV2,
  type DesktopRendererAuthorityStateV2,
} from './desktopRendererAuthorityStateV2';
import {
  acquireDesktopPluginGenerationLeaseV2,
  useDesktopPluginGenerationV2,
} from './useDesktopPluginGenerationV2';

const DESKTOP_RENDERER_TARGET_V2 = 'desktop-renderer' as const;

export interface DesktopRendererGenerationStateV2 {
  readonly authority: DesktopRendererAuthorityStateV2;
  readonly navigationRegistry: DesktopRouteRegistry<DesktopRouteModule>;
  readonly routeRegistry: DesktopRouteRegistry<DesktopRouteModule>;
}

export interface DesktopRendererGenerationMetaV2 {
  readonly digest: string | undefined;
  readonly error: unknown | undefined;
  readonly status: RendererPluginGenerationStateV2['status'];
  readonly target: typeof DESKTOP_RENDERER_TARGET_V2;
}

export interface DesktopRendererOperationLeaseV2 {
  readonly digest: string | undefined;
  readonly kind: 'authentication-kernel' | 'generation';
  readonly release: () => Promise<void>;
}

export interface DesktopRendererGenerationActionsV2 {
  readonly acquireOperationLease: () => DesktopRendererOperationLeaseV2;
}

export interface DesktopRendererGenerationContextValueV2 {
  readonly actions: DesktopRendererGenerationActionsV2;
  readonly meta: DesktopRendererGenerationMetaV2;
  readonly state: DesktopRendererGenerationStateV2;
}

const AUTHENTICATION_KERNEL_OPERATION_LEASE_V2: DesktopRendererOperationLeaseV2 = Object.freeze({
  digest: undefined,
  kind: 'authentication-kernel',
  release: async () => undefined,
});

const DesktopRendererGenerationContextV2 =
  createContext<DesktopRendererGenerationContextValueV2 | null>(null);

export interface DesktopRendererGenerationProviderV2Props {
  readonly children: ReactNode;
  readonly value: DesktopRendererGenerationContextValueV2;
}

export function DesktopRendererGenerationProviderV2({
  children,
  value,
}: DesktopRendererGenerationProviderV2Props) {
  return (
    <DesktopRendererGenerationContextV2 value={value}>
      <DesktopRendererAuthorityContextV2 value={value.state.authority}>
        {children}
      </DesktopRendererAuthorityContextV2>
    </DesktopRendererGenerationContextV2>
  );
}

export function useDesktopRendererGenerationV2(): DesktopRendererGenerationContextValueV2 {
  const value = use(DesktopRendererGenerationContextV2);
  if (value === null) {
    throw new Error('desktop_renderer_generation_host_missing');
  }
  return value;
}

export function useDesktopRendererGenerationHostV2(
  config: DesktopRuntimeConfig,
  enabled: boolean,
  routeRefs: AppRouteRegistryRefs,
): DesktopRendererGenerationContextValueV2 {
  const generationState = useDesktopPluginGenerationV2(config, enabled);
  const generation = generationState.generation;
  const generationDigest = generation?.snapshot.digest;
  const generationError = generationState.error;
  const generationStatus = generationState.status;

  return useMemo(() => {
    const authority = resolveDesktopRendererAuthorityStateV2(generation, enabled);
    const routeRegistry = projectDesktopRouteRegistryV2(routeRefs, authority);
    const navigationRegistry = projectDesktopNavigationRegistryV2(routeRegistry, authority);
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
    });
    return Object.freeze({
      actions,
      meta: Object.freeze({
        digest: generationDigest,
        error: generationError,
        status: generationStatus,
        target: DESKTOP_RENDERER_TARGET_V2,
      }),
      state: Object.freeze({ authority, navigationRegistry, routeRegistry }),
    });
  }, [enabled, generation, generationDigest, generationError, generationStatus, routeRefs]);
}
