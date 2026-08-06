import type {
  ChannelsRouteClient,
  ChannelsRouteObservation,
  ChannelsRouteScope,
} from './channelsRouteClient';
import {
  createNativeSettingsRouteController,
  type NativeSettingsRouteController,
} from './nativeSettingsRouteController';
import {
  buildChannelsRoutePresentation,
  type ChannelsRoutePresentationModel,
} from './channelsRoutePresentationModel';

export type ChannelsRouteController = NativeSettingsRouteController<
  ChannelsRouteScope,
  ChannelsRoutePresentationModel
> &
  Readonly<{
    getSchema(
      scope: ChannelsRouteScope,
      channelType: string,
    ): ReturnType<ChannelsRouteClient['getSchema']>;
    create(
      scope: ChannelsRouteScope,
      input: Parameters<ChannelsRouteClient['create']>[1],
    ): Promise<void>;
    update(
      scope: ChannelsRouteScope,
      configId: string,
      input: Parameters<ChannelsRouteClient['update']>[2],
    ): Promise<void>;
    test(scope: ChannelsRouteScope, configId: string): ReturnType<ChannelsRouteClient['test']>;
    remove(scope: ChannelsRouteScope, configId: string): Promise<void>;
  }>;

export function createChannelsRouteController({
  client,
  initialScope,
}: Readonly<{
  client: ChannelsRouteClient;
  initialScope: ChannelsRouteScope;
}>): ChannelsRouteController {
  const controller = createNativeSettingsRouteController<
    ChannelsRouteScope,
    ChannelsRouteObservation,
    ChannelsRoutePresentationModel
  >({
    client,
    initialScope,
    sameScope: (left, right) =>
      left.authority === right.authority &&
      left.tenantId === right.tenantId &&
      left.projectId === right.projectId,
    present: buildChannelsRoutePresentation,
    fallbackReasonCode: 'project_channels_request_failed',
  });
  return Object.freeze({
    ...controller,
    getSchema: (scope, channelType) => client.getSchema(scope, channelType),
    async create(scope, input) {
      await client.create(scope, input);
      await controller.load(scope);
    },
    async update(scope, configId, input) {
      await client.update(scope, configId, input);
      await controller.load(scope);
    },
    async test(scope, configId) {
      const result = await client.test(scope, configId);
      await controller.load(scope);
      return result;
    },
    async remove(scope, configId) {
      await client.remove(scope, configId);
      await controller.load(scope);
    },
  });
}
