import type {
  TemplatesRouteClient,
  TemplatesRouteDetail,
  TemplatesRouteObservation,
  TemplatesRouteQuery,
  TemplatesRouteScope,
} from './templatesRouteClient';
import {
  createNativeSettingsRouteController,
  type NativeSettingsRouteController,
} from './nativeSettingsRouteController';
import {
  buildTemplatesRoutePresentation,
  type TemplatesRoutePresentationModel,
} from './templatesRoutePresentationModel';

export type TemplatesRouteController = NativeSettingsRouteController<
  TemplatesRouteScope,
  TemplatesRoutePresentationModel
> &
  Readonly<{
    filter(scope: TemplatesRouteScope, query: TemplatesRouteQuery): Promise<void>;
    get(scope: TemplatesRouteScope, templateId: string): Promise<TemplatesRouteDetail>;
    install(scope: TemplatesRouteScope, templateId: string): Promise<void>;
    seed(scope: TemplatesRouteScope): Promise<number>;
  }>;

export function createTemplatesRouteController({
  client,
  initialScope,
}: Readonly<{
  client: TemplatesRouteClient;
  initialScope: TemplatesRouteScope;
}>): TemplatesRouteController {
  let query: TemplatesRouteQuery = Object.freeze({});
  const controller = createNativeSettingsRouteController<
    TemplatesRouteScope,
    TemplatesRouteObservation,
    TemplatesRoutePresentationModel
  >({
    client: {
      observe: (scope, signal) => client.observe(scope, query, signal),
    },
    initialScope,
    sameScope: (left, right) =>
      left.authority === right.authority && left.tenantId === right.tenantId,
    present: buildTemplatesRoutePresentation,
    fallbackReasonCode: 'template_marketplace_request_failed',
  });
  return Object.freeze({
    ...controller,
    async filter(scope, nextQuery) {
      query = Object.freeze({ ...nextQuery });
      await controller.load(scope);
    },
    get: (scope, templateId) => client.get(scope, templateId),
    async install(scope, templateId) {
      await client.install(scope, templateId);
      await controller.load(scope);
    },
    async seed(scope) {
      const created = await client.seed(scope);
      await controller.load(scope);
      return created;
    },
  });
}
