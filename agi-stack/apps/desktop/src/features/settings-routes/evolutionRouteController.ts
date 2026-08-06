import type {
  EvolutionRouteClient,
  EvolutionRouteObservation,
  EvolutionRouteScope,
} from './evolutionRouteClient';
import {
  createNativeSettingsRouteController,
  type NativeSettingsRouteController,
} from './nativeSettingsRouteController';
import {
  buildEvolutionRoutePresentation,
  type EvolutionRoutePresentationModel,
} from './evolutionRoutePresentationModel';

export type EvolutionRouteController = NativeSettingsRouteController<
  EvolutionRouteScope,
  EvolutionRoutePresentationModel
> &
  Readonly<{
    run(scope: EvolutionRouteScope): Promise<void>;
    updateConfig(
      scope: EvolutionRouteScope,
      input: Parameters<EvolutionRouteClient['updateConfig']>[1],
    ): Promise<void>;
    reviewJob(scope: EvolutionRouteScope, jobId: string, action: 'apply' | 'reject'): Promise<void>;
  }>;

export function createEvolutionRouteController({
  client,
  initialScope,
}: Readonly<{
  client: EvolutionRouteClient;
  initialScope: EvolutionRouteScope;
}>): EvolutionRouteController {
  const controller = createNativeSettingsRouteController<
    EvolutionRouteScope,
    EvolutionRouteObservation,
    EvolutionRoutePresentationModel
  >({
    client,
    initialScope,
    sameScope: (left, right) =>
      left.authority === right.authority && left.tenantId === right.tenantId,
    present: buildEvolutionRoutePresentation,
    fallbackReasonCode: 'skill_evolution_request_failed',
  });
  return Object.freeze({
    ...controller,
    async run(scope) {
      await client.run(scope);
      await controller.load(scope);
    },
    async updateConfig(scope, input) {
      await client.updateConfig(scope, input);
      await controller.load(scope);
    },
    async reviewJob(scope, jobId, action) {
      await client.reviewJob(scope, jobId, action);
      await controller.load(scope);
    },
  });
}
