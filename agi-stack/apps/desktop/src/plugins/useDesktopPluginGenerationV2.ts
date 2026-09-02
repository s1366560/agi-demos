import { useEffect, useLayoutEffect, useSyncExternalStore } from 'react';

import {
  createDesktopRendererDefinitionsV2,
  DesktopRendererDistributionReconcilerV2,
  RendererGenerationLeaseStoreV2,
  RendererGenerationStatusStoreV2,
  RendererPluginRuntimeV2,
  projectRendererPluginGenerationStateV2,
  startRendererGenerationPollingV2,
  type GenerationLeaseV2,
  type RendererPluginGenerationStateV2,
  type RuntimeGenerationV2,
} from '@agistack/plugin-runtime';

import type { DesktopRuntimeConfig } from '../types';

import { desktopArtifactContentAuthorityDefinitionV2 } from './desktopArtifactContentAuthorityModuleV2';
import { desktopAutomationAuthorityDefinitionV2 } from './desktopAutomationAuthorityModuleV2';
import { desktopConversationLifecycleAuthorityDefinitionV2 } from './desktopConversationLifecycleAuthorityModuleV2';
import { validateDesktopRendererContributionsV2 } from './desktopRendererArtifactCatalogV2';
import { desktopConversationConfigAuthorityDefinitionV2 } from './desktopConversationConfigAuthorityModuleV2';
import { desktopHitlResponseAuthorityDefinitionV2 } from './desktopHitlResponseAuthorityModuleV2';
import { desktopMyWorkAuthorityDefinitionV2 } from './desktopMyWorkAuthorityModuleV2';
import { desktopNewTaskFlowAuthorityDefinitionV2 } from './desktopNewTaskFlowAuthorityModuleV2';
import {
  desktopNewThreadCreationAuthorityDefinitionV2,
} from './desktopNewThreadCreationAuthorityModuleV2';
import { desktopProjectSearchAuthorityDefinitionV2 } from './desktopProjectSearchAuthorityModuleV2';
import { desktopSessionArtifactActionAuthorityDefinitionV2 } from './desktopSessionArtifactActionAuthorityModuleV2';
import { desktopSessionRunControlAuthorityDefinitionV2 } from './desktopSessionRunControlAuthorityModuleV2';
import {
  desktopPluginMarketplaceCatalogDefinitionV2,
  desktopPluginMarketplaceManagementDefinitionV2,
} from './desktopPluginMarketplaceAuthorityModulesV2';
import { desktopSessionProjectionAuthorityDefinitionV2 } from './desktopSessionProjectionAuthorityModuleV2';
import { desktopSessionRunChangesAuthorityDefinitionV2 } from './desktopSessionRunChangesAuthorityModuleV2';
import { desktopSessionRunInputAuthorityDefinitionV2 } from './desktopSessionRunInputAuthorityModuleV2';
import { desktopSessionTimelineAuthorityDefinitionV2 } from './desktopSessionTimelineAuthorityModuleV2';
import { desktopTerminalLifecycleAuthorityDefinitionV2 } from './desktopTerminalLifecycleAuthorityModuleV2';
import { desktopTenantAgentBindingsAuthorityDefinitionV2 } from './desktopTenantAgentBindingsAuthorityModuleV2';
import { desktopTenantAgentDashboardAuthorityDefinitionV2 } from './desktopTenantAgentDashboardAuthorityModuleV2';
import { desktopTenantAnalyticsAuthorityDefinitionV2 } from './desktopTenantAnalyticsAuthorityModuleV2';
import { desktopTenantCatalogAuthorityDefinitionV2 } from './desktopTenantCatalogAuthorityModuleV2';
import { desktopTenantOverviewAuthorityDefinitionV2 } from './desktopTenantOverviewAuthorityModuleV2';
import { desktopTenantProjectsAuthorityDefinitionV2 } from './desktopTenantProjectsAuthorityModuleV2';
import { desktopWorkspaceAgentBindingAuthorityDefinitionV2 } from './desktopWorkspaceAgentBindingAuthorityModuleV2';
import { desktopWorkspaceAutonomyAttentionAuthorityDefinitionV2 } from './desktopWorkspaceAutonomyAttentionAuthorityModuleV2';
import { desktopWorkspaceMemberMutationAuthorityDefinitionV2 } from './desktopWorkspaceMemberMutationAuthorityModuleV2';
import { desktopWorkspaceContextAuthorityDefinitionV2 } from './desktopWorkspaceContextAuthorityModuleV2';
import { desktopWorkspaceCatalogAuthorityDefinitionV2 } from './desktopWorkspaceCatalogAuthorityModuleV2';
import { desktopWorkspaceLifecycleAuthorityDefinitionV2 } from './desktopWorkspaceLifecycleAuthorityModuleV2';
import { desktopWorkspaceRosterAuthorityDefinitionV2 } from './desktopWorkspaceRosterAuthorityModuleV2';
import { desktopWorkspaceExecutionSnapshotAuthorityDefinitionV2 } from './desktopWorkspaceExecutionSnapshotAuthorityModuleV2';
import {
  desktopWorkspaceConversationCatalogAuthorityDefinitionV2,
} from './desktopWorkspaceConversationCatalogAuthorityModuleV2';
import { desktopWorkspaceMessageCatalogAuthorityDefinitionV2 } from './desktopWorkspaceMessageCatalogAuthorityModuleV2';

const RENDERER_DISTRIBUTION_COMMAND_V2 = 'platform_plugin_renderer_distribution_current_v2';
const POLL_INTERVAL_MS = 30_000;
const desktopRendererRuntimeV2 = new RendererPluginRuntimeV2(
  'desktop-renderer',
  Object.freeze([
    ...createDesktopRendererDefinitionsV2(validateDesktopRendererContributionsV2),
    desktopArtifactContentAuthorityDefinitionV2,
    desktopAutomationAuthorityDefinitionV2,
    desktopPluginMarketplaceCatalogDefinitionV2,
    desktopPluginMarketplaceManagementDefinitionV2,
    desktopConversationConfigAuthorityDefinitionV2,
    desktopConversationLifecycleAuthorityDefinitionV2,
    desktopHitlResponseAuthorityDefinitionV2,
    desktopMyWorkAuthorityDefinitionV2,
    desktopNewTaskFlowAuthorityDefinitionV2,
    desktopNewThreadCreationAuthorityDefinitionV2,
    desktopProjectSearchAuthorityDefinitionV2,
    desktopSessionArtifactActionAuthorityDefinitionV2,
    desktopSessionProjectionAuthorityDefinitionV2,
    desktopSessionRunControlAuthorityDefinitionV2,
    desktopSessionRunChangesAuthorityDefinitionV2,
    desktopSessionRunInputAuthorityDefinitionV2,
    desktopSessionTimelineAuthorityDefinitionV2,
    desktopTerminalLifecycleAuthorityDefinitionV2,
    desktopTenantAgentBindingsAuthorityDefinitionV2,
    desktopTenantAgentDashboardAuthorityDefinitionV2,
    desktopTenantAnalyticsAuthorityDefinitionV2,
    desktopTenantCatalogAuthorityDefinitionV2,
    desktopTenantOverviewAuthorityDefinitionV2,
    desktopTenantProjectsAuthorityDefinitionV2,
    desktopWorkspaceAgentBindingAuthorityDefinitionV2,
    desktopWorkspaceAutonomyAttentionAuthorityDefinitionV2,
    desktopWorkspaceMemberMutationAuthorityDefinitionV2,
    desktopWorkspaceContextAuthorityDefinitionV2,
    desktopWorkspaceCatalogAuthorityDefinitionV2,
    desktopWorkspaceLifecycleAuthorityDefinitionV2,
    desktopWorkspaceRosterAuthorityDefinitionV2,
    desktopWorkspaceConversationCatalogAuthorityDefinitionV2,
    desktopWorkspaceExecutionSnapshotAuthorityDefinitionV2,
    desktopWorkspaceMessageCatalogAuthorityDefinitionV2,
  ])
);
const desktopRendererLeaseStoreV2 = new RendererGenerationLeaseStoreV2(desktopRendererRuntimeV2);
const desktopRendererStatusStoreV2 = new RendererGenerationStatusStoreV2();
const desktopRendererDistributionReconcilerV2 = new DesktopRendererDistributionReconcilerV2(
  desktopRendererRuntimeV2
);
let pendingClose: ReturnType<typeof setTimeout> | null = null;

export function activateDesktopPluginGenerationRootV2(): void {
  desktopRendererLeaseStoreV2.activateRoot();
}

export async function deactivateDesktopPluginGenerationRootV2(): Promise<void> {
  await desktopRendererLeaseStoreV2.deactivateRoot();
}

export function acquireDesktopPluginGenerationLeaseV2(
  generation: RuntimeGenerationV2
): GenerationLeaseV2 {
  return desktopRendererLeaseStoreV2.acquireGeneration(generation);
}

export function useDesktopPluginGenerationV2(
  _config: DesktopRuntimeConfig,
  enabled: boolean
): RendererPluginGenerationStateV2 {
  const snapshot = useSyncExternalStore(
    desktopRendererLeaseStoreV2.subscribe,
    desktopRendererLeaseStoreV2.getSnapshot,
    desktopRendererLeaseStoreV2.getSnapshot
  );
  const status = useSyncExternalStore(
    desktopRendererStatusStoreV2.subscribe,
    desktopRendererStatusStoreV2.getSnapshot,
    desktopRendererStatusStoreV2.getSnapshot
  );
  useLayoutEffect(() => {
    void desktopRendererLeaseStoreV2.commit(snapshot);
  }, [snapshot]);

  useEffect(() => {
    if (pendingClose !== null) {
      clearTimeout(pendingClose);
      pendingClose = null;
    }
    if (!enabled) {
      scheduleClose();
      return;
    }

    const stop = startDesktopPluginGenerationPollingV2(
      desktopRendererRuntimeV2,
      desktopRendererStatusStoreV2
    );
    return () => {
      stop();
      scheduleClose();
    };
  }, [enabled]);

  const state = projectRendererPluginGenerationStateV2(enabled, snapshot.generation, status);
  return state;
}

function startDesktopPluginGenerationPollingV2(
  runtime: RendererPluginRuntimeV2,
  statusStore: RendererGenerationStatusStoreV2
): () => void {
  return startRendererGenerationPollingV2({
    runtime,
    source: fetchDesktopPluginDistributionV2,
    apply: (payload) => desktopRendererDistributionReconcilerV2.apply(payload),
    statusStore,
    pollIntervalMs: POLL_INTERVAL_MS,
  });
}

async function fetchDesktopPluginDistributionV2(signal: AbortSignal): Promise<unknown | null> {
  signal.throwIfAborted();
  const invoke = window.__MEMSTACK_DESKTOP__?.core?.invoke;
  if (invoke === undefined) {
    throw new Error('desktop_renderer_distribution_ipc_unavailable');
  }
  const distribution = await invoke<unknown>(RENDERER_DISTRIBUTION_COMMAND_V2);
  signal.throwIfAborted();
  return distribution ?? null;
}

function scheduleClose(): void {
  pendingClose = setTimeout(() => {
    pendingClose = null;
    void desktopRendererDistributionReconcilerV2.close();
  }, 0);
}
