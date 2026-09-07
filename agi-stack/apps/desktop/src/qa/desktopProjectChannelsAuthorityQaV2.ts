import type { DesktopProjectChannelsOperationsV2 } from '../plugins/desktopProjectChannelsAuthorityModuleV2';
import { createDesktopProjectChannelsHttpProjectionV2 } from '../plugins/desktopProjectChannelsHttpProjectionV2';
import {
  prepareDesktopProjectChannelsCreateV2,
  prepareDesktopProjectChannelsItemV2,
  prepareDesktopProjectChannelsLoadV2,
  prepareDesktopProjectChannelsSchemaV2,
  prepareDesktopProjectChannelsUpdateV2,
  requireDesktopProjectChannelConfigV2,
  requireDesktopProjectChannelSchemaV2,
  requireDesktopProjectChannelsSnapshotV2,
  requireDesktopProjectChannelTestResultV2,
} from '../plugins/desktopProjectChannelsOperationContractV2';

export function createDesktopProjectChannelsQaOperationsV2(): DesktopProjectChannelsOperationsV2 {
  const operations: DesktopProjectChannelsOperationsV2 = {
    async loadProjectChannels(input) {
      const prepared = prepareDesktopProjectChannelsLoadV2(input);
      const authority = createDesktopProjectChannelsHttpProjectionV2(prepared.config);
      return requireDesktopProjectChannelsSnapshotV2(
        await authority.load(prepared.scope, prepared.signal),
        prepared.scope,
      );
    },
    async getProjectChannelSchema(input) {
      const prepared = prepareDesktopProjectChannelsSchemaV2(input);
      const authority = createDesktopProjectChannelsHttpProjectionV2(prepared.config);
      return requireDesktopProjectChannelSchemaV2(
        await authority.schema(prepared.scope, prepared.channelType, prepared.signal),
        prepared.channelType,
      );
    },
    async createProjectChannelConfig(input) {
      const prepared = prepareDesktopProjectChannelsCreateV2(input);
      const authority = createDesktopProjectChannelsHttpProjectionV2(prepared.config);
      return requireDesktopProjectChannelConfigV2(
        await authority.create(prepared.scope, prepared.input, prepared.signal),
        prepared.scope.projectId,
      );
    },
    async updateProjectChannelConfig(input) {
      const prepared = prepareDesktopProjectChannelsUpdateV2(input);
      const authority = createDesktopProjectChannelsHttpProjectionV2(prepared.config);
      return requireDesktopProjectChannelConfigV2(
        await authority.update(
          prepared.scope,
          prepared.configId,
          prepared.input,
          prepared.signal,
        ),
        prepared.scope.projectId,
      );
    },
    async testProjectChannelConfig(input) {
      const prepared = prepareDesktopProjectChannelsItemV2(input);
      const authority = createDesktopProjectChannelsHttpProjectionV2(prepared.config);
      return requireDesktopProjectChannelTestResultV2(
        await authority.test(prepared.scope, prepared.configId, prepared.signal),
      );
    },
    async removeProjectChannelConfig(input) {
      const prepared = prepareDesktopProjectChannelsItemV2(input);
      const authority = createDesktopProjectChannelsHttpProjectionV2(prepared.config);
      await authority.remove(prepared.scope, prepared.configId, prepared.signal);
    },
  };
  return Object.freeze(operations);
}
