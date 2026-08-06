import type { ProfileRouteObservation, ProfileRouteScope } from './profileRouteClient';
import {
  buildNativeSettingsRoutePresentation,
  type NativeSettingsRoutePresentationInput,
  type NativeSettingsRoutePresentationModel,
} from './nativeSettingsRoutePresentation';

export const PROFILE_ROUTE_ID = 'user-profile' as const;

export type ProfileRoutePresentationInput = NativeSettingsRoutePresentationInput<
  ProfileRouteScope,
  ProfileRouteObservation
>;

export type ProfileRoutePresentationModel = NativeSettingsRoutePresentationModel<
  typeof PROFILE_ROUTE_ID,
  ProfileRouteScope,
  ProfileRouteObservation
>;

export function buildProfileRoutePresentation(
  input: ProfileRoutePresentationInput,
): ProfileRoutePresentationModel {
  return buildNativeSettingsRoutePresentation(PROFILE_ROUTE_ID, input);
}
