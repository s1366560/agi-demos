import type { EvolutionRouteObservation, EvolutionRouteScope } from './evolutionRouteClient';
import {
  buildNativeSettingsRoutePresentation,
  type NativeSettingsRoutePresentationInput,
  type NativeSettingsRoutePresentationModel,
} from './nativeSettingsRoutePresentation';

export const EVOLUTION_ROUTE_ID = 'tenant-tenant-evolution' as const;

export type EvolutionRoutePresentationInput = NativeSettingsRoutePresentationInput<
  EvolutionRouteScope,
  EvolutionRouteObservation
>;

export type EvolutionRoutePresentationModel = NativeSettingsRoutePresentationModel<
  typeof EVOLUTION_ROUTE_ID,
  EvolutionRouteScope,
  EvolutionRouteObservation
>;

export function buildEvolutionRoutePresentation(
  input: EvolutionRoutePresentationInput,
): EvolutionRoutePresentationModel {
  return buildNativeSettingsRoutePresentation(EVOLUTION_ROUTE_ID, input);
}
