import type { DesktopApiClient } from '../../api/client';
import type { ProjectSummary } from '../../types';
import {
  desktopCapability,
  type DesktopCapabilitySnapshot,
} from '../runtime/capabilitySnapshot';
import {
  type ProjectSearchRouteBinding,
  type ProjectSearchRouteContext,
  type ProjectSearchRouteScope,
} from './projectSearchRouteModule';

const PROJECT_SEARCH_ROUTE_ID = 'project-project-search' as const;

export type ProjectSearchRouteBindingProviderReasonCodeV2 =
  | 'project_search_route_binding_unpublished'
  | 'project_search_route_binding_scope_mismatch';

export class ProjectSearchRouteBindingProviderErrorV2 extends Error {
  readonly reasonCode: ProjectSearchRouteBindingProviderReasonCodeV2;

  constructor(reasonCode: ProjectSearchRouteBindingProviderReasonCodeV2) {
    super(reasonCode);
    this.name = 'ProjectSearchRouteBindingProviderErrorV2';
    this.reasonCode = reasonCode;
  }
}

export type ProjectSearchRouteBindingInputV2 = Readonly<{
  api: Pick<DesktopApiClient, 'searchProject'>;
  scope: ProjectSearchRouteScope;
  projects: readonly ProjectSummary[];
  capabilitySnapshot: DesktopCapabilitySnapshot | null;
  capabilityLoading: boolean;
  onRetryCapability?: () => void;
}>;

export type ProjectSearchRouteBindingProviderV2 = Readonly<{
  publish: (input: ProjectSearchRouteBindingInputV2) => void;
  resolve: (context: ProjectSearchRouteContext) => ProjectSearchRouteBinding;
}>;

type ProjectSearchRouteBindingPublicationV2 = Readonly<{
  scope: ProjectSearchRouteScope;
  binding: ProjectSearchRouteBinding;
}>;

export function createProjectSearchRouteBindingProviderV2(): ProjectSearchRouteBindingProviderV2 {
  let publication: ProjectSearchRouteBindingPublicationV2 | null = null;

  return Object.freeze({
    publish(input: ProjectSearchRouteBindingInputV2) {
      const scope = Object.freeze({
        tenantId: input.scope.tenantId,
        projectId: input.scope.projectId,
      });
      const project = input.projects.find(
        (candidate) =>
          candidate.id === scope.projectId && candidate.tenant_id === scope.tenantId,
      );
      const capability = Object.freeze(
        desktopCapability(input.capabilitySnapshot, PROJECT_SEARCH_ROUTE_ID),
      );
      const binding = Object.freeze({
        api: input.api,
        scope,
        projectName: (project?.name ?? project?.id ?? scope.projectId) || null,
        capability,
        capabilityLoading: input.capabilityLoading,
        ...(input.onRetryCapability === undefined
          ? {}
          : { onRetryCapability: input.onRetryCapability }),
      });
      publication = Object.freeze({ scope, binding });
    },
    resolve(context) {
      if (publication === null) {
        throw new ProjectSearchRouteBindingProviderErrorV2(
          'project_search_route_binding_unpublished',
        );
      }
      if (
        publication.scope.tenantId !== context.tenantId ||
        publication.scope.projectId !== context.projectId
      ) {
        throw new ProjectSearchRouteBindingProviderErrorV2(
          'project_search_route_binding_scope_mismatch',
        );
      }
      return publication.binding;
    },
  });
}
