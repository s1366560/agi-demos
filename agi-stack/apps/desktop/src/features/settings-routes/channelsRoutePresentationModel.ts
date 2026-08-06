import type { ChannelsRouteObservation, ChannelsRouteScope } from './channelsRouteClient';
import {
  buildNativeSettingsRoutePresentation,
  type NativeSettingsRoutePresentationInput,
  type NativeSettingsRoutePresentationModel,
} from './nativeSettingsRoutePresentation';

export const CHANNELS_ROUTE_ID = 'project-project-channels' as const;

export type ChannelsRoutePresentationInput = NativeSettingsRoutePresentationInput<
  ChannelsRouteScope,
  ChannelsRouteObservation
>;

export type ChannelsRoutePresentationModel = NativeSettingsRoutePresentationModel<
  typeof CHANNELS_ROUTE_ID,
  ChannelsRouteScope,
  ChannelsRouteObservation
>;

export function buildChannelsRoutePresentation(
  input: ChannelsRoutePresentationInput,
): ChannelsRoutePresentationModel {
  return buildNativeSettingsRoutePresentation(CHANNELS_ROUTE_ID, input);
}
