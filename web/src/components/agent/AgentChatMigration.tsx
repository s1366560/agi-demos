/**
 * AgentChat Migration - Updated ensureSandbox using Project Sandbox API
 *
 * This file shows how to update AgentChat.tsx to use the new project-scoped
 * sandbox API instead of the old sandbox ID-based API.
 */

import { useCallback } from 'react';
import { projectSandboxService } from '../../services/projectSandboxService';
import { useSandboxStore } from '../../stores/sandbox';

/**
 * Hook: useEnsureProjectSandbox
 *
 * Replacement for the ensureSandbox function in AgentChat.tsx
 * Uses the new project-scoped API.
 */
export function useEnsureProjectSandbox(projectId: string | undefined) {
  const { activeSandboxId, setSandboxId } = useSandboxStore();

  const ensureSandbox = useCallback(async () => {
    if (activeSandboxId) return activeSandboxId;
    if (!projectId) return null;

    try {
      // Use new project-scoped API
      const sandbox = await projectSandboxService.ensureSandbox(projectId);
      
      if (sandbox.is_healthy) {
        setSandboxId(sandbox.sandbox_id);
        return sandbox.sandbox_id;
      }
      
      // If not healthy, try to restart
      const result = await projectSandboxService.restartSandbox(projectId);
      if (result.success && result.sandbox) {
        setSandboxId(result.sandbox.sandbox_id);
        return result.sandbox.sandbox_id;
      }
      
      return null;
    } catch (error) {
      console.error('[AgentChat] Failed to ensure sandbox:', error);
      return null;
    }
  }, [activeSandboxId, projectId, setSandboxId]);

  return ensureSandbox;
}

/**
 * Hook: useProjectDesktop
 *
 * Manage desktop service using project-scoped API
 */
export function useProjectDesktop(projectId: string | undefined) {
  const startDesktop = useCallback(async () => {
    if (!projectId) throw new Error('No project ID');
    return projectSandboxService.startDesktop(projectId);
  }, [projectId]);

  const stopDesktop = useCallback(async () => {
    if (!projectId) throw new Error('No project ID');
    return projectSandboxService.stopDesktop(projectId);
  }, [projectId]);

  return { startDesktop, stopDesktop };
}

/**
 * Hook: useProjectTerminal
 *
 * Manage terminal service using project-scoped API
 */
export function useProjectTerminal(projectId: string | undefined) {
  const startTerminal = useCallback(async () => {
    if (!projectId) throw new Error('No project ID');
    return projectSandboxService.startTerminal(projectId);
  }, [projectId]);

  const stopTerminal = useCallback(async () => {
    if (!projectId) throw new Error('No project ID');
    return projectSandboxService.stopTerminal(projectId);
  }, [projectId]);

  return { startTerminal, stopTerminal };
}

/**
 * Migration Guide:
 *
 * 1. In AgentChat.tsx, replace:
 *
 *    import { sandboxService } from '../../services/sandboxService';
 *
 *    with:
 *
 *    import { projectSandboxService } from '../../services/projectSandboxService';
 *
 * 2. Replace the ensureSandbox function:
 *
 *    OLD:
 *    const ensureSandbox = useCallback(async () => {
 *      if (activeSandboxId) return activeSandboxId;
 *      if (!projectId) return null;
 *
 *      try {
 *        const { sandboxes } = await sandboxService.listSandboxes(projectId);
 *        if (sandboxes.length > 0 && sandboxes[0].status === 'running') {
 *          setSandboxId(sandboxes[0].id);
 *          return sandboxes[0].id;
 *        }
 *        const { sandbox } = await sandboxService.createSandbox({ project_id: projectId });
 *        setSandboxId(sandbox.id);
 *        return sandbox.id;
 *      } catch (error) {
 *        console.error('[AgentChat] Failed to ensure sandbox:', error);
 *        return null;
 *      }
 *    }, [activeSandboxId, projectId, setSandboxId]);
 *
 *    NEW:
 *    const ensureSandbox = useCallback(async () => {
 *      if (activeSandboxId) return activeSandboxId;
 *      if (!projectId) return null;
 *
 *      try {
 *        const sandbox = await projectSandboxService.ensureSandbox(projectId);
 *        setSandboxId(sandbox.sandbox_id);
 *        return sandbox.sandbox_id;
 *      } catch (error) {
 *        console.error('[AgentChat] Failed to ensure sandbox:', error);
 *        return null;
 *      }
 *    }, [activeSandboxId, projectId, setSandboxId]);
 *
 * 3. Update sandbox store to use projectId for SSE subscription:
 *
 *    The SSE service already uses projectId, so no changes needed there.
 *
 * 4. Update SandboxPanel components to accept projectId prop:
 *
 *    Components can use the new hooks (useProjectDesktop, useProjectTerminal)
 *    instead of using sandboxId.
 */
