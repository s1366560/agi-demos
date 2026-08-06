import type { DesktopRuntimeConfig } from '../../types';

export type NativeSettingsRouteState =
  | 'loading'
  | 'scope_switch'
  | 'ready'
  | 'empty'
  | 'degraded'
  | 'conflict'
  | 'forbidden'
  | 'unavailable'
  | 'error';

export type NativeSettingsRouteScope = Readonly<{
  authority: DesktopRuntimeConfig['mode'];
}>;

export type NativeSettingsRouteObservation<TScope extends NativeSettingsRouteScope> = Readonly<{
  scope: TScope;
  authority: DesktopRuntimeConfig['mode'];
  availability: 'available' | 'degraded';
  reasonCode: string | null;
  itemCount: number;
}>;

export type NativeSettingsRoutePresentationInput<
  TScope extends NativeSettingsRouteScope,
  TObservation extends NativeSettingsRouteObservation<TScope>,
> =
  | Readonly<{ kind: 'loading'; scope: TScope; scopeSwitch: boolean }>
  | Readonly<{ kind: 'observed'; observation: TObservation }>
  | Readonly<{
      kind: 'failure';
      scope: TScope;
      state: 'conflict' | 'forbidden' | 'unavailable' | 'error';
      reasonCode: string;
      retryable: boolean;
    }>;

export type NativeSettingsRoutePresentationModel<
  TCapability extends string,
  TScope extends NativeSettingsRouteScope,
  TObservation extends NativeSettingsRouteObservation<TScope>,
> = Readonly<{
  capability: TCapability;
  scope: TScope;
  authority: DesktopRuntimeConfig['mode'];
  state: NativeSettingsRouteState;
  reasonCode: string | null;
  retryVisible: boolean;
  itemCount: number | null;
  observation: TObservation | null;
}>;

export function buildNativeSettingsRoutePresentation<
  TCapability extends string,
  TScope extends NativeSettingsRouteScope,
  TObservation extends NativeSettingsRouteObservation<TScope>,
>(
  capability: TCapability,
  input: NativeSettingsRoutePresentationInput<TScope, TObservation>,
): NativeSettingsRoutePresentationModel<TCapability, TScope, TObservation> {
  if (input.kind === 'loading') {
    return Object.freeze({
      capability,
      scope: input.scope,
      authority: input.scope.authority,
      state: input.scopeSwitch ? 'scope_switch' : 'loading',
      reasonCode: null,
      retryVisible: false,
      itemCount: null,
      observation: null,
    });
  }
  if (input.kind === 'observed') {
    const { observation } = input;
    return Object.freeze({
      capability,
      scope: observation.scope,
      authority: observation.authority,
      state:
        observation.availability === 'degraded'
          ? 'degraded'
          : observation.itemCount === 0
            ? 'empty'
            : 'ready',
      reasonCode: observation.reasonCode,
      retryVisible: false,
      itemCount: observation.itemCount,
      observation,
    });
  }
  return Object.freeze({
    capability,
    scope: input.scope,
    authority: input.scope.authority,
    state: input.state,
    reasonCode: input.reasonCode,
    retryVisible: input.retryable,
    itemCount: null,
    observation: null,
  });
}
