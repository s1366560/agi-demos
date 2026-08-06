import type { TemplatesRouteObservation, TemplatesRouteScope } from './templatesRouteClient';
import {
  buildNativeSettingsRoutePresentation,
  type NativeSettingsRoutePresentationInput,
  type NativeSettingsRoutePresentationModel,
} from './nativeSettingsRoutePresentation';

export const TEMPLATES_ROUTE_ID = 'tenant-tenant-templates' as const;

export type TemplatesRoutePresentationInput = NativeSettingsRoutePresentationInput<
  TemplatesRouteScope,
  TemplatesRouteObservation
>;

export type TemplatesRoutePresentationModel = NativeSettingsRoutePresentationModel<
  typeof TEMPLATES_ROUTE_ID,
  TemplatesRouteScope,
  TemplatesRouteObservation
>;

export function buildTemplatesRoutePresentation(
  input: TemplatesRoutePresentationInput,
): TemplatesRoutePresentationModel {
  return buildNativeSettingsRoutePresentation(TEMPLATES_ROUTE_ID, input);
}
