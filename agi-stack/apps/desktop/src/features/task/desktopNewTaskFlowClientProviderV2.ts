import { DesktopApiClient } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';

type DesktopNewTaskFlowMethod =
  | 'approvePlanAndStart'
  | 'createTaskSession'
  | 'getConversationMessages'
  | 'listAgentPlanTasks'
  | 'listWorkspaces'
  | 'sendMessage'
  | 'supportsAgentPlanWorkflow'
  | 'switchPlanMode';

export type DesktopNewTaskFlowClient = Readonly<Pick<DesktopApiClient, DesktopNewTaskFlowMethod>>;

export type DesktopNewTaskFlowClientProviderReasonCodeV2 =
  'desktop_new_task_flow_client_unpublished';

export class DesktopNewTaskFlowClientProviderErrorV2 extends Error {
  readonly reasonCode: DesktopNewTaskFlowClientProviderReasonCodeV2;

  constructor(reasonCode: DesktopNewTaskFlowClientProviderReasonCodeV2) {
    super(reasonCode);
    this.name = 'DesktopNewTaskFlowClientProviderErrorV2';
    this.reasonCode = reasonCode;
  }
}

export type DesktopNewTaskFlowClientProviderInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
}>;

export type DesktopNewTaskFlowClientBindingV2 = Readonly<{
  client: DesktopNewTaskFlowClient;
  bindOperation: (config: DesktopRuntimeConfig) => DesktopNewTaskFlowClient;
}>;

export type DesktopNewTaskFlowClientProviderV2 = Readonly<{
  publish: (
    input: DesktopNewTaskFlowClientProviderInputV2,
  ) => DesktopNewTaskFlowClientBindingV2;
  resolve: () => DesktopNewTaskFlowClientBindingV2;
}>;

export function createDesktopNewTaskFlowClientProviderV2():
  DesktopNewTaskFlowClientProviderV2 {
  let publication: DesktopNewTaskFlowClientBindingV2 | null = null;

  return Object.freeze({
    publish(input) {
      const next = createDesktopNewTaskFlowClientBindingV2(input);
      publication = next;
      return next;
    },
    resolve() {
      if (publication === null) {
        throw new DesktopNewTaskFlowClientProviderErrorV2(
          'desktop_new_task_flow_client_unpublished',
        );
      }
      return publication;
    },
  });
}

function createDesktopNewTaskFlowClientBindingV2(
  input: DesktopNewTaskFlowClientProviderInputV2,
): DesktopNewTaskFlowClientBindingV2 {
  const config = Object.freeze({ ...input.config });
  return Object.freeze({
    client: createDesktopNewTaskFlowClient(config),
    bindOperation: (operationConfig) =>
      createDesktopNewTaskFlowClient(Object.freeze({ ...operationConfig })),
  });
}

function createDesktopNewTaskFlowClient(
  config: DesktopRuntimeConfig,
): DesktopNewTaskFlowClient {
  const authority = new DesktopApiClient(config);
  return Object.freeze({
    approvePlanAndStart: (...args: Parameters<DesktopApiClient['approvePlanAndStart']>) =>
      authority.approvePlanAndStart(...args),
    createTaskSession: (...args: Parameters<DesktopApiClient['createTaskSession']>) =>
      authority.createTaskSession(...args),
    getConversationMessages: (
      ...args: Parameters<DesktopApiClient['getConversationMessages']>
    ) => authority.getConversationMessages(...args),
    listAgentPlanTasks: (...args: Parameters<DesktopApiClient['listAgentPlanTasks']>) =>
      authority.listAgentPlanTasks(...args),
    listWorkspaces: (...args: Parameters<DesktopApiClient['listWorkspaces']>) =>
      authority.listWorkspaces(...args),
    sendMessage: (...args: Parameters<DesktopApiClient['sendMessage']>) =>
      authority.sendMessage(...args),
    supportsAgentPlanWorkflow: (
      ...args: Parameters<DesktopApiClient['supportsAgentPlanWorkflow']>
    ) => authority.supportsAgentPlanWorkflow(...args),
    switchPlanMode: (...args: Parameters<DesktopApiClient['switchPlanMode']>) =>
      authority.switchPlanMode(...args),
  });
}
