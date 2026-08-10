import {
  type Dispatch,
  type RefObject,
  type SetStateAction,
} from 'react';

import {
  DesktopApiClient,
} from '../api/client';
import type { CloudSessionProjection } from '../api/cloudSessionProjectionClient';
import type { WorkspaceSsoPresentation } from '../features/auth/LoginScreen';
import type { SettingsSection } from '../features/settings/SettingsWindow';
import type { AgentTaskSignal } from '../features/chat/agentTaskSignalModel';
import {
  type PendingPasswordChangeAttempt,
} from '../features/auth/forcePasswordChangeModel';
import {
  AuthState,
  ConnectionState,
  DesktopRuntimeConfig,
  ProjectSummary,
  RuntimeDataset,
  WorkbenchSection,
} from '../types';
import {
  type AgentConversationSession,
} from '../appShellTypes';
import { useCloudSessionAuth } from './useCloudSessionAuth';
import { useLocalCredentialAuth } from './useLocalCredentialAuth';

export type DesktopAuthParams = {
  runsInNativeDesktop: boolean;
  config: DesktopRuntimeConfig;
  auth: AuthState;
  loginEmail: string;
  loginPassword: string;
  workspaceSso: WorkspaceSsoPresentation | null;
  error: string | null;
  api: DesktopApiClient;
  localRuntimeAuthorityReady: boolean;
  selectedProject: ProjectSummary | null;
  setAuth: Dispatch<SetStateAction<AuthState>>;
  setLoginModalOpen: Dispatch<SetStateAction<boolean>>;
  setSettingsWindowOpen: Dispatch<SetStateAction<boolean>>;
  setSettingsInitialSection: Dispatch<SetStateAction<SettingsSection>>;
  setLoginEmail: Dispatch<SetStateAction<string>>;
  setLoginPassword: Dispatch<SetStateAction<string>>;
  setWorkspaceSso: Dispatch<SetStateAction<WorkspaceSsoPresentation | null>>;
  setDataset: Dispatch<SetStateAction<RuntimeDataset>>;
  setConnection: Dispatch<SetStateAction<ConnectionState>>;
  setError: Dispatch<SetStateAction<string | null>>;
  setLastSync: Dispatch<SetStateAction<string>>;
  setActiveSection: Dispatch<SetStateAction<WorkbenchSection>>;
  setSectionBackStack: Dispatch<SetStateAction<WorkbenchSection[]>>;
  setSectionForwardStack: Dispatch<SetStateAction<WorkbenchSection[]>>;
  setAgentConversationSession: Dispatch<
    SetStateAction<AgentConversationSession | null>
  >;
  setAgentTaskSignals: Dispatch<SetStateAction<AgentTaskSignal[]>>;
  activeSectionRef: RefObject<WorkbenchSection>;
  contextRevisionRef: RefObject<number>;
  configRef: RefObject<DesktopRuntimeConfig>;
  localResumeAttemptRef: RefObject<string>;
  authAttemptRevisionRef: RefObject<number>;
  pendingPasswordChangeRef: RefObject<PendingPasswordChangeAttempt | null>;
  deviceAuthAttemptIdRef: RefObject<number>;
  deviceAuthAttemptRef: RefObject<{
    attemptId: number;
    nativeAttemptId?: string;
    authRevision: number;
    controller: AbortController;
    authorizationUrl: string;
    userCode: string;
    openInFlight: boolean;
  } | null>;
  commitRuntimeConfig: (nextConfig: DesktopRuntimeConfig) => void;
  nativeOAuthResumeRoute: () => string;
  onNativeOAuthAuthenticated: (
    resumeRoute: string,
    projection: CloudSessionProjection,
  ) => void;
  resetConversationTimeline: () => void;
  resetProjectScopedState: () => void;
  refreshRuntime: (
    nextConfig?: DesktopRuntimeConfig,
    projectOverride?: ProjectSummary[],
  ) => Promise<boolean>;
  applySectionSideEffects: (section: WorkbenchSection) => void;
};

export function useDesktopAuth(params: DesktopAuthParams) {
  const {
    cancelWorkspaceSso,
    beginNativeOAuth,
    hydrateCloudSession,
    hydrateProjectedCloudSession,
    loginWithWorkspaceSso,
    nativeOAuthPendingProvider,
    nativeOAuthProviders,
    openCurrentWorkspaceSso,
    revokeUnadoptedDeviceToken,
    supersedeWorkspaceSsoAttempt,
  } = useCloudSessionAuth(params);
  const {
    cancelForcedPasswordChange,
    changeLoginMode,
    handleConfigChange,
    hydrateLocalSession,
    login,
    loginLocalSession,
    logout,
    submitForcedPasswordChange,
    useApiKeyManually,
  } = useLocalCredentialAuth(params, {
    hydrateCloudSession,
    hydrateProjectedCloudSession,
    revokeUnadoptedDeviceToken,
    supersedeWorkspaceSsoAttempt,
  });
  return {
    cancelForcedPasswordChange,
    cancelWorkspaceSso,
    beginNativeOAuth,
    changeLoginMode,
    handleConfigChange,
    hydrateCloudSession,
    hydrateProjectedCloudSession,
    hydrateLocalSession,
    login,
    loginLocalSession,
    loginWithWorkspaceSso,
    nativeOAuthPendingProvider,
    nativeOAuthProviders,
    logout,
    openCurrentWorkspaceSso,
    submitForcedPasswordChange,
    useApiKeyManually,
  };
}
