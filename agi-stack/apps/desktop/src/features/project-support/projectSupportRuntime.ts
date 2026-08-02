import type { DesktopRuntimeConfig } from '../../types';
import { createProjectSupportClient } from './projectSupportClient';
import { createProjectSupportController } from './projectSupportController';
import type {
  ProjectSupportRouteBinding,
  ProjectSupportRouteContext,
} from './projectSupportRouteModule';

export function createProjectSupportRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: ProjectSupportRouteContext,
): ProjectSupportRouteBinding {
  if (
    config.tenantId !== context.tenantId ||
    config.projectId !== context.projectId
  ) {
    throw new Error('project_support_runtime_scope_mismatch');
  }
  const scope = Object.freeze({
    authority: config.mode,
    tenantId: context.tenantId,
    projectId: context.projectId,
  });
  const client = createProjectSupportClient(config);
  return Object.freeze({
    controller: createProjectSupportController({
      authority: config.mode,
      client,
      initialScope: scope,
    }),
    scope,
  });
}
