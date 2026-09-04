import type {
  CreateManagedChannelConfigRequest,
  DesktopRuntimeConfig,
  ManagedChannelConfig,
  ManagedChannelPluginCatalogItem,
  ManagedChannelPluginConfigSchema,
  ManagedChannelTestResult,
  UpdateManagedChannelConfigRequest,
} from '../../types';
export type ChannelsRouteScope = Readonly<{
  authority: DesktopRuntimeConfig['mode'];
  tenantId: string;
  projectId: string;
}>;

export type ChannelsRouteObservation = Readonly<{
  scope: ChannelsRouteScope;
  authority: DesktopRuntimeConfig['mode'];
  availability: 'available';
  reasonCode: null;
  allowedActions: readonly string[];
  itemCount: number;
  catalog: readonly ManagedChannelPluginCatalogItem[];
  configs: readonly ManagedChannelConfig[];
}>;

export type ChannelsRouteClient = Readonly<{
  observe(scope: ChannelsRouteScope, signal?: AbortSignal): Promise<ChannelsRouteObservation>;
  getSchema(
    scope: ChannelsRouteScope,
    channelType: string,
    signal?: AbortSignal,
  ): Promise<ManagedChannelPluginConfigSchema>;
  create(
    scope: ChannelsRouteScope,
    input: CreateManagedChannelConfigRequest,
    signal?: AbortSignal,
  ): Promise<ManagedChannelConfig>;
  update(
    scope: ChannelsRouteScope,
    configId: string,
    input: UpdateManagedChannelConfigRequest,
    signal?: AbortSignal,
  ): Promise<ManagedChannelConfig>;
  test(
    scope: ChannelsRouteScope,
    configId: string,
    signal?: AbortSignal,
  ): Promise<ManagedChannelTestResult>;
  remove(scope: ChannelsRouteScope, configId: string, signal?: AbortSignal): Promise<void>;
}>;
