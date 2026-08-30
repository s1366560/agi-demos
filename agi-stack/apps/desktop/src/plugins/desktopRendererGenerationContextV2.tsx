import { createContext, use, type ReactNode } from 'react';

import type { DesktopRouteModule } from '../features/navigation/desktopRouteModule';
import type { DesktopRouteRegistry } from '../features/navigation/desktopRouteRegistry';
import type { DesktopRendererCompositionPortV2 } from './desktopRendererCompositionPortV2';
import {
  DesktopRendererAuthorityContextV2,
  type DesktopRendererAuthorityStateV2,
} from './desktopRendererAuthorityStateV2';

export const DESKTOP_RENDERER_TARGET_V2 = 'desktop-renderer' as const;

export interface DesktopRendererGenerationStateV2 {
  readonly authority: DesktopRendererAuthorityStateV2;
  readonly navigationRegistry: DesktopRouteRegistry<DesktopRouteModule>;
  readonly routeRegistry: DesktopRouteRegistry<DesktopRouteModule>;
}

export type DesktopRendererGenerationStatusV2 =
  | 'degraded'
  | 'empty'
  | 'error'
  | 'loading'
  | 'ready';

export interface DesktopRendererGenerationMetaV2 {
  readonly digest: string | undefined;
  readonly error: unknown | undefined;
  readonly status: DesktopRendererGenerationStatusV2;
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
  readonly composition: DesktopRendererCompositionPortV2;
  readonly meta: DesktopRendererGenerationMetaV2;
  readonly state: DesktopRendererGenerationStateV2;
}

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

export function useOptionalDesktopRendererGenerationV2():
  DesktopRendererGenerationContextValueV2 | null {
  return use(DesktopRendererGenerationContextV2);
}
