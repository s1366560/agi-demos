import type {
  ManagementRouteCapability,
  ManagementRouteObservation,
  ManagementRouteScope,
} from './managementRouteTypes';

export type ManagementRoutePresentationState =
  | 'loading'
  | 'scope_switch'
  | 'ready'
  | 'empty'
  | 'conflict'
  | 'forbidden'
  | 'unavailable'
  | 'error';

export type ManagementRoutePresentationInput =
  | Readonly<{
      kind: 'loading';
      capability: ManagementRouteCapability;
      scope: ManagementRouteScope;
      scopeSwitch: boolean;
    }>
  | Readonly<{
      kind: 'observed';
      capability: ManagementRouteCapability;
      observation: ManagementRouteObservation;
    }>
  | Readonly<{
      kind: 'terminal';
      capability: ManagementRouteCapability;
      scope: ManagementRouteScope;
      state: 'conflict' | 'forbidden' | 'unavailable' | 'error';
      reasonCode: string;
      retryable: boolean;
    }>;

export type ManagementRoutePresentationModel = Readonly<{
  capability: ManagementRouteCapability;
  scope: ManagementRouteScope;
  state: ManagementRoutePresentationState;
  reasonCode: string | null;
  retryVisible: boolean;
  itemCount: number | null;
}>;

export function buildManagementRoutePresentation(
  input: ManagementRoutePresentationInput,
): ManagementRoutePresentationModel {
  if (input.kind === 'loading') {
    return Object.freeze({
      capability: input.capability,
      scope: input.scope,
      state: input.scopeSwitch ? 'scope_switch' : 'loading',
      reasonCode: null,
      retryVisible: false,
      itemCount: null,
    });
  }
  if (input.kind === 'observed') {
    return Object.freeze({
      capability: input.capability,
      scope: input.observation.scope,
      state: input.observation.itemCount === 0 ? 'empty' : 'ready',
      reasonCode: null,
      retryVisible: false,
      itemCount: input.observation.itemCount,
    });
  }
  return Object.freeze({
    capability: input.capability,
    scope: input.scope,
    state: input.state,
    reasonCode: input.reasonCode,
    retryVisible: input.retryable,
    itemCount: null,
  });
}
