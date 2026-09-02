import { RuntimeV2Error, type ContextV2 } from '@agistack/plugin-runtime';

import {
  DESKTOP_NEW_TASK_FLOW_AUTHORITY_SERVICE_V2,
  DESKTOP_NEW_TASK_FLOW_AUTHORITY_VERSION_V2,
  applyDesktopNewTaskFlowAuthorityV2,
  createDesktopNewTaskFlowOperationsV2,
  type DesktopNewTaskFlowAuthorityServiceV2,
  type DesktopNewTaskFlowOperationsV2,
} from '../plugins/desktopNewTaskFlowAuthorityModuleV2';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseRequestV2,
} from '../plugins/desktopRendererGenerationContextV2';

const QA_GENERATION_DIGEST_V2 = `sha256:${'a'.repeat(64)}`;

export function createDesktopNewTaskFlowQaOperationsV2(): DesktopNewTaskFlowOperationsV2 {
  const service = activateQaServiceV2();
  const actions: DesktopRendererGenerationActionsV2 = Object.freeze({
    acquireOperationLease() {
      throw new RuntimeV2Error(
        'desktop_new_task_flow_qa_generic_lease_forbidden',
        'new-task flow QA must acquire its declared service',
      );
    },
    async acquireServiceOperationLease<TService>(
      request: DesktopRendererServiceOperationLeaseRequestV2,
    ) {
      if (
        request.service !== DESKTOP_NEW_TASK_FLOW_AUTHORITY_SERVICE_V2 ||
        request.version !== DESKTOP_NEW_TASK_FLOW_AUTHORITY_VERSION_V2
      ) {
        return Object.freeze({
          status: 'rejected' as const,
          reasonCode: 'desktop_renderer_service_request_invalid' as const,
        });
      }
      let released = false;
      return Object.freeze({
        status: 'accepted' as const,
        digest: QA_GENERATION_DIGEST_V2,
        useService<TResult>(operation: (candidate: TService) => TResult): TResult {
          if (released) throw new Error('desktop_renderer_service_generation_lease_released');
          return operation(service as unknown as TService);
        },
        async release() {
          released = true;
        },
      });
    },
  });
  return createDesktopNewTaskFlowOperationsV2(() => actions);
}

function activateQaServiceV2(): DesktopNewTaskFlowAuthorityServiceV2 {
  let service: DesktopNewTaskFlowAuthorityServiceV2 | null = null;
  const context = {
    provide(key: string, value: unknown) {
      if (key !== DESKTOP_NEW_TASK_FLOW_AUTHORITY_SERVICE_V2 || service !== null) {
        throw new Error('desktop_new_task_flow_qa_service_registration_invalid');
      }
      service = value as DesktopNewTaskFlowAuthorityServiceV2;
      return async () => undefined;
    },
  } as unknown as ContextV2;
  applyDesktopNewTaskFlowAuthorityV2(context, { strategy: 'desktop-api-client' });
  if (service === null) throw new Error('desktop_new_task_flow_qa_service_missing');
  return service;
}
