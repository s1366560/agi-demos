import type { AgentConversation, ProjectSummary } from '../../types';
import {
  desktopCapability,
  type DesktopCapabilitySnapshot,
} from '../runtime/capabilitySnapshot';
import type { DesktopAutomationApi } from './automationClient';
import type {
  ProjectCronJobsRouteBinding,
  ProjectCronJobsRouteContext,
  ProjectCronJobsRouteScope,
} from './projectCronJobsRouteModule';

import { automationConversationChoices, type AutomationConversationChoice } from './automationConversationModel';

const AUTOMATION_RUN_CAPABILITY_ID = 'automation_run' as const;

export type ProjectCronJobsRouteBindingProviderReasonCodeV2 =
  | 'project_cron_jobs_route_binding_unpublished'
  | 'project_cron_jobs_route_binding_scope_mismatch';

export class ProjectCronJobsRouteBindingProviderErrorV2 extends Error {
  readonly reasonCode: ProjectCronJobsRouteBindingProviderReasonCodeV2;

  constructor(reasonCode: ProjectCronJobsRouteBindingProviderReasonCodeV2) {
    super(reasonCode);
    this.name = 'ProjectCronJobsRouteBindingProviderErrorV2';
    this.reasonCode = reasonCode;
  }
}

export type ProjectCronJobsRouteBindingInputV2 = Readonly<{
  api: DesktopAutomationApi;
  scope: ProjectCronJobsRouteScope;
  projects: readonly ProjectSummary[];
  conversations?: readonly AgentConversation[];
  capabilitySnapshot: DesktopCapabilitySnapshot | null;
  onOpenProjectSettings: () => void;
  onOpenConnection: () => void;
  onOpenConversation?: (choice: AutomationConversationChoice) => void;
}>;

export type ProjectCronJobsRouteBindingProviderV2 = Readonly<{
  publish: (input: ProjectCronJobsRouteBindingInputV2) => void;
  resolve: (context: ProjectCronJobsRouteContext) => ProjectCronJobsRouteBinding;
}>;

type ProjectCronJobsRouteBindingPublicationV2 = Readonly<{
  scope: ProjectCronJobsRouteScope;
  binding: ProjectCronJobsRouteBinding;
}>;

export function createProjectCronJobsRouteBindingProviderV2():
  ProjectCronJobsRouteBindingProviderV2 {
  let publication: ProjectCronJobsRouteBindingPublicationV2 | null = null;

  return Object.freeze({
    publish(input: ProjectCronJobsRouteBindingInputV2) {
      const scope = Object.freeze({
        tenantId: input.scope.tenantId,
        projectId: input.scope.projectId,
      });
      const project = input.projects.find(
        (candidate) =>
          candidate.id === scope.projectId && candidate.tenant_id === scope.tenantId,
      );
      const runCapability = Object.freeze(
        desktopCapability(input.capabilitySnapshot, AUTOMATION_RUN_CAPABILITY_ID),
      );
      const binding = Object.freeze({
        api: input.api,
        scope,
        projectName: (project?.name ?? project?.id ?? scope.projectId) || null,
        runCapability,
        conversations: automationConversationChoices(input.conversations ?? [], scope),
        onOpenProjectSettings: input.onOpenProjectSettings,
        onOpenConnection: input.onOpenConnection,
        onOpenConversation: input.onOpenConversation,
      });
      publication = Object.freeze({ scope, binding });
    },
    resolve(context) {
      if (publication === null) {
        throw new ProjectCronJobsRouteBindingProviderErrorV2(
          'project_cron_jobs_route_binding_unpublished',
        );
      }
      if (
        publication.scope.tenantId !== context.tenantId ||
        publication.scope.projectId !== context.projectId
      ) {
        throw new ProjectCronJobsRouteBindingProviderErrorV2(
          'project_cron_jobs_route_binding_scope_mismatch',
        );
      }
      return publication.binding;
    },
  });
}
