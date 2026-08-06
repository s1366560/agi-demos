import type {
  ProfileRouteClient,
  ProfileRouteObservation,
  ProfileRouteScope,
} from './profileRouteClient';
import {
  createNativeSettingsRouteController,
  type NativeSettingsRouteController,
} from './nativeSettingsRouteController';
import {
  buildProfileRoutePresentation,
  type ProfileRoutePresentationModel,
} from './profileRoutePresentationModel';

export type ProfileRouteController = NativeSettingsRouteController<
  ProfileRouteScope,
  ProfileRoutePresentationModel
> &
  Readonly<{
    update(
      scope: ProfileRouteScope,
      input: Parameters<ProfileRouteClient['update']>[1],
    ): Promise<void>;
    changePassword(
      scope: ProfileRouteScope,
      input: Parameters<ProfileRouteClient['changePassword']>[1],
    ): Promise<void>;
  }>;

export function createProfileRouteController({
  client,
  initialScope,
}: Readonly<{
  client: ProfileRouteClient;
  initialScope: ProfileRouteScope;
}>): ProfileRouteController {
  const controller = createNativeSettingsRouteController<
    ProfileRouteScope,
    ProfileRouteObservation,
    ProfileRoutePresentationModel
  >({
    client,
    initialScope,
    sameScope: (left, right) => left.authority === right.authority,
    present: buildProfileRoutePresentation,
    fallbackReasonCode: 'user_profile_request_failed',
  });
  return Object.freeze({
    ...controller,
    async update(scope, input) {
      await client.update(scope, input);
      await controller.load(scope);
    },
    async changePassword(scope, input) {
      await client.changePassword(scope, input);
      await controller.load(scope);
    },
  });
}
