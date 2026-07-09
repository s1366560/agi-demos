import {
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
  type RefObject,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { createPortal } from 'react-dom';
import {
  Badge,
  Box,
  Button,
  Flex,
  Heading,
  IconButton,
  Text,
  Theme,
  Tooltip,
} from '@radix-ui/themes';
import {
  ActivityLogIcon,
  ArchiveIcon,
  ChatBubbleIcon,
  CheckCircledIcon,
  CodeIcon,
  CommitIcon,
  ChevronDownIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  ColumnsIcon,
  Cross2Icon,
  DashboardIcon,
  DotsHorizontalIcon,
  DesktopIcon,
  EnterFullScreenIcon,
  ExitFullScreenIcon,
  FileTextIcon,
  FrameIcon,
  GearIcon,
  GridIcon,
  MagnifyingGlassIcon,
  MixerHorizontalIcon,
  PlayIcon,
  PlusIcon,
  ReaderIcon,
  RocketIcon,
  ExclamationTriangleIcon,
  ViewVerticalIcon,
} from '@radix-ui/react-icons';

import { DesktopApiClient } from './api/client';
import {
  ingestLocalMemory,
  searchLocalMemory,
  semanticSearchLocalMemory,
} from './api/localMemory';
import { AuthPanel } from './features/auth/AuthPanel';
import { BoardPanel } from './features/board/BoardPanel';
import {
  ChatPanel,
  type AgentTaskSignal,
  type AgentTaskSignalStatus,
  type ChatWorkflowTarget,
} from './features/chat/ChatPanel';
import { ComposerControls } from './features/chat/ComposerControls';
import { RuntimeConfigPanel } from './features/runtime/RuntimeConfigPanel';
import { StatusPanel } from './features/status/StatusPanel';
import { WorkspaceDock } from './features/workspace/WorkspaceDock';
import { useAgentSocket } from './hooks/useAgentSocket';
import { useTerminalProxy } from './hooks/useTerminalProxy';
import type {
  AgentConversation,
  AuthState,
  BoardMode,
  ConnectionState,
  DesktopRuntimeConfig,
  DesktopServiceResponse,
  LocalMemoryResult,
  ProjectSandbox,
  RuntimeDataset,
  StatusTab,
  TerminalServiceResponse,
  WorkbenchSection,
  WorkspaceTask,
} from './types';
import { DEFAULT_CONFIG } from './types';

const emptyDataset: RuntimeDataset = {
  workspaces: [],
  messages: [],
  tasks: [],
  plan: null,
  sandbox: null,
};

const emptyAuthState: AuthState = {
  status: 'signed_out',
  user: null,
  tenants: [],
  projects: [],
  mustChangePassword: false,
  error: null,
};

const DEFAULT_WORKSPACE_NAME = 'Desktop workspace';

const formatDesktopWorkspaceName = () => {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, '0');
  const date = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
  const time = `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
  return `${DEFAULT_WORKSPACE_NAME} ${date} ${time}`;
};

const resolveNewWorkspaceName = (draft: string) => {
  const trimmed = draft.trim();
  return !trimmed || trimmed === DEFAULT_WORKSPACE_NAME ? formatDesktopWorkspaceName() : trimmed;
};

type CommandPaletteItem = {
  id: string;
  label: string;
  description: string;
  icon: ReactNode;
  shortcut?: string;
  disabled?: boolean;
  onSelect: () => void;
};

type WorkflowTarget =
  | 'changes'
  | 'pull'
  | 'plan'
  | 'board'
  | 'background'
  | 'artifacts'
  | 'runtime';
type SessionGroupMode = 'recent' | 'project';
type SessionScopeKind = 'project' | 'worktree' | 'branch';
type ComposerReferenceKind = 'files' | 'issues';
type MobileTitlebarMenuItem = {
  id: string;
  label: string;
  icon: ReactNode;
  selected?: boolean;
  disabled?: boolean;
  onSelect: () => void;
};
type ReviewTab =
  | 'changes'
  | 'pull'
  | 'plan'
  | 'background'
  | 'artifacts'
  | 'terminal';

type AgentConversationSession = {
  scopeKey: string;
  conversation: AgentConversation;
};

type AgentTaskSignalPatch = Partial<Omit<AgentTaskSignal, 'id'>> & {
  id: string;
};

function detectTauriShell(): boolean {
  if (typeof window === 'undefined') return false;
  return Boolean(
    window.__TAURI__?.core?.invoke ||
      window.__TAURI_INTERNALS__ ||
      document.documentElement.hasAttribute('data-tauri-window'),
  );
}

const composerReferenceOptions: Record<
  ComposerReferenceKind,
  Array<{ id: string; label: string; description: string; icon: ReactNode }>
> = {
  files: [
    {
      id: 'readme',
      label: 'README.md',
      description: 'Project quick start and desktop run notes.',
      icon: <FileTextIcon />,
    },
    {
      id: 'desktop-app',
      label: 'apps/desktop/src/App.tsx',
      description: 'Desktop shell, command palette, and signed-out composer.',
      icon: <CodeIcon />,
    },
    {
      id: 'styles',
      label: 'apps/desktop/src/styles.css',
      description: 'Copilot-like layout, popovers, and responsive polish.',
      icon: <MixerHorizontalIcon />,
    },
  ],
  issues: [
    {
      id: 'login',
      label: '#desktop-login',
      description: 'Sign-in flow, account scope, and session readiness.',
      icon: <ChatBubbleIcon />,
    },
    {
      id: 'sandbox',
      label: '#sandbox-terminal',
      description: 'Workspace shell, desktop view, and sandbox health.',
      icon: <DesktopIcon />,
    },
    {
      id: 'figma',
      label: '#figma-design',
      description: 'Design capture and componentized desktop screen work.',
      icon: <FrameIcon />,
    },
  ],
};

const sessionScopeOptions: Record<SessionScopeKind, string[]> = {
  project: ['No project', 'Connect project', 'Manual API key'],
  worktree: ['New worktree', 'Current worktree', 'Review worktree'],
  branch: ['Default branch', 'Current branch', 'Review branch'],
};

function sessionScopeOptionId(kind: SessionScopeKind, option: string): string {
  const normalized = option.toLowerCase().replace(/[^a-z0-9]+/g, '-');
  return `session-scope-option-${kind}-${normalized}`;
}

function mobileMenuOptionId(id: string): string {
  const normalized = id.toLowerCase().replace(/[^a-z0-9]+/g, '-');
  return `mobile-section-option-${normalized}`;
}

function isEditableEventTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  return Boolean(target.closest('input, textarea, select, [contenteditable="true"]'));
}

function agentConversationScopeKey(config: DesktopRuntimeConfig): string {
  return `${config.projectId.trim()}::${config.workspaceId.trim()}`;
}

function agentTaskUpdateFromSocketEvent(
  event: unknown,
): null | {
  conversationId: string;
  status: AgentTaskSignalStatus;
  detail: string;
  eventType: string;
} {
  if (!event || typeof event !== 'object') return null;
  const payload = event as Record<string, unknown>;
  const conversationId = readStringField(payload, 'conversation_id');
  if (!conversationId) return null;

  const type = readStringField(payload, 'type') ?? readStringField(payload, 'event_type') ?? 'event';
  const action = readStringField(payload, 'action');
  const eventType = action ? `${type}:${action}` : type;

  if (type === 'ack' && action === 'send_message') {
    return {
      conversationId,
      status: 'acknowledged',
      detail: 'Agent acknowledged the task over WebSocket.',
      eventType,
    };
  }

  if (type === 'user_message' || type === 'message') {
    return {
      conversationId,
      status: 'acknowledged',
      detail: 'Agent conversation received the task message.',
      eventType,
    };
  }

  if (type.toLowerCase().includes('error') || action?.toLowerCase().includes('error')) {
    const errorDetail = socketErrorDetail(payload);
    return {
      conversationId,
      status: 'failed',
      detail: errorDetail
        ? `Agent reported an error for this task: ${errorDetail}`
        : 'Agent reported an error for this task.',
      eventType,
    };
  }

  return null;
}

function socketErrorDetail(payload: Record<string, unknown>): string | undefined {
  const direct =
    readStringField(payload, 'detail') ??
    readStringField(payload, 'message') ??
    readStringField(payload, 'error') ??
    readStringField(payload, 'reason');
  if (direct) return direct;

  const nested = payload.payload;
  if (nested && typeof nested === 'object') {
    return socketErrorDetail(nested as Record<string, unknown>);
  }

  return undefined;
}

function readStringField(payload: Record<string, unknown>, key: string): string | undefined {
  const value = payload[key];
  return typeof value === 'string' && value.trim() ? value : undefined;
}

export function App() {
  const runsInTauri = detectTauriShell();
  const [config, setConfig] = useState<DesktopRuntimeConfig>(DEFAULT_CONFIG);
  const [runtimeApiKeyFocusSignal, setRuntimeApiKeyFocusSignal] = useState(0);
  const [auth, setAuth] = useState<AuthState>(emptyAuthState);
  const [loginModalOpen, setLoginModalOpen] = useState(false);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [commandQuery, setCommandQuery] = useState('');
  const commandInputRef = useRef<HTMLInputElement>(null);
  const commandPaletteTriggerRef = useRef<HTMLElement | null>(null);
  const appShellRef = useRef<HTMLDivElement>(null);
  const loginRestoreTargetRef = useRef<HTMLElement | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sessionMenuOpen, setSessionMenuOpen] = useState(false);
  const [mobileSectionMenuOpen, setMobileSectionMenuOpen] = useState(false);
  const [activeMobileMenuItemId, setActiveMobileMenuItemId] = useState<string | null>(null);
  const mobileSectionButtonRef = useRef<HTMLButtonElement>(null);
  const mobileSectionMenuRef = useRef<HTMLDivElement>(null);
  const mobileTitlebarItemsRef = useRef<MobileTitlebarMenuItem[]>([]);
  const activeMobileMenuOptionId = activeMobileMenuItemId
    ? mobileMenuOptionId(activeMobileMenuItemId)
    : undefined;
  const [sessionGroupMode, setSessionGroupMode] = useState<SessionGroupMode>('project');
  const [loginEmail, setLoginEmail] = useState('');
  const [loginPassword, setLoginPassword] = useState('');
  const [dataset, setDataset] = useState<RuntimeDataset>(emptyDataset);
  const [connection, setConnection] = useState<ConnectionState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [lastSync, setLastSync] = useState<string>('never');
  const [chatInput, setChatInput] = useState('');
  const [sending, setSending] = useState(false);
  const [activeSection, setActiveSection] = useState<WorkbenchSection>('workspace');
  const activeSectionRef = useRef<WorkbenchSection>('workspace');
  const [sectionBackStack, setSectionBackStack] = useState<WorkbenchSection[]>([]);
  const [sectionForwardStack, setSectionForwardStack] = useState<WorkbenchSection[]>([]);
  const [reviewTab, setReviewTab] = useState<ReviewTab>('plan');
  const [reviewPanelOpen, setReviewPanelOpen] = useState(true);
  const [boardMode, setBoardMode] = useState<BoardMode>('flow');
  const [selectedTaskId, setSelectedTaskId] = useState('');
  const [statusTab, setStatusTab] = useState<StatusTab>('overview');
  const [sandboxBusy, setSandboxBusy] = useState(false);
  const [desktop, setDesktop] = useState<DesktopServiceResponse | null>(null);
  const [terminal, setTerminal] = useState<TerminalServiceResponse | null>(null);
  const [terminalInput, setTerminalInput] = useState('');
  const [memoryContent, setMemoryContent] = useState('Local-first desktop workspace smoke record');
  const [memoryQuery, setMemoryQuery] = useState('desktop workspace');
  const [memoryBusy, setMemoryBusy] = useState(false);
  const [memoryResult, setMemoryResult] = useState<LocalMemoryResult | null>(null);
  const [newWorkspaceName, setNewWorkspaceName] = useState(DEFAULT_WORKSPACE_NAME);
  const [creatingWorkspace, setCreatingWorkspace] = useState(false);
  const [agentConversationSession, setAgentConversationSession] =
    useState<AgentConversationSession | null>(null);
  const [agentTaskSignals, setAgentTaskSignals] = useState<AgentTaskSignal[]>([]);

  const api = useMemo(() => new DesktopApiClient(config), [config]);
  const socket = useAgentSocket(config, connection === 'ready');
  const terminalUrl = useMemo(() => {
    if (!terminal?.success || !terminal.session_id) return null;
    try {
      return api.terminalProxyUrl(terminal.session_id);
    } catch {
      return null;
    }
  }, [api, terminal?.session_id, terminal?.success]);
  const terminalProxy = useTerminalProxy(terminalUrl);
  const desktopFrameUrl = useMemo(() => {
    if (!desktop?.success) return null;
    try {
      return api.desktopProxyUrl();
    } catch {
      return null;
    }
  }, [api, desktop?.success]);
  const modalOpen = loginModalOpen || commandPaletteOpen;

  const selectedTask = useMemo(
    () => dataset.tasks.find((task) => task.id === selectedTaskId) ?? dataset.tasks[0] ?? null,
    [dataset.tasks, selectedTaskId],
  );
  const upsertAgentTaskSignal = useCallback((patch: AgentTaskSignalPatch) => {
    setAgentTaskSignals((current) => {
      const existing = current.find((signal) => signal.id === patch.id);
      const next: AgentTaskSignal = {
        id: patch.id,
        content: patch.content ?? existing?.content ?? '',
        status: patch.status ?? existing?.status ?? 'queued',
        detail: patch.detail ?? existing?.detail ?? '',
        createdAt: patch.createdAt ?? existing?.createdAt ?? new Date().toISOString(),
        conversationId: patch.conversationId ?? existing?.conversationId,
        messageId: patch.messageId ?? existing?.messageId,
        eventType: patch.eventType ?? existing?.eventType,
      };
      return [...current.filter((signal) => signal.id !== patch.id), next].slice(-8);
    });
  }, []);

  const openCommandPalette = useCallback((trigger?: HTMLElement | null) => {
    commandPaletteTriggerRef.current =
      trigger ??
      (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    setSessionMenuOpen(false);
    setMobileSectionMenuOpen(false);
    setActiveMobileMenuItemId(null);
    setCommandPaletteOpen(true);
  }, []);

  const closeCommandPalette = useCallback((restoreFocus = false) => {
    const trigger = commandPaletteTriggerRef.current;
    setCommandPaletteOpen(false);
    setCommandQuery('');
    commandPaletteTriggerRef.current = null;
    if (restoreFocus && trigger?.isConnected) {
      window.requestAnimationFrame(() => {
        window.requestAnimationFrame(() => {
          if (trigger.isConnected) {
            trigger.focus();
          }
        });
      });
    }
  }, []);

  const getLoginRestoreTarget = useCallback(() => {
    if (loginRestoreTargetRef.current?.isConnected) {
      return loginRestoreTargetRef.current;
    }
    return (
      document.querySelector<HTMLElement>('[aria-label="Open command palette"]') ??
      document.querySelector<HTMLElement>('[aria-label="Sign in to agi-stack"]')
    );
  }, []);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented) return;
      const key = event.key.toLowerCase();
      if ((event.metaKey || event.ctrlKey) && key === 'k') {
        event.preventDefault();
        openCommandPalette();
        return;
      }
      if (
        event.key === '/' &&
        !event.metaKey &&
        !event.ctrlKey &&
        !event.altKey &&
        !commandPaletteOpen &&
        !loginModalOpen &&
        !isEditableEventTarget(event.target)
      ) {
        event.preventDefault();
        setCommandQuery('');
        openCommandPalette();
        return;
      }
      if (event.key === 'Escape' && commandPaletteOpen) {
        event.preventDefault();
        closeCommandPalette(true);
      }
      if (event.key === 'Escape' && sessionMenuOpen) {
        event.preventDefault();
        setSessionMenuOpen(false);
      }
      if (event.key === 'Escape' && mobileSectionMenuOpen) {
        event.preventDefault();
        setMobileSectionMenuOpen(false);
        setActiveMobileMenuItemId(null);
        mobileSectionButtonRef.current?.focus();
        return;
      }
      if (
        mobileSectionMenuOpen &&
        ['ArrowDown', 'ArrowUp', 'Home', 'End', 'Enter', ' '].includes(event.key)
      ) {
        const enabledItems = mobileTitlebarItemsRef.current.filter((item) => !item.disabled);
        if (!enabledItems.length) return;
        event.preventDefault();
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
          const delta = event.key === 'ArrowDown' ? 1 : -1;
          setActiveMobileMenuItemId((current) => {
            const currentIndex = enabledItems.findIndex((item) => item.id === current);
            const startIndex = currentIndex === -1 ? (delta > 0 ? -1 : 0) : currentIndex;
            const nextIndex = (startIndex + delta + enabledItems.length) % enabledItems.length;
            return enabledItems[nextIndex].id;
          });
          return;
        }
        if (event.key === 'Home' || event.key === 'End') {
          setActiveMobileMenuItemId(
            event.key === 'Home' ? enabledItems[0].id : enabledItems[enabledItems.length - 1].id,
          );
          return;
        }
        const activeItem =
          enabledItems.find((item) => item.id === activeMobileMenuItemId) ?? enabledItems[0];
        activeItem.onSelect();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [
    activeMobileMenuItemId,
    closeCommandPalette,
    commandPaletteOpen,
    loginModalOpen,
    mobileSectionMenuOpen,
    openCommandPalette,
    sessionMenuOpen,
  ]);

  useEffect(() => {
    const shell = appShellRef.current;
    if (!shell) return;
    const backgroundRoots = [
      document.getElementById('root'),
      shell.parentElement,
      shell,
    ].filter(
      (element, index, elements): element is HTMLElement =>
        element instanceof HTMLElement && elements.indexOf(element) === index,
    );

    if (modalOpen) {
      backgroundRoots.forEach((element) => {
        element.setAttribute('aria-hidden', 'true');
        element.setAttribute('inert', '');
      });
      return;
    }

    backgroundRoots.forEach((element) => {
      element.removeAttribute('aria-hidden');
      element.removeAttribute('inert');
    });
  }, [modalOpen]);

  useEffect(() => {
    if (!mobileSectionMenuOpen) return;

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (mobileSectionMenuRef.current?.contains(target)) return;
      if (mobileSectionButtonRef.current?.contains(target)) return;
      setMobileSectionMenuOpen(false);
      setActiveMobileMenuItemId(null);
    };

    document.addEventListener('pointerdown', handlePointerDown);
    return () => document.removeEventListener('pointerdown', handlePointerDown);
  }, [mobileSectionMenuOpen]);

  useEffect(() => {
    if (!mobileSectionMenuOpen || !activeMobileMenuOptionId) return;
    const activeOption = document.getElementById(activeMobileMenuOptionId);
    activeOption?.scrollIntoView({ block: 'nearest' });
    if (activeOption instanceof HTMLElement && document.activeElement !== activeOption) {
      activeOption.focus({ preventScroll: true });
    }
  }, [activeMobileMenuOptionId, mobileSectionMenuOpen]);

  useEffect(() => {
    if (!commandPaletteOpen) return;
    window.requestAnimationFrame(() => commandInputRef.current?.focus());
  }, [commandPaletteOpen]);

  useEffect(() => {
    const update = agentTaskUpdateFromSocketEvent(socket.events[0]);
    if (!update) return;
    setAgentTaskSignals((current) => {
      let changed = false;
      const next = current.map((signal) => {
        if (signal.conversationId !== update.conversationId || signal.status === 'failed') {
          return signal;
        }
        changed = true;
        return {
          ...signal,
          status: update.status,
          detail: update.detail,
          eventType: update.eventType,
        };
      });
      return changed ? next : current;
    });
  }, [socket.events]);

  const showRuntimeConfig = auth.status === 'signed_in' || auth.status === 'manual';
  const showReviewPanel = showRuntimeConfig && reviewPanelOpen;
  const runtimeDisabledReason = !showRuntimeConfig
    ? 'Sign in or use a manual API key before connecting.'
    : !config.apiKey.trim()
      ? 'Enter an API key or sign in before connecting.'
      : !config.tenantId.trim() || !config.projectId.trim()
        ? 'Select an account and project before connecting.'
        : null;
  const workspaceDisabledReason = !showRuntimeConfig
    ? 'Sign in or use a manual API key before loading workspaces.'
    : !config.apiKey.trim()
      ? 'Enter an API key before loading workspaces.'
      : !config.tenantId.trim() || !config.projectId.trim()
        ? 'Select an account and project before loading workspaces.'
        : null;
  const sandboxDisabledReason = !showRuntimeConfig
    ? 'Sign in or use a manual API key before starting sandbox services.'
    : !config.apiKey.trim()
      ? 'Enter an API key before starting sandbox services.'
      : !config.projectId.trim()
        ? 'Select a project before starting sandbox services.'
        : null;
  const chatDisabledReason = !showRuntimeConfig
    ? 'Sign in or enter an API key before sending messages.'
    : !config.apiKey.trim()
      ? 'Enter an API key before sending messages.'
      : !config.tenantId.trim() || !config.projectId.trim()
        ? 'Select an account and project before chatting.'
    : !config.workspaceId
      ? 'Create or select a workspace before sending messages.'
      : connection !== 'ready'
        ? 'Connect the workspace before sending messages.'
        : null;

  useEffect(() => {
    if (!dataset.tasks.length) {
      setSelectedTaskId('');
      return;
    }
    if (!dataset.tasks.some((task) => task.id === selectedTaskId)) {
      setSelectedTaskId(dataset.tasks[0].id);
    }
  }, [dataset.tasks, selectedTaskId]);

  const refreshRuntime = useCallback(
    async (nextConfig: DesktopRuntimeConfig = config) => {
      setConnection('loading');
      setError(null);
      try {
        const baseClient = new DesktopApiClient(nextConfig);
        const workspaces = await baseClient.listWorkspaces();
        const workspaceId = nextConfig.workspaceId.trim() || workspaces[0]?.id || '';
        const resolvedConfig = { ...nextConfig, workspaceId };
        const scopedClient = new DesktopApiClient(resolvedConfig);
        const [messages, tasks, plan] = await Promise.all([
          workspaceId ? scopedClient.listMessages() : Promise.resolve([]),
          workspaceId ? scopedClient.listTasks() : Promise.resolve([]),
          workspaceId ? scopedClient.getPlanSnapshot().catch(() => null) : Promise.resolve(null),
        ]);

        setConfig(resolvedConfig);
        setDataset({ workspaces, messages, tasks, plan, sandbox: null });
        setConnection('ready');
        setLastSync(new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
      } catch (caught) {
        setConnection('error');
        setError(formatConnectionError(caught, nextConfig.apiBaseUrl));
      }
    },
    [config],
  );

  const login = async () => {
    const username = loginEmail.trim();
    if (!username || !loginPassword) return;

    setAuth((current) => ({ ...current, status: 'signing_in', error: null }));
    setConnection('loading');
    setError(null);
    try {
      const loginClient = new DesktopApiClient({ ...config, apiKey: '' });
      const outcome = await loginClient.login(username, loginPassword);
      const tokenConfig = { ...config, apiKey: outcome.access_token, workspaceId: '' };
      const identityClient = new DesktopApiClient(tokenConfig);
      const [user, tenants] = await Promise.all([
        identityClient.currentUser(),
        identityClient.listTenants(),
      ]);
      const firstTenantId = tenants[0]?.id ?? '';
      const projectClient = new DesktopApiClient({ ...tokenConfig, tenantId: firstTenantId });
      const projects = await projectClient.listProjects(firstTenantId || undefined);
      const tenantId = firstTenantId || projects[0]?.tenant_id || '';
      const projectId = projects[0]?.id ?? '';
      const nextConfig = { ...tokenConfig, tenantId, projectId, workspaceId: '' };

      setConfig(nextConfig);
      setAuth({
        status: 'signed_in',
        user,
        tenants,
        projects,
        mustChangePassword: outcome.must_change_password,
        error: null,
      });
      setLoginPassword('');

      if (projectId) {
        await refreshRuntime(nextConfig);
        applySectionSideEffects('chat');
      } else {
        setDataset(emptyDataset);
        setConnection('ready');
        setLastSync(new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
        applySectionSideEffects('settings');
      }
    } catch (caught) {
      const message = formatLoginError(caught, config.apiBaseUrl);
      setAuth({ ...emptyAuthState, error: message });
      setConnection('error');
      setError(message);
    }
  };

  const handleConfigChange = (nextConfig: DesktopRuntimeConfig) => {
    setConfig(nextConfig);
    setConnection('idle');
    setAgentConversationSession(null);
    setAgentTaskSignals([]);
  };

  const useApiKeyManually = () => {
    setAuth({ ...emptyAuthState, status: 'manual' });
    setLoginModalOpen(false);
    setConnection('idle');
    setError(null);
    setSectionBackStack([]);
    setSectionForwardStack([]);
    setAgentTaskSignals([]);
    applySectionSideEffects('settings');
    setRuntimeApiKeyFocusSignal((signal) => signal + 1);
  };

  const logout = () => {
    setAuth(emptyAuthState);
    setLoginModalOpen(false);
    setConfig({ ...DEFAULT_CONFIG, apiBaseUrl: config.apiBaseUrl, mode: config.mode });
    setDataset(emptyDataset);
    setConnection('idle');
    setError(null);
    setLastSync('never');
    setChatInput('');
    setSectionBackStack([]);
    setSectionForwardStack([]);
    setSelectedTaskId('');
    setDesktop(null);
    setTerminal(null);
    setTerminalInput('');
    setAgentConversationSession(null);
    setAgentTaskSignals([]);
    setNewWorkspaceName(DEFAULT_WORKSPACE_NAME);
    setActiveSection('workspace');
    setStatusTab('overview');
    terminalProxy.clear();
  };

  const selectWorkspace = (workspaceId: string) => {
    const nextConfig = { ...config, workspaceId };
    setConfig(nextConfig);
    setAgentConversationSession(null);
    setAgentTaskSignals([]);
    void refreshRuntime(nextConfig);
  };

  const createWorkspace = async () => {
    const name = resolveNewWorkspaceName(newWorkspaceName);
    setCreatingWorkspace(true);
    setError(null);
    try {
      const created = await api.createWorkspace(name, 'Created from agi-stack Desktop');
      const nextConfig = { ...config, workspaceId: created.id };
      setConfig(nextConfig);
      setAgentConversationSession(null);
      setAgentTaskSignals([]);
      setNewWorkspaceName(DEFAULT_WORKSPACE_NAME);
      applySectionSideEffects('chat');
      await refreshRuntime(nextConfig);
    } catch (caught) {
      setError(formatConnectionError(caught, config.apiBaseUrl));
    } finally {
      setCreatingWorkspace(false);
    }
  };

  const startNewSession = () => {
    setError(null);
    setLoginModalOpen(false);
    setCommandPaletteOpen(false);
    setCommandQuery('');
    setChatInput('');
    setSelectedTaskId('');
    setAgentTaskSignals([]);
    setStatusTab('overview');
    setReviewTab('plan');
    setSectionBackStack([]);
    setSectionForwardStack([]);

    if (showRuntimeConfig && !workspaceDisabledReason) {
      void createWorkspace();
      return;
    }

    applySectionSideEffects('workspace');
  };

  const ensureAgentConversation = async (firstMessage: string): Promise<AgentConversation> => {
    const scopeKey = agentConversationScopeKey(config);
    if (
      agentConversationSession?.scopeKey === scopeKey &&
      agentConversationSession.conversation.project_id === config.projectId.trim()
    ) {
      return agentConversationSession.conversation;
    }

    const workspace = dataset.workspaces.find((item) => item.id === config.workspaceId.trim());
    const workspaceLabel = workspace?.name || workspace?.title || 'Desktop workspace';
    const titleSource = firstMessage.length > 42 ? `${firstMessage.slice(0, 39)}...` : firstMessage;
    const created = await api.createAgentConversation(`${workspaceLabel}: ${titleSource}`);
    const conversation = config.workspaceId.trim()
      ? await api.updateAgentConversationMode(created.id, {
          workspace_id: config.workspaceId.trim(),
        })
      : created;
    setAgentConversationSession({ scopeKey, conversation });
    socket.subscribeConversation(conversation.id);
    return conversation;
  };

  const sendMessage = async () => {
    const content = chatInput.trim();
    if (!content) return;
    setSending(true);
    setError(null);
    const signalId = `agent-task-${Date.now()}`;
    upsertAgentTaskSignal({
      id: signalId,
      content,
      status: 'saving',
      detail: 'Saving workspace message before handing it to the Agent.',
      createdAt: new Date().toISOString(),
    });
    try {
      const saved = await api.sendMessage(content);
      setDataset((current) => ({ ...current, messages: [...current.messages, saved] }));
      setChatInput('');
      upsertAgentTaskSignal({
        id: signalId,
        messageId: saved.id,
        status: 'queued',
        detail: 'Workspace message saved. Opening the Agent conversation.',
      });

      if (config.projectId.trim()) {
        try {
          const conversation = await ensureAgentConversation(content);
          const messageId = saved.id || `desktop-${Date.now()}`;
          upsertAgentTaskSignal({
            id: signalId,
            conversationId: conversation.id,
            messageId,
            status: 'queued',
            detail: 'Agent conversation opened. Sending task over WebSocket.',
          });
          const queued = socket.sendAgentMessage({
            conversationId: conversation.id,
            projectId: config.projectId,
            message: content,
            messageId,
          });
          if (!queued) {
            const websocketMessage = 'Message saved, but the Agent WebSocket is not connected yet.';
            setError(websocketMessage);
            upsertAgentTaskSignal({
              id: signalId,
              status: 'failed',
              detail: websocketMessage,
            });
          } else {
            upsertAgentTaskSignal({
              id: signalId,
              status: 'queued',
              detail: 'Task sent to Agent. Waiting for acknowledgement.',
            });
          }
        } catch (agentError) {
          const detail = `Message saved, but Agent launch failed: ${formatConnectionError(
            agentError,
            config.apiBaseUrl,
          )}`;
          setError(detail);
          upsertAgentTaskSignal({
            id: signalId,
            status: 'failed',
            detail,
          });
        }
      } else {
        upsertAgentTaskSignal({
          id: signalId,
          status: 'failed',
          detail: 'Message saved, but no project is selected for Agent launch.',
        });
      }
    } catch (caught) {
      const detail = formatConnectionError(caught, config.apiBaseUrl);
      setError(detail);
      upsertAgentTaskSignal({
        id: signalId,
        status: 'failed',
        detail,
      });
    } finally {
      setSending(false);
    }
  };

  const ensureSandbox = async () => {
    await runSandboxAction(async () => {
      const sandbox = await api.ensureSandbox();
      setDataset((current) => ({ ...current, sandbox }));
    });
  };

  const startDesktop = async () => {
    await runSandboxAction(async () => {
      await api.seedProxyAuthCookie();
      const response = await api.startDesktop();
      setDesktop(response);
      const sandbox = await api.getSandbox().catch(() => dataset.sandbox);
      setDataset((current) => ({ ...current, sandbox }));
      setStatusTab('sandbox');
    });
  };

  const startTerminal = async () => {
    await runSandboxAction(async () => {
      await api.seedProxyAuthCookie();
      const response = await api.startTerminal();
      setTerminal(response);
      setStatusTab('sandbox');
    });
  };

  const runSandboxAction = async (action: () => Promise<void>) => {
    setSandboxBusy(true);
    setError(null);
    try {
      await action();
    } catch (caught) {
      setError(formatConnectionError(caught, config.apiBaseUrl));
    } finally {
      setSandboxBusy(false);
    }
  };

  const sendTerminalInput = () => {
    const input = terminalInput.trimEnd();
    if (!input) return;
    terminalProxy.sendInput(`${input}\n`);
    setTerminalInput('');
  };

  const runMemoryAction = async (action: () => Promise<LocalMemoryResult>) => {
    setMemoryBusy(true);
    setError(null);
    try {
      setMemoryResult(await action());
    } catch (caught) {
      setMemoryResult({ label: 'Error', usedFallback: false, data: formatError(caught) });
    } finally {
      setMemoryBusy(false);
    }
  };

  const memoryProjectId = config.projectId.trim() || 'desktop-local';
  const memoryAuthorId = auth.user?.user_id ?? 'desktop-user';
  const paneStageClassName = 'pane-stage single-stage';
  const selectedWorkspace = useMemo(
    () => dataset.workspaces.find((workspace) => workspace.id === config.workspaceId) ?? null,
    [config.workspaceId, dataset.workspaces],
  );
  const selectedProject = useMemo(
    () => auth.projects.find((project) => project.id === config.projectId) ?? null,
    [auth.projects, config.projectId],
  );
  const sidebarProjectLabel = selectedProject?.name || config.projectId.trim() || 'Project';
  const hasWorkspaceScope = Boolean(config.workspaceId.trim());
  const hasProjectScope = Boolean(config.projectId.trim());
  const visibleWorkspaces = useMemo(() => {
    const timestamp = (value: string | undefined) => (value ? Date.parse(value) || 0 : 0);
    return [...dataset.workspaces].sort((left, right) => {
      if (left.id === config.workspaceId) return -1;
      if (right.id === config.workspaceId) return 1;
      if (sessionGroupMode === 'recent') {
        return (
          Math.max(timestamp(right.updated_at), timestamp(right.created_at)) -
          Math.max(timestamp(left.updated_at), timestamp(left.created_at))
        );
      }
      const leftProject = left.project_id ?? '';
      const rightProject = right.project_id ?? '';
      if (leftProject !== rightProject) return leftProject.localeCompare(rightProject);
      return workspaceLabel(left).localeCompare(workspaceLabel(right));
    });
  }, [config.workspaceId, dataset.workspaces, sessionGroupMode]);
  const sessionTitle =
    selectedWorkspace?.name ??
    selectedWorkspace?.title ??
    selectedWorkspace?.id ??
    (showRuntimeConfig ? 'Connection setup' : 'New session');
  const sessionInfoLabel = hasWorkspaceScope
    ? config.workspaceId.trim()
    : hasProjectScope
      ? config.projectId.trim()
      : 'Not connected';
  const authStatusLabel =
    auth.status === 'signed_in'
      ? auth.user?.email ?? 'signed in'
      : auth.status === 'manual'
        ? 'manual API key'
        : 'signed out';
  const sessionGroupLabel = sessionGroupMode === 'recent' ? 'Recent first' : 'Project folders';
  const quickLinkItems: Array<[WorkbenchSection, string, ReactNode, string?]> = [
    ['workspace', 'Home', <DashboardIcon key="workspace" />],
    ['board', 'My work', <GridIcon key="board" />],
    ['status', 'Automations', <ActivityLogIcon key="status" />],
    ['memory', 'Search', <MagnifyingGlassIcon key="memory" />],
  ];
  const toolItems: Array<[WorkbenchSection, string, ReactNode]> = [
    ['chat', 'Chats', <ChatBubbleIcon key="chat" />],
    ['sandbox', 'Sandbox', <DesktopIcon key="sandbox" />],
    ['terminal', 'Terminal', <CodeIcon key="terminal" />],
    ['settings', 'Settings', <GearIcon key="settings" />],
  ];
  const mobileSectionItems: Array<[WorkbenchSection, string, ReactNode]> = [
    ...quickLinkItems.map(([section, label, icon]) => [section, label, icon] as [
      WorkbenchSection,
      string,
      ReactNode,
    ]),
    ...toolItems,
  ];
  const mobileTitlebarItems: MobileTitlebarMenuItem[] = showRuntimeConfig
    ? mobileSectionItems.map(([section, label, icon]) => ({
        id: `section-${section}`,
        label,
        icon,
        selected: activeSection === section,
        onSelect: () => selectMobileSection(section),
      }))
    : [
        {
          id: 'commands',
          label: 'Commands',
          icon: <MagnifyingGlassIcon />,
          onSelect: () => {
            setMobileSectionMenuOpen(false);
            openCommandPalette(mobileSectionButtonRef.current);
          },
        },
        {
          id: 'sign-in',
          label: 'Sign in',
          icon: <RocketIcon />,
          onSelect: () => {
            setMobileSectionMenuOpen(false);
            mobileSectionButtonRef.current?.focus();
            setLoginModalOpen(true);
          },
        },
        {
          id: 'api-key',
          label: 'API key',
          icon: <GearIcon />,
          onSelect: () => {
            setMobileSectionMenuOpen(false);
            useApiKeyManually();
          },
        },
      ];
  mobileTitlebarItemsRef.current = mobileTitlebarItems;

  const changeSessionGroupMode = (mode: SessionGroupMode) => {
    setSessionGroupMode(mode);
    setSessionMenuOpen(false);
  };

  const applySectionSideEffects = (section: WorkbenchSection) => {
    activeSectionRef.current = section;
    setActiveSection(section);
    if (section === 'sandbox' || section === 'terminal') setStatusTab('sandbox');
    if (section === 'memory') setStatusTab('memory');
    if (section === 'status') setStatusTab('overview');
    if (section === 'terminal') setReviewTab('terminal');
    if (section === 'board') setReviewTab('changes');
    if (section === 'status') setReviewTab('plan');
  };

  const switchSection = (section: WorkbenchSection) => {
    const currentSection = activeSectionRef.current;
    if (section !== currentSection) {
      setSectionBackStack([...sectionBackStack, currentSection].slice(-24));
      setSectionForwardStack([]);
    }
    applySectionSideEffects(section);
  };

  const openConnectionSettings = () => {
    if (!showRuntimeConfig) {
      useApiKeyManually();
      return;
    }
    switchSection('settings');
  };

  const selectMobileSection = (section: WorkbenchSection) => {
    switchSection(section);
    setMobileSectionMenuOpen(false);
  };

  const defaultMobileMenuItemId = () =>
    mobileTitlebarItems.find((item) => item.selected && !item.disabled)?.id ??
    mobileTitlebarItems.find((item) => !item.disabled)?.id ??
    null;

  const toggleMobileSectionMenu = () => {
    const nextOpen = !mobileSectionMenuOpen;
    if (nextOpen) {
      closeCommandPalette();
      setSessionMenuOpen(false);
    }
    setMobileSectionMenuOpen(nextOpen);
    setActiveMobileMenuItemId(nextOpen ? defaultMobileMenuItemId() : null);
  };

  const goBackSection = () => {
    const previousSection = sectionBackStack[sectionBackStack.length - 1];
    if (!previousSection) return;
    const leavingSection = activeSectionRef.current;
    setSectionBackStack(sectionBackStack.slice(0, -1));
    setSectionForwardStack([leavingSection, ...sectionForwardStack].slice(0, 24));
    applySectionSideEffects(previousSection);
  };

  const goForwardSection = () => {
    const nextSection = sectionForwardStack[0];
    if (!nextSection) return;
    const leavingSection = activeSectionRef.current;
    setSectionBackStack([...sectionBackStack, leavingSection].slice(-24));
    setSectionForwardStack(sectionForwardStack.slice(1));
    applySectionSideEffects(nextSection);
  };

  const canGoBack = sectionBackStack.length > 0;
  const canGoForward = sectionForwardStack.length > 0;

  const selectWorkflowTarget = (target: WorkflowTarget) => {
    setReviewPanelOpen(true);
    if (target === 'changes') {
      setReviewTab('changes');
      switchSection('workspace');
      return;
    }
    if (target === 'pull') {
      setReviewTab('pull');
      switchSection('workspace');
      return;
    }
    if (target === 'board') {
      setReviewTab('changes');
      switchSection('board');
      return;
    }
    if (target === 'plan') {
      setReviewTab('plan');
      switchSection('workspace');
      return;
    }
    if (target === 'background') {
      setReviewTab('background');
      switchSection('workspace');
      return;
    }
    if (target === 'artifacts') {
      setReviewTab('artifacts');
      switchSection('workspace');
      return;
    }
    setReviewTab('terminal');
    switchSection('terminal');
  };

  const selectChatWorkflowTarget = (target: ChatWorkflowTarget) => {
    setReviewPanelOpen(true);
    if (target === 'changes') {
      setReviewTab('changes');
      return;
    }
    if (target === 'pull') {
      setReviewTab('pull');
      return;
    }
    if (target === 'background') {
      setReviewTab('background');
      return;
    }
    if (target === 'artifacts') {
      setReviewTab('artifacts');
      return;
    }
    setReviewTab('plan');
  };

  const runSelectedSession = () => {
    if (!showRuntimeConfig) {
      setLoginModalOpen(true);
      return;
    }
    if (runtimeDisabledReason) {
      switchSection('settings');
      return;
    }
    if (connection !== 'ready') {
      void refreshRuntime();
      return;
    }
    switchSection('chat');
  };

  const openProject = () => {
    if (!showRuntimeConfig) {
      useApiKeyManually();
      return;
    }
    if (!config.projectId.trim()) {
      switchSection('settings');
      return;
    }
    switchSection(config.workspaceId ? 'workspace' : 'settings');
  };

  const openPullRequestOverview = () => {
    selectWorkflowTarget('pull');
  };

  const openOtherApps = () => {
    openCommandPalette();
  };

  const commandItems: CommandPaletteItem[] = [
    {
      id: 'home',
      label: 'Home',
      description: 'Open the workspace overview.',
      icon: <DashboardIcon />,
      onSelect: () => switchSection('workspace'),
    },
    {
      id: 'my-work',
      label: 'My work',
      description: 'Open tasks, board lanes, and active work.',
      icon: <GridIcon />,
      onSelect: () => switchSection('board'),
    },
    {
      id: 'automations',
      label: 'Automations',
      description: 'Review connection status, live updates, and workflow activity.',
      icon: <ActivityLogIcon />,
      onSelect: () => switchSection('status'),
    },
    {
      id: 'search-memory',
      label: 'Search local memory',
      description: showRuntimeConfig
        ? 'Search local memory records for this desktop session.'
        : 'Sign in or use a manual API key before searching local memory.',
      icon: <MagnifyingGlassIcon />,
      shortcut: '⌘K',
      disabled: !showRuntimeConfig,
      onSelect: () => switchSection('memory'),
    },
    {
      id: 'chats',
      label: 'Chats',
      description: showRuntimeConfig
        ? 'Open the workspace message timeline.'
        : 'Sign in or use a manual API key before opening chats.',
      icon: <ChatBubbleIcon />,
      disabled: !showRuntimeConfig,
      onSelect: () => switchSection('chat'),
    },
    {
      id: 'settings',
      label: showRuntimeConfig ? 'Settings' : 'Use API key manually',
      description: showRuntimeConfig
        ? 'Edit connection, account, project, and workspace settings.'
        : 'Switch to the manual API key fallback without saving secrets.',
      icon: <GearIcon />,
      onSelect: openConnectionSettings,
    },
    {
      id: 'sign-in',
      label: auth.status === 'signed_in' ? 'Account' : 'Sign in to agi-stack',
      description:
        auth.status === 'signed_in'
          ? auth.user?.email ?? 'Review the signed-in account.'
          : 'Open the email/password login dialog.',
      icon: <RocketIcon />,
      onSelect: () => {
        if (auth.status === 'signed_in') {
          switchSection('settings');
          return;
        }
        loginRestoreTargetRef.current = commandPaletteTriggerRef.current?.isConnected
          ? commandPaletteTriggerRef.current
          : getLoginRestoreTarget();
        setLoginModalOpen(true);
      },
    },
    {
      id: 'refresh-runtime',
      label: 'Refresh workspace',
      description: runtimeDisabledReason ?? 'Reload chats, work items, plan, and sandbox.',
      icon: <RocketIcon />,
      disabled: Boolean(runtimeDisabledReason) || connection === 'loading',
      onSelect: () => void refreshRuntime(),
    },
    {
      id: 'run-selected-session',
      label: 'Run selected session',
      description: showRuntimeConfig
        ? runtimeDisabledReason ?? 'Connect or open the chat surface for this workspace.'
        : 'Open sign in before running a workspace session.',
      icon: <PlayIcon />,
      onSelect: runSelectedSession,
    },
    {
      id: 'open-project',
      label: hasProjectScope ? 'Open in VS Code' : 'Configure project',
      description: hasProjectScope
        ? 'Open the selected workspace or project settings.'
        : 'Add a project id before opening workspace files.',
      icon: <CodeIcon />,
      onSelect: openProject,
    },
  ];
  const normalizedCommandQuery = commandQuery.trim().toLowerCase();
  const filteredCommandItems = normalizedCommandQuery
    ? commandItems.filter((item) =>
        `${item.label} ${item.description}`.toLowerCase().includes(normalizedCommandQuery),
      )
    : commandItems;

  const renderChatPanel = () => (
    <ChatPanel
      messages={dataset.messages}
      agentTaskSignals={agentTaskSignals}
      input={chatInput}
      sending={sending}
      disabledReason={chatDisabledReason}
      activeWorkflowTarget={chatWorkflowTargetForReviewTab(reviewTab)}
      onInputChange={setChatInput}
      onSend={() => void sendMessage()}
      onRefresh={() => void refreshRuntime()}
      onWorkflowSelect={selectChatWorkflowTarget}
    />
  );

  const renderWorkspaceOverview = () => {
    const blockedTasks = dataset.tasks.filter((task) => task.status === 'blocked').length;
    const activeTasks = dataset.tasks.filter((task) => {
      const status = (task.status ?? '').toLowerCase();
      return status !== 'done' && status !== 'closed' && status !== 'completed';
    }).length;
    const latestMessage = dataset.messages[dataset.messages.length - 1] ?? null;
    const workspaceStatus = selectedWorkspace?.status ?? 'open';

    return (
      <section className="pane-shell overview-shell">
        <header className="pane-head">
          <div>
            <Heading as="h2" size="3">
              Workspace
            </Heading>
            <Text size="1" color="gray">
              Chat, work items, plan, and sandbox status for this session.
            </Text>
          </div>
          <Button
            size="2"
            variant="surface"
            aria-label="Refresh workspace overview"
            onClick={() => void refreshRuntime()}
            disabled={Boolean(runtimeDisabledReason) || connection === 'loading'}
            loading={connection === 'loading'}
          >
            <RocketIcon /> Refresh
          </Button>
        </header>
        <div className="overview-content">
          <section className="overview-summary" aria-label="Workspace summary">
            <div>
              <Text size="1" color="gray">
                Current workspace
              </Text>
              <Heading as="h3" size="4">
                {workspaceLabel(selectedWorkspace ?? undefined)}
              </Heading>
              <Text size="2" color="gray">
                {selectedWorkspace?.description ??
                  (config.workspaceId || 'Select or create a workspace to load live chat and tasks.')}
              </Text>
            </div>
            <Badge color={workspaceStatus === 'closed' ? 'gray' : 'green'} variant="soft">
              {workspaceStatus}
            </Badge>
          </section>

          <div className="overview-metrics">
            <OverviewMetric label="Messages" value={String(dataset.messages.length)} />
            <OverviewMetric label="Active tasks" value={String(activeTasks)} />
            <OverviewMetric label="Blocked" value={String(blockedTasks)} />
            <OverviewMetric label="Sandbox" value={dataset.sandbox?.status ?? 'idle'} />
          </div>

          <div className="overview-actions" aria-label="Workspace actions">
            <button
              type="button"
              aria-label="Open workspace chat"
              onClick={() => switchSection('chat')}
            >
              <span>
                <ChatBubbleIcon />
              </span>
              <strong>Open chat</strong>
              <Text size="1" color="gray">
                {latestMessage
                  ? latestMessage.content
                  : 'No messages loaded for this workspace yet.'}
              </Text>
            </button>
            <button
              type="button"
              aria-label="Review workspace work items"
              onClick={() => switchSection('board')}
            >
              <span>
                <GridIcon />
              </span>
              <strong>Review work</strong>
              <Text size="1" color="gray">
                {dataset.tasks.length
                  ? `${dataset.tasks.length} tasks across board lanes.`
                  : 'No tasks loaded for this workspace yet.'}
              </Text>
            </button>
            <button
              type="button"
              aria-label="Open workspace sandbox"
              onClick={() => switchSection('sandbox')}
            >
              <span>
                <DesktopIcon />
              </span>
              <strong>Open sandbox</strong>
              <Text size="1" color="gray">
                {dataset.sandbox?.is_healthy
                  ? 'Desktop and terminal services are available.'
                  : 'Start sandbox desktop or terminal when a project is configured.'}
              </Text>
            </button>
            <button
              type="button"
              aria-label="Open connection settings"
              onClick={() => switchSection('settings')}
            >
              <span>
                <GearIcon />
              </span>
              <strong>Connection settings</strong>
              <Text size="1" color="gray">
                {runtimeDisabledReason ?? `${config.apiBaseUrl} / ${config.mode}`}
              </Text>
            </button>
          </div>
        </div>
      </section>
    );
  };

  const renderBoardPanel = () => (
    <BoardPanel
      tasks={dataset.tasks}
      boardMode={boardMode}
      selectedTaskId={selectedTaskId}
      onBoardModeChange={setBoardMode}
      onSelectTask={setSelectedTaskId}
    />
  );

  const renderStatusPanel = () => (
    <StatusPanel
      selectedTask={selectedTask}
      plan={dataset.plan}
      events={socket.events}
      wsConnected={socket.connected}
      tab={statusTab}
      sandbox={dataset.sandbox}
      desktop={desktop}
      desktopFrameUrl={desktopFrameUrl}
      terminal={terminal}
      terminalConnected={terminalProxy.connected}
      terminalError={terminalProxy.error}
      terminalLines={terminalProxy.lines}
      terminalInput={terminalInput}
      sandboxBusy={sandboxBusy}
      sandboxDisabledReason={sandboxDisabledReason}
      memoryProjectId={memoryProjectId}
      memoryContent={memoryContent}
      memoryQuery={memoryQuery}
      tauriAvailable={runsInTauri}
      memoryBusy={memoryBusy}
      memoryResult={memoryResult}
      onTabChange={setStatusTab}
      onTerminalInputChange={setTerminalInput}
      onEnsureSandbox={() => void ensureSandbox()}
      onStartDesktop={() => void startDesktop()}
      onStartTerminal={() => void startTerminal()}
      onSendTerminalInput={sendTerminalInput}
      onClearTerminal={terminalProxy.clear}
      onMemoryContentChange={setMemoryContent}
      onMemoryQueryChange={setMemoryQuery}
      onMemoryIngest={() =>
        void runMemoryAction(() =>
          ingestLocalMemory(memoryProjectId, memoryAuthorId, memoryContent),
        )
      }
      onMemorySearch={() =>
        void runMemoryAction(() => searchLocalMemory(memoryProjectId, memoryQuery, 10))
      }
      onMemorySemanticSearch={() =>
        void runMemoryAction(() =>
          semanticSearchLocalMemory(memoryProjectId, memoryQuery, 10),
        )
      }
    />
  );

  const renderWorkbench = () => {
    if (!showRuntimeConfig) {
      return (
        <SignedOutPanel
          activeTarget={signedOutTargetForSection(activeSection, reviewTab)}
          onWorkflowSelect={selectWorkflowTarget}
          onSignIn={() => setLoginModalOpen(true)}
          onUseManualKey={useApiKeyManually}
          onOpenCommands={openCommandPalette}
          onCloseCommands={closeCommandPalette}
        />
      );
    }
    if (activeSection === 'workspace') return renderWorkspaceOverview();
    if (activeSection === 'chat') return renderChatPanel();
    if (activeSection === 'board') return renderBoardPanel();
    if (
      activeSection === 'status' ||
      activeSection === 'sandbox' ||
      activeSection === 'memory' ||
      activeSection === 'terminal'
    ) {
      return renderStatusPanel();
    }
    if (activeSection === 'settings') {
      return (
        <section className="pane-shell settings-shell">
          <header className="pane-head">
            <div>
              <Heading as="h2" size="3">
                Settings
              </Heading>
              <Text size="1" color="gray">
                Current connection, account, and workspace scope.
              </Text>
            </div>
            <Badge color={connection === 'ready' ? 'green' : 'gray'} variant="soft">
              {connection}
            </Badge>
          </header>
          <div className="settings-content">
            <RuntimeConfigPanel
              config={config}
              connection={connection}
              wsConnected={socket.connected}
              wsError={socket.error}
              disabledReason={runtimeDisabledReason}
              focusApiKeySignal={runtimeApiKeyFocusSignal}
              onChange={handleConfigChange}
              onRefresh={() => void refreshRuntime()}
            />
            <div className="settings-grid">
              <SettingMetric label="Server" value={config.apiBaseUrl} />
              <SettingMetric label="Account" value={config.tenantId || '-'} />
              <SettingMetric label="Project" value={config.projectId || '-'} />
              <SettingMetric label="Workspace" value={config.workspaceId || '-'} />
              <SettingMetric label="Connection" value={config.mode} />
              <SettingMetric label="Live events" value={socket.connected ? 'live' : 'idle'} />
            </div>
          </div>
        </section>
      );
    }
    return renderWorkspaceOverview();
  };

  return (
    <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium" scaling="95%">
      <div
        ref={appShellRef}
        className={`app-shell ${runsInTauri ? 'tauri-window' : 'browser-window'} ${
          showRuntimeConfig ? 'runtime-mode' : 'signed-out-mode'
        } ${sidebarCollapsed ? 'sidebar-collapsed' : ''}`}
      >
        <header className="titlebar" data-tauri-drag-region>
          <div className="session-crumb">
            {showRuntimeConfig && hasWorkspaceScope ? (
              <Button
                size="2"
                color="purple"
                variant="soft"
                className="pull-request-overview"
                aria-label="View pull request overview"
                onClick={openPullRequestOverview}
              >
                <ReaderIcon /> PR idle
              </Button>
            ) : null}
            {showRuntimeConfig ? (
              <Text size="2" weight="bold">
                {`Session: ${sessionTitle}`}
              </Text>
            ) : (
              <div className="titlebar-signedout-label" aria-label="New session">
                <Text size="3" weight="bold" className="titlebar-workspace-name">
                  New session
                </Text>
              </div>
            )}
            {showRuntimeConfig ? (
              <button
                className="session-info-button"
                type="button"
                aria-label={`${sessionInfoLabel}, session information`}
                onClick={() => switchSection('settings')}
              >
                {sessionInfoLabel}
              </button>
            ) : null}
          </div>
          {mobileTitlebarItems.length ? (
            <div className="mobile-section-switcher">
              <Tooltip content={showRuntimeConfig ? 'Switch section' : 'Session actions'}>
                <IconButton
                  ref={mobileSectionButtonRef}
                  size="2"
                  variant="soft"
                  color="gray"
                  aria-label={showRuntimeConfig ? 'Switch workspace section' : 'Open session actions'}
                  aria-controls={mobileSectionMenuOpen ? 'mobile-section-menu' : undefined}
                  aria-expanded={mobileSectionMenuOpen}
                  aria-haspopup="menu"
                  onClick={toggleMobileSectionMenu}
                >
                  {showRuntimeConfig ? <ColumnsIcon /> : <DotsHorizontalIcon />}
                </IconButton>
              </Tooltip>
              {mobileSectionMenuOpen ? (
                <div
                  className="mobile-section-menu"
                  id="mobile-section-menu"
                  ref={mobileSectionMenuRef}
                  role="menu"
                  aria-activedescendant={activeMobileMenuOptionId}
                  aria-label={showRuntimeConfig ? 'Workspace sections' : 'Session actions'}
                >
                  {mobileTitlebarItems.map((item) => {
                    const selectable = typeof item.selected === 'boolean';
                    const isActive = activeMobileMenuItemId === item.id;
                    return (
                      <button
                        id={mobileMenuOptionId(item.id)}
                        type="button"
                        role={selectable ? 'menuitemradio' : 'menuitem'}
                        aria-checked={selectable ? item.selected : undefined}
                        disabled={item.disabled}
                        className={[item.selected ? 'selected' : '', isActive ? 'active' : '']
                          .filter(Boolean)
                          .join(' ')}
                        key={item.id}
                        onFocus={() => setActiveMobileMenuItemId(item.id)}
                        onMouseEnter={() => setActiveMobileMenuItemId(item.id)}
                        onClick={item.onSelect}
                      >
                        <span aria-hidden>{item.icon}</span>
                        <strong>{item.label}</strong>
                      </button>
                    );
                  })}
                </div>
              ) : null}
            </div>
          ) : null}
          {showRuntimeConfig ? (
            <Flex align="center" gap="2" ml="auto" className="titlebar-actions">
              <Tooltip
                content={`${authStatusLabel} / ${config.mode} / ${connection} / last sync ${lastSync}`}
              >
                <IconButton
                  color={connection === 'ready' ? 'green' : connection === 'error' ? 'red' : 'gray'}
                  variant="soft"
                  className="runtime-readout"
                  aria-label={`Refresh workspace, ${connection}`}
                  disabled={Boolean(runtimeDisabledReason) || connection === 'loading'}
                  onClick={() => void refreshRuntime()}
                >
                  <RocketIcon />
                </IconButton>
              </Tooltip>
              <Button
                size="2"
                variant="surface"
                color="gray"
                aria-label="Run selected session"
                disabled={Boolean(runtimeDisabledReason) || connection === 'loading'}
                onClick={runSelectedSession}
                loading={connection === 'loading'}
              >
                <PlayIcon /> Run
              </Button>
              <Flex align="center" gap="1" className="open-action-group">
                <Button
                  size="2"
                  variant="surface"
                  color="gray"
                  aria-label={
                    hasProjectScope
                      ? 'Open in Visual Studio Code'
                      : 'Configure project before opening in Visual Studio Code'
                  }
                  disabled={!hasProjectScope}
                  onClick={openProject}
                >
                  <CodeIcon /> {hasProjectScope ? 'VS Code' : 'Project'}
                </Button>
                <Tooltip
                  content={
                    hasProjectScope
                      ? 'Open in other apps'
                      : 'Configure a project before opening in other apps'
                  }
                >
                  <IconButton
                    variant="surface"
                    color="gray"
                    aria-label={
                      hasProjectScope
                        ? 'Open in other apps'
                        : 'Configure project before opening in other apps'
                    }
                    disabled={!hasProjectScope}
                    onClick={openOtherApps}
                  >
                    <DotsHorizontalIcon />
                  </IconButton>
                </Tooltip>
              </Flex>
              <Tooltip
                content={
                  socket.connected
                    ? 'Live updates connected'
                    : socket.error ?? 'Live updates idle'
                }
              >
                <IconButton
                  variant="surface"
                  color={socket.connected ? 'green' : socket.error ? 'red' : 'gray'}
                  aria-label={
                    socket.connected
                      ? 'Open live updates status, connected'
                      : socket.error
                        ? 'Open live updates status, error'
                        : 'Open live updates status, idle'
                  }
                  onClick={() => switchSection('status')}
                >
                  <CheckCircledIcon />
                </IconButton>
              </Tooltip>
              <Tooltip content={reviewPanelOpen ? 'Hide workspace panel' : 'Show workspace panel'}>
                <IconButton
                  variant="surface"
                  color={reviewPanelOpen ? 'cyan' : 'gray'}
                  aria-label={reviewPanelOpen ? 'Hide workspace panel' : 'Show workspace panel'}
                  aria-pressed={reviewPanelOpen}
                  onClick={() => setReviewPanelOpen((open) => !open)}
                >
                  <ColumnsIcon />
                </IconButton>
              </Tooltip>
            </Flex>
          ) : null}
        </header>

        <section className="desktop-body">
          <aside className="copilot-sidebar">
            <div className="sidebar-chrome" data-tauri-drag-region>
              <div className="sidebar-nav-controls">
                <IconButton
                  size="1"
                  variant="ghost"
                  color="gray"
                  aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
                  aria-pressed={sidebarCollapsed}
                  onClick={() => setSidebarCollapsed((collapsed) => !collapsed)}
                >
                  <ViewVerticalIcon />
                </IconButton>
                <IconButton
                  size="1"
                  variant="ghost"
                  color="gray"
                  aria-label="Go back"
                  disabled={!canGoBack}
                  onClick={goBackSection}
                >
                  <ChevronLeftIcon />
                </IconButton>
                <IconButton
                  size="1"
                  variant="ghost"
                  color="gray"
                  aria-label="Go forward"
                  disabled={!canGoForward}
                  onClick={goForwardSection}
                >
                  <ChevronRightIcon />
                </IconButton>
              </div>
            </div>

            <div className="sidebar-main">
              <nav className="quick-links" aria-label="desktop sections">
                <div className="sidebar-heading">
                  <Text size="1" weight="bold" color="gray">
                    Quick links
                  </Text>
                </div>
                {quickLinkItems.map(([section, label, icon]) => (
                  <button
                    className={`sidebar-row ${
                      showRuntimeConfig && activeSection === section ? 'selected' : ''
                    }`}
                    type="button"
                    key={String(label)}
                    aria-label={`${String(label)} section`}
                    onClick={() => {
                      switchSection(section);
                    }}
                  >
                    <span className="sidebar-icon">{icon}</span>
                    <span>{label}</span>
                  </button>
                ))}
              </nav>

              {showRuntimeConfig ? (
                <nav className="sidebar-tools" aria-label="workspace tools">
                  <div className="sidebar-heading">
                    <Text size="1" weight="bold" color="gray">
                      Tools
                    </Text>
                  </div>
                  {toolItems.map(([section, label, icon]) => (
                    <button
                      className={`sidebar-row ${activeSection === section ? 'selected' : ''}`}
                      type="button"
                      key={String(label)}
                      aria-label={`${String(label)} section`}
                      onClick={() => switchSection(section)}
                    >
                      <span className="sidebar-icon">{icon}</span>
                      <span>{label}</span>
                    </button>
                  ))}
                </nav>
              ) : null}

              <section className="sidebar-sessions">
                <div className="sidebar-heading">
                  <Text size="1" weight="bold" color="gray">
                    Sessions
                  </Text>
                  <span className="sidebar-heading-actions">
                    <span className="session-grouping-control">
                      <IconButton
                        size="1"
                        variant="ghost"
                        color={sessionMenuOpen ? 'cyan' : 'gray'}
                        aria-label={`Session grouping, ${sessionGroupLabel}`}
                        aria-haspopup="menu"
                        aria-expanded={sessionMenuOpen}
                        onClick={() => {
                          const nextOpen = !sessionMenuOpen;
                          if (nextOpen) {
                            closeCommandPalette();
                            setMobileSectionMenuOpen(false);
                            setActiveMobileMenuItemId(null);
                          }
                          setSessionMenuOpen(nextOpen);
                        }}
                      >
                        <MixerHorizontalIcon />
                      </IconButton>
                      {sessionMenuOpen ? (
                        <div className="session-group-menu" role="menu" aria-label="Session grouping">
                          <button
                            type="button"
                            role="menuitemradio"
                            aria-checked={sessionGroupMode === 'project'}
                            className={sessionGroupMode === 'project' ? 'selected' : ''}
                            onClick={() => changeSessionGroupMode('project')}
                          >
                            <CheckCircledIcon />
                            <span>
                              <strong>Project folders</strong>
                              <em>Group chats under workspace roots.</em>
                            </span>
                          </button>
                          <button
                            type="button"
                            role="menuitemradio"
                            aria-checked={sessionGroupMode === 'recent'}
                            className={sessionGroupMode === 'recent' ? 'selected' : ''}
                            onClick={() => changeSessionGroupMode('recent')}
                          >
                            <CheckCircledIcon />
                            <span>
                              <strong>Recent first</strong>
                              <em>Show the active session first.</em>
                            </span>
                          </button>
                        </div>
                      ) : null}
                    </span>
                    <IconButton
                      size="1"
                      variant="ghost"
                      color="gray"
                      aria-label={
                        showRuntimeConfig && !workspaceDisabledReason
                          ? 'Create workspace session'
                          : 'New session'
                      }
                      disabled={creatingWorkspace}
                      onClick={startNewSession}
                    >
                      <PlusIcon />
                    </IconButton>
                  </span>
                </div>
                {showRuntimeConfig ? (
                  <WorkspaceDock
                    workspaces={visibleWorkspaces}
                    currentWorkspaceId={config.workspaceId}
                    projectLabel={sidebarProjectLabel}
                    messageCount={dataset.messages.length}
                    taskCount={dataset.tasks.length}
                    onSelectWorkspace={selectWorkspace}
                    onOpenChat={() => switchSection('chat')}
                    onRefresh={() => void refreshRuntime()}
                    actionDisabledReason={workspaceDisabledReason}
                    creatingWorkspace={creatingWorkspace}
                    onCreateWorkspace={startNewSession}
                  />
                ) : (
                  <SignedOutSessionTree mode={sessionGroupMode} onNewSession={startNewSession} />
                )}
              </section>
            </div>

            <section className="left-dock">
              <AuthPanel
                auth={auth}
                config={config}
                email={loginEmail}
                password={loginPassword}
                onApiBaseUrlChange={(apiBaseUrl) => handleConfigChange({ ...config, apiBaseUrl })}
                onEmailChange={setLoginEmail}
                onPasswordChange={setLoginPassword}
                onLogin={() => void login()}
                onUseApiKeyManually={useApiKeyManually}
                onLogout={logout}
                onOpenSettings={openConnectionSettings}
                loginOpen={loginModalOpen}
                onLoginOpenChange={setLoginModalOpen}
                getLoginRestoreTarget={getLoginRestoreTarget}
              />
            </section>
          </aside>

          <main className="workbench">
            {error ? (
              <div className="workbench-error" role="alert" aria-live="polite">
                {error}
              </div>
            ) : null}
            <section
              className={`workbench-layout ${showReviewPanel ? '' : 'review-panel-collapsed'}`}
            >
              <section className={paneStageClassName}>{renderWorkbench()}</section>
              {showReviewPanel ? (
                <WorkspaceReviewPanel
                  activeTab={reviewTab}
                  dataset={dataset}
                  connection={connection}
                  socketConnected={socket.connected}
                  socketEvents={socket.events}
                  terminalConnected={terminalProxy.connected}
                  terminalLines={terminalProxy.lines}
                  onTabChange={setReviewTab}
                />
              ) : null}
            </section>
          </main>
        </section>

        {commandPaletteOpen
          ? createPortal(
              <CommandPalette
                inputRef={commandInputRef}
                query={commandQuery}
                items={filteredCommandItems}
                onQueryChange={setCommandQuery}
                onClose={closeCommandPalette}
              />,
              document.body,
            )
          : null}
      </div>
    </Theme>
  );
}

function formatError(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

function formatConnectionError(error: unknown, apiBaseUrl: string): string {
  const message = formatError(error);
  if (/failed to fetch|networkerror|load failed/i.test(message)) {
    return `Cannot reach ${apiBaseUrl}. Start the agi-stack server or update the Server URL.`;
  }
  return message;
}

function formatLoginError(error: unknown, apiBaseUrl: string): string {
  return formatConnectionError(error, apiBaseUrl);
}

function SignedOutSessionTree({
  mode,
  onNewSession,
}: {
  mode: SessionGroupMode;
  onNewSession: () => void;
}) {
  const newSessionRow = (
    <button
      className={`sidebar-row selected ${mode === 'project' ? 'session-child-row' : ''}`}
      type="button"
      aria-label="Current new session"
      onClick={onNewSession}
    >
      <span className="sidebar-icon">
        <CommitIcon />
      </span>
      <span>New session</span>
    </button>
  );
  const chatsRow = (
    <button className="sidebar-row" type="button" aria-label="Chats collection">
      <span className="sidebar-icon">
        <ChatBubbleIcon />
      </span>
      <span>Chats</span>
    </button>
  );
  const projectRow = (
    <button className="sidebar-row" type="button" aria-label="Project connection">
      <span className="sidebar-icon">
        <ArchiveIcon />
      </span>
      <span>Connect project</span>
    </button>
  );

  return (
    <div className={`signed-out-session-tree ${mode === 'recent' ? 'recent-first' : ''}`}>
      {mode === 'recent' ? (
        <>
          {newSessionRow}
          {chatsRow}
          {projectRow}
        </>
      ) : (
        <>
          {chatsRow}
          {projectRow}
          {newSessionRow}
        </>
      )}
    </div>
  );
}

function workspaceLabel(workspace: { id: string; name?: string; title?: string } | undefined): string {
  return workspace?.name ?? workspace?.title ?? workspace?.id ?? 'No workspace';
}

function SignedOutPanel({
  activeTarget,
  onWorkflowSelect,
  onSignIn,
  onUseManualKey,
  onOpenCommands,
  onCloseCommands,
}: {
  activeTarget: WorkflowTarget;
  onWorkflowSelect: (target: WorkflowTarget) => void;
  onSignIn: () => void;
  onUseManualKey: () => void;
  onOpenCommands: () => void;
  onCloseCommands: () => void;
}) {
  const context = signedOutWorkflowContext(activeTarget);
  const [warningVisible, setWarningVisible] = useState(true);
  const [scopeMenu, setScopeMenu] = useState<SessionScopeKind | null>(null);
  const [activeScopeOption, setActiveScopeOption] = useState<string | null>(null);
  const [composerDraft, setComposerDraft] = useState('');
  const [referenceMenu, setReferenceMenu] = useState<ComposerReferenceKind | null>(null);
  const [activeReferenceId, setActiveReferenceId] = useState<string | null>(null);
  const composerRef = useRef<HTMLDivElement>(null);
  const composerDraftRef = useRef<HTMLTextAreaElement>(null);
  const referenceOptions = useMemo(
    () => (referenceMenu ? composerReferenceOptions[referenceMenu] : []),
    [referenceMenu],
  );
  const activeReference =
    referenceOptions.find((option) => option.id === activeReferenceId) ?? referenceOptions[0];
  const activeReferenceOptionId = activeReference
    ? `composer-reference-option-${activeReference.id}`
    : undefined;
  const [sessionScope, setSessionScope] = useState<Record<SessionScopeKind, string>>({
    project: 'No project',
    worktree: 'New worktree',
    branch: 'Default branch',
  });
  const activeScopeOptionId =
    scopeMenu && activeScopeOption ? sessionScopeOptionId(scopeMenu, activeScopeOption) : undefined;

  const selectScopeValue = useCallback((kind: SessionScopeKind, value: string) => {
    setSessionScope((current) => ({ ...current, [kind]: value }));
    setScopeMenu(null);
    setActiveScopeOption(null);
  }, []);

  const openCommands = () => {
    setScopeMenu(null);
    setActiveScopeOption(null);
    setReferenceMenu(null);
    onOpenCommands();
  };

  const openReferenceMenu = (kind: ComposerReferenceKind) => {
    onCloseCommands();
    setScopeMenu(null);
    setActiveScopeOption(null);
    setReferenceMenu(kind);
  };

  useEffect(() => {
    if (!scopeMenu) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      const options = sessionScopeOptions[scopeMenu];
      if (event.key === 'Escape') {
        event.preventDefault();
        setScopeMenu(null);
        setActiveScopeOption(null);
        return;
      }
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        const delta = event.key === 'ArrowDown' ? 1 : -1;
        setActiveScopeOption((current) => {
          const currentOption = current ?? sessionScope[scopeMenu];
          const currentIndex = options.findIndex((option) => option === currentOption);
          const startIndex = currentIndex === -1 ? (delta > 0 ? -1 : 0) : currentIndex;
          const nextIndex = (startIndex + delta + options.length) % options.length;
          return options[nextIndex];
        });
        return;
      }
      if (event.key === 'Home' || event.key === 'End') {
        event.preventDefault();
        setActiveScopeOption(event.key === 'Home' ? options[0] : options[options.length - 1]);
        return;
      }
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        selectScopeValue(scopeMenu, activeScopeOption ?? sessionScope[scopeMenu]);
      }
    };

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      if (target.closest('.session-scope-control')) return;
      setScopeMenu(null);
    };

    document.addEventListener('keydown', handleKeyDown);
    document.addEventListener('pointerdown', handlePointerDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.removeEventListener('pointerdown', handlePointerDown);
    };
  }, [activeScopeOption, scopeMenu, selectScopeValue, sessionScope]);

  useEffect(() => {
    if (!scopeMenu) {
      setActiveScopeOption(null);
      return;
    }
    setActiveScopeOption(sessionScope[scopeMenu]);
  }, [scopeMenu, sessionScope]);

  useEffect(() => {
    setActiveReferenceId(referenceOptions[0]?.id ?? null);
  }, [referenceOptions]);

  useEffect(() => {
    if (!activeReferenceOptionId) return;
    document.getElementById(activeReferenceOptionId)?.scrollIntoView({ block: 'nearest' });
  }, [activeReferenceOptionId]);

  useEffect(() => {
    if (!referenceMenu) return;

    const closeIfOutsideComposer = (event: Event) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (composerRef.current?.contains(target)) return;
      setReferenceMenu(null);
    };

    document.addEventListener('pointerdown', closeIfOutsideComposer, true);
    document.addEventListener('focusin', closeIfOutsideComposer);
    return () => {
      document.removeEventListener('pointerdown', closeIfOutsideComposer, true);
      document.removeEventListener('focusin', closeIfOutsideComposer);
    };
  }, [referenceMenu]);

  useEffect(() => {
    if (!activeScopeOptionId) return;
    document.getElementById(activeScopeOptionId)?.scrollIntoView({ block: 'nearest' });
  }, [activeScopeOptionId]);

  const updateComposerDraft = (value: string, caret: number) => {
    if (value === '/' && caret === 1) {
      setComposerDraft('');
      openCommands();
      requestAnimationFrame(() => composerDraftRef.current?.focus());
      return;
    }

    setComposerDraft(value);
    const token = value.slice(0, caret).split(/\s/).pop() ?? '';
    if (token.startsWith('@')) {
      openReferenceMenu('files');
      return;
    }
    if (token.startsWith('#')) {
      openReferenceMenu('issues');
      return;
    }
    setReferenceMenu(null);
  };

  const moveActiveReference = (delta: number) => {
    setActiveReferenceId((current) => {
      if (referenceOptions.length === 0) return null;
      const currentIndex = referenceOptions.findIndex((option) => option.id === current);
      const startIndex = currentIndex === -1 ? (delta > 0 ? -1 : 0) : currentIndex;
      const nextIndex = (startIndex + delta + referenceOptions.length) % referenceOptions.length;
      return referenceOptions[nextIndex].id;
    });
  };

  const insertComposerReference = (label: string) => {
    const input = composerDraftRef.current;
    const selectionStart = input?.selectionStart ?? composerDraft.length;
    const selectionEnd = input?.selectionEnd ?? selectionStart;
    const beforeSelection = composerDraft.slice(0, selectionStart);
    const afterSelection = composerDraft.slice(selectionEnd);
    const tokenMatch = beforeSelection.match(/(^|\s)([@#][^\s]*)$/);
    const tokenStart = tokenMatch ? beforeSelection.length - tokenMatch[2].length : selectionStart;
    const insertLabel = referenceMenu === 'files' ? `@${label}` : label;
    const nextDraft = `${composerDraft.slice(0, tokenStart)}${insertLabel} ${
      afterSelection.startsWith(' ') ? afterSelection.slice(1) : afterSelection
    }`;
    const nextCursor = tokenStart + insertLabel.length + 1;
    setComposerDraft(nextDraft);
    setReferenceMenu(null);
    requestAnimationFrame(() => {
      composerDraftRef.current?.focus();
      composerDraftRef.current?.setSelectionRange(nextCursor, nextCursor);
    });
  };

  const renderScopeControl = (
    kind: SessionScopeKind,
    label: string,
    icon: ReactNode,
  ) => {
    const options = sessionScopeOptions[kind];
    const isOpen = scopeMenu === kind;
    const menuId = `session-scope-menu-${kind}`;

    return (
      <span className="session-scope-control" data-scope-kind={kind}>
        <button
          type="button"
          aria-label={`Choose ${label}`}
          aria-haspopup="menu"
          aria-controls={isOpen ? menuId : undefined}
          aria-expanded={isOpen}
          onClick={() => {
            const nextMenu = isOpen ? null : kind;
            if (nextMenu) {
              onCloseCommands();
              setReferenceMenu(null);
            }
            setScopeMenu(nextMenu);
            setActiveScopeOption(nextMenu ? sessionScope[kind] : null);
          }}
        >
          {icon}
          <span className="session-scope-label">{sessionScope[kind]}</span>
          <ChevronDownIcon className="footer-chevron" aria-hidden />
        </button>
        {isOpen ? (
          <div
            className="session-scope-menu"
            id={menuId}
            role="menu"
            aria-label={`${label} options`}
            aria-activedescendant={activeScopeOptionId}
          >
            {options.map((option) => {
              const isSelected = sessionScope[kind] === option;
              const isActive = activeScopeOption === option;
              return (
                <button
                  id={sessionScopeOptionId(kind, option)}
                  type="button"
                  role="menuitemradio"
                  aria-checked={isSelected}
                  className={[isSelected ? 'selected' : '', isActive ? 'active' : '']
                    .filter(Boolean)
                    .join(' ')}
                  key={option}
                  onFocus={() => setActiveScopeOption(option)}
                  onMouseEnter={() => setActiveScopeOption(option)}
                  onClick={() => selectScopeValue(kind, option)}
                >
                  <span>{option}</span>
                  {isSelected ? <CheckCircledIcon /> : null}
                </button>
              );
            })}
          </div>
        ) : null}
      </span>
    );
  };

  return (
    <section className="pane-shell welcome-shell">
      <div className="signed-out-canvas" aria-hidden="true">
        <div className="signed-out-mark">
          <span />
          <span />
          <span />
        </div>
      </div>
      <section className="welcome-timeline" aria-label="Conversation transcript">
        <div className="session-empty-hint">
          <span>Open any file in the repo with</span>
          <kbd aria-label="Command P">⌘ P</kbd>
          <span>.</span>
        </div>
      </section>
      <div
        className={`signed-out-dock ${warningVisible ? '' : 'warning-hidden'}`}
        aria-label="New session composer"
      >
        <WorkflowStrip activeTarget={activeTarget} onSelect={onWorkflowSelect} />
        {warningVisible ? (
          <div className="usage-warning">
            <div className="usage-warning-copy">
              <ExclamationTriangleIcon />
              <Text size="2">
                Sign in to connect workspace, sandbox, and terminal.
              </Text>
            </div>
            <div className="usage-warning-actions">
              <Button
                size="2"
                color="gray"
                variant="surface"
                aria-label="Sign in from connection warning"
                onClick={onSignIn}
              >
                Sign in
              </Button>
              <Button
                size="2"
                color="gray"
                variant="ghost"
                aria-label="Use API key from connection warning"
                onClick={onUseManualKey}
              >
                API key
              </Button>
              <IconButton
                size="1"
                color="gray"
                variant="ghost"
                className="usage-warning-dismiss"
                aria-label="Dismiss connection warning"
                onClick={() => setWarningVisible(false)}
              >
                <Cross2Icon />
              </IconButton>
            </div>
          </div>
        ) : null}
        <div className="composer signed-out-composer" ref={composerRef}>
          <textarea
            ref={composerDraftRef}
            className="composer-draft-input"
            value={composerDraft}
            rows={2}
            aria-label="New session prompt"
            aria-controls={referenceMenu ? 'composer-reference-menu' : undefined}
            aria-expanded={Boolean(referenceMenu)}
            aria-haspopup="listbox"
            aria-activedescendant={referenceMenu ? activeReferenceOptionId : undefined}
            placeholder="Ask anything. Type / for commands, @ to add files, or # to reference issues..."
            onChange={(event) =>
              updateComposerDraft(event.currentTarget.value, event.currentTarget.selectionStart)
            }
            onKeyDown={(event) => {
              const draftIsEmpty = event.currentTarget.value.trim() === '';
              if (event.key === '/' && draftIsEmpty) {
                event.preventDefault();
                setComposerDraft('');
                openCommands();
                return;
              }
              if (referenceMenu && event.key === 'ArrowDown') {
                event.preventDefault();
                moveActiveReference(1);
                return;
              }
              if (referenceMenu && event.key === 'ArrowUp') {
                event.preventDefault();
                moveActiveReference(-1);
                return;
              }
              if (referenceMenu && (event.key === 'Enter' || event.key === 'Tab')) {
                event.preventDefault();
                if (activeReference) {
                  insertComposerReference(activeReference.label);
                }
                return;
              }
              if (event.key === 'Escape' && referenceMenu) {
                event.preventDefault();
                setReferenceMenu(null);
              }
            }}
          />
          {referenceMenu ? (
            <div
              className="composer-reference-menu"
              id="composer-reference-menu"
              role="listbox"
              aria-label={referenceMenu === 'files' ? 'Files to add' : 'Issues to reference'}
            >
              <strong>{referenceMenu === 'files' ? 'Files' : 'Issues'}</strong>
              {referenceOptions.map((option) => (
                <button
                  id={`composer-reference-option-${option.id}`}
                  key={option.id}
                  type="button"
                  role="option"
                  aria-selected={option.id === activeReference?.id}
                  className={option.id === activeReference?.id ? 'selected' : ''}
                  onMouseEnter={() => setActiveReferenceId(option.id)}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => insertComposerReference(option.label)}
                >
                  <span className="reference-icon">{option.icon}</span>
                  <span className="reference-copy">
                    <span>{option.label}</span>
                    <em>{option.description}</em>
                  </span>
                </button>
              ))}
            </div>
          ) : null}
          <Flex align="center" justify="between" className="composer-toolbar">
            <ComposerControls
              disabledHint={context.body}
              effortLabel="Max"
              modeLabel="Interactive"
              modelLabel="Claude Fable 5 · 1M"
            />
            <Flex align="center" gap="2" className="composer-right-actions">
              <button
                className="composer-ring-button"
                type="button"
                aria-label="Open command palette"
                title="Open command palette"
                onClick={openCommands}
              >
                <ActivityLogIcon />
              </button>
              <Button
                size="2"
                className="send-pill"
                aria-label="Send message, sign in required"
                disabled
              >
                <RocketIcon />
              </Button>
            </Flex>
          </Flex>
        </div>
        <div
          className={`signed-out-session-footer ${
            warningVisible ? '' : 'auth-fallback-visible'
          }`}
          aria-label={warningVisible ? 'Session scope' : 'Connection actions'}
        >
          {warningVisible ? (
            <>
              {renderScopeControl('project', 'project', <ArchiveIcon />)}
              {renderScopeControl('worktree', 'worktree', <EnterFullScreenIcon />)}
              {renderScopeControl('branch', 'branch', <CommitIcon />)}
            </>
          ) : (
            <>
              <button type="button" aria-label="Sign in from connection footer" onClick={onSignIn}>
                <ChatBubbleIcon /> Sign in
              </button>
              <button
                type="button"
                aria-label="Use API key from connection footer"
                onClick={onUseManualKey}
              >
                <GearIcon /> API key
              </button>
              <button
                type="button"
                aria-label="Open command palette for project setup"
                onClick={openCommands}
              >
                <ArchiveIcon /> No project
              </button>
            </>
          )}
        </div>
      </div>
    </section>
  );
}

function WorkflowStrip({
  activeTarget,
  onSelect,
}: {
  activeTarget: WorkflowTarget;
  onSelect: (target: WorkflowTarget) => void;
}) {
  const items: Array<[WorkflowTarget, string, string, ReactNode]> = [
    ['changes', 'Changes', '+0 -0', <CodeIcon key="changes" />],
    ['pull', 'PR', 'idle', <ReaderIcon key="pull" />],
    ['plan', 'Plan', 'idle', <ActivityLogIcon key="plan" />],
    ['background', 'Background', '0', <DotsHorizontalIcon key="background" />],
    ['artifacts', 'Artifacts', '0', <ArchiveIcon key="artifacts" />],
  ];

  return (
    <div className="composer-workflows signed-out-workflows" aria-label="session workflow shortcuts">
      {items.map(([target, label, value, icon]) => (
        <button
          className={activeTarget === target ? 'selected' : ''}
          type="button"
          aria-label={`${label} ${value}`}
          key={target}
          onClick={() => onSelect(target)}
        >
          <span>{icon}</span>
          <strong>{label}</strong>
          <em>{value}</em>
        </button>
      ))}
    </div>
  );
}

function WorkspaceReviewPanel({
  activeTab,
  dataset,
  connection,
  socketConnected,
  socketEvents,
  terminalConnected,
  terminalLines,
  onTabChange,
}: {
  activeTab: ReviewTab;
  dataset: RuntimeDataset;
  connection: ConnectionState;
  socketConnected: boolean;
  socketEvents: unknown[];
  terminalConnected: boolean;
  terminalLines: string[];
  onTabChange: (tab: ReviewTab) => void;
}) {
  const [showMoreTabs, setShowMoreTabs] = useState(false);
  const [showAddTabs, setShowAddTabs] = useState(false);
  const [panelMode, setPanelMode] = useState<'normal' | 'maximized' | 'fullscreen'>('normal');
  const moreTabsButtonRef = useRef<HTMLButtonElement>(null);
  const moreTabsMenuRef = useRef<HTMLDivElement>(null);
  const addTabButtonRef = useRef<HTMLButtonElement>(null);
  const addTabMenuRef = useRef<HTMLDivElement>(null);
  const planKeys = dataset.plan ? Object.keys(dataset.plan).slice(0, 6) : [];
  const reviewTabs: Array<{
    tab: ReviewTab;
    label: string;
    value?: string;
  }> = [
    { tab: 'changes', label: 'Changes', value: '+0 -0' },
    { tab: 'pull', label: 'Pull request', value: 'idle' },
    { tab: 'plan', label: 'Plan', value: dataset.plan ? 'active' : 'idle' },
    { tab: 'terminal', label: 'Terminal', value: terminalConnected ? 'live' : 'idle' },
  ];
  const overflowReviewTabs: Array<{
    tab: ReviewTab;
    label: string;
    value: string;
  }> = [
    {
      tab: 'background',
      label: 'Background agents',
      value: socketEvents.length ? `${socketEvents.length} events` : 'idle',
    },
    { tab: 'artifacts', label: 'Artifacts', value: socketConnected ? 'subscribed' : 'idle' },
  ];
  const moreTabs: Array<{
    tab: ReviewTab;
    label: string;
    value: string;
  }> = overflowReviewTabs;
  const addableTabs: Array<{
    tab: ReviewTab;
    label: string;
    value: string;
  }> = [...reviewTabs, ...overflowReviewTabs].map(({ tab, label, value }) => ({
    tab,
    label,
    value: value ?? 'tab',
  }));
  const panelClassName = `review-panel ${panelMode === 'fullscreen' ? 'full-screen' : ''} ${
    panelMode === 'maximized' ? 'maximized' : ''
  }`;
  const pinnedReviewTabs = reviewTabs.slice(0, 4);
  const activeReviewTab = [...reviewTabs, ...overflowReviewTabs].find(
    ({ tab }) => tab === activeTab,
  );
  const visibleReviewTabs =
    activeReviewTab && !pinnedReviewTabs.some(({ tab }) => tab === activeReviewTab.tab)
      ? [...reviewTabs.slice(0, 3), activeReviewTab]
      : pinnedReviewTabs;

  const selectTab = (tab: ReviewTab) => {
    onTabChange(tab);
    setShowMoreTabs(false);
    setShowAddTabs(false);
  };

  useEffect(() => {
    if (!showMoreTabs) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      setShowMoreTabs(false);
      moreTabsButtonRef.current?.focus();
    };

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (moreTabsMenuRef.current?.contains(target)) return;
      if (moreTabsButtonRef.current?.contains(target)) return;
      setShowMoreTabs(false);
    };

    document.addEventListener('keydown', handleKeyDown);
    document.addEventListener('pointerdown', handlePointerDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.removeEventListener('pointerdown', handlePointerDown);
    };
  }, [showMoreTabs]);

  useEffect(() => {
    if (!showAddTabs) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      setShowAddTabs(false);
      addTabButtonRef.current?.focus();
    };

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (addTabMenuRef.current?.contains(target)) return;
      if (addTabButtonRef.current?.contains(target)) return;
      setShowAddTabs(false);
    };

    document.addEventListener('keydown', handleKeyDown);
    document.addEventListener('pointerdown', handlePointerDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.removeEventListener('pointerdown', handlePointerDown);
    };
  }, [showAddTabs]);

  return (
    <aside className={panelClassName} aria-label="Workspace review panel">
      <header className="review-head">
        <div>
          <Heading as="h2" size="3">
            Workspace
          </Heading>
          <Text size="1" color="gray">
            Review changes, pull requests, plans, background agents, artifacts, and terminal output.
          </Text>
        </div>
        <Badge color={connection === 'ready' ? 'green' : 'gray'} variant="soft">
          {connection}
        </Badge>
      </header>

      <div className="review-tabs" aria-label="Workspace tabs">
        <nav className="review-tab-scroll">
          {visibleReviewTabs.map(({ tab, label, value }) => (
            <button
              className={`review-tab ${activeTab === tab ? 'selected' : ''}`}
              type="button"
              aria-label={`Open ${label} tab${value ? `, ${value}` : ''}`}
              key={tab}
              onClick={() => selectTab(tab)}
            >
              <span>{label}</span>
              {value ? <em>{value}</em> : null}
            </button>
          ))}
        </nav>
        <div className="review-tab-actions" aria-label="Workspace tab actions">
          <Tooltip content="More tabs">
            <IconButton
              ref={moreTabsButtonRef}
              size="1"
              variant="ghost"
              color="gray"
              aria-label="More tabs"
              aria-controls={showMoreTabs ? 'workspace-more-tabs-menu' : undefined}
              aria-expanded={showMoreTabs}
              aria-haspopup="menu"
              onClick={() => {
                setShowAddTabs(false);
                setShowMoreTabs((open) => !open);
              }}
            >
              <DotsHorizontalIcon />
            </IconButton>
          </Tooltip>
          <Tooltip content="Add tab">
            <IconButton
              ref={addTabButtonRef}
              size="1"
              variant="ghost"
              color="gray"
              aria-label="Add workspace tab"
              aria-controls={showAddTabs ? 'workspace-add-tabs-menu' : undefined}
              aria-expanded={showAddTabs}
              aria-haspopup="menu"
              onClick={() => {
                setShowMoreTabs(false);
                setShowAddTabs((open) => !open);
              }}
            >
              <PlusIcon />
            </IconButton>
          </Tooltip>
          <Tooltip content={panelMode === 'fullscreen' ? 'Exit full screen' : 'Enter full screen'}>
            <IconButton
              size="1"
              variant="ghost"
              color={panelMode === 'fullscreen' ? 'cyan' : 'gray'}
              aria-label={panelMode === 'fullscreen' ? 'Exit full screen' : 'Enter full screen'}
              aria-pressed={panelMode === 'fullscreen'}
              onClick={() =>
                setPanelMode((mode) => (mode === 'fullscreen' ? 'normal' : 'fullscreen'))
              }
            >
              {panelMode === 'fullscreen' ? <ExitFullScreenIcon /> : <EnterFullScreenIcon />}
            </IconButton>
          </Tooltip>
          <Tooltip content={panelMode === 'maximized' ? 'Restore panel' : 'Maximize panel'}>
            <IconButton
              size="1"
              variant="ghost"
              color={panelMode === 'maximized' ? 'cyan' : 'gray'}
              aria-label={panelMode === 'maximized' ? 'Restore panel' : 'Maximize panel'}
              aria-pressed={panelMode === 'maximized'}
              onClick={() =>
                setPanelMode((mode) => (mode === 'maximized' ? 'normal' : 'maximized'))
              }
            >
              <FrameIcon />
            </IconButton>
          </Tooltip>
        </div>
        {showMoreTabs ? (
          <div
            className="review-tab-menu"
            id="workspace-more-tabs-menu"
            ref={moreTabsMenuRef}
            role="menu"
            aria-label="More workspace tabs"
          >
            {moreTabs.map(({ tab, label, value }) => (
              <button
                type="button"
                role="menuitemradio"
                aria-checked={activeTab === tab}
                aria-label={`Open ${label} workspace tab, ${value}`}
                key={tab}
                onClick={() => selectTab(tab)}
              >
                <span>{label}</span>
                <em>{value}</em>
              </button>
            ))}
          </div>
        ) : null}
        {showAddTabs ? (
          <div
            className="review-tab-menu review-add-tab-menu"
            id="workspace-add-tabs-menu"
            ref={addTabMenuRef}
            role="menu"
            aria-label="Add workspace tab"
          >
            {addableTabs.map(({ tab, label, value }) => (
              <button
                type="button"
                role="menuitemradio"
                aria-checked={activeTab === tab}
                aria-label={`Add ${label} workspace tab, ${value}`}
                key={tab}
                onClick={() => selectTab(tab)}
              >
                <span>{label}</span>
                <em>{value}</em>
              </button>
            ))}
          </div>
        ) : null}
      </div>

      <div className="review-content">
        {activeTab === 'changes' ? (
          <ReviewEmpty
            icon={<CodeIcon />}
            title="No synced changes"
            body="Connect a workspace session to show repository diffs, changed files, and review actions."
          />
        ) : null}

        {activeTab === 'pull' ? (
          <ReviewEmpty
            icon={<ReaderIcon />}
            title="No pull request linked"
            body="Connect a GitHub-backed workspace to show PR overview, checks, branch state, and review actions."
          />
        ) : null}

        {activeTab === 'plan' ? (
          <div className="review-plan">
            {dataset.plan ? (
              <>
                <div className="review-section-title">
                  <Text size="1" weight="bold" color="gray">
                    Active plan snapshot
                  </Text>
                  <Badge color="green" variant="soft">
                    loaded
                  </Badge>
                </div>
                <div className="plan-key-list">
                  {planKeys.map((key) => (
                    <div className="plan-key-row" key={key}>
                      <CheckCircledIcon />
                      <span>{key}</span>
                    </div>
                  ))}
                </div>
                <pre className="review-json">{JSON.stringify(dataset.plan, null, 2)}</pre>
              </>
            ) : (
              <div className="review-plan-tree">
                <div className="plan-node complete">
                  <CheckCircledIcon />
                  <span>Start desktop shell</span>
                </div>
                <div className="plan-branch">
                  <div className="plan-node">
                    <CheckCircledIcon />
                    <span>Sign in or configure API key</span>
                  </div>
                  <div className="plan-node">
                    <CheckCircledIcon />
                    <span>Select account, project, and workspace</span>
                  </div>
                  <div className="plan-node">
                    <CheckCircledIcon />
                    <span>Load work items, plan, sandbox, and terminal state</span>
                  </div>
                </div>
              </div>
            )}
          </div>
        ) : null}

        {activeTab === 'background' ? (
          <div className="review-background">
            <div className="review-section-title">
              <Text size="1" weight="bold" color="gray">
                Background agents
              </Text>
              <Badge color={socketEvents.length ? 'green' : 'gray'} variant="soft">
                {socketEvents.length ? `${socketEvents.length} events` : 'idle'}
              </Badge>
            </div>
            {socketEvents.length ? (
              socketEvents.slice(0, 8).map((event, index) => (
                <pre className="event-pill" key={index}>
                  {JSON.stringify(event, null, 2)}
                </pre>
              ))
            ) : (
              <ReviewEmpty
                icon={<DotsHorizontalIcon />}
                title="No background agents"
                body="Long-running work, queued checks, and progress updates appear here after connection."
              />
            )}
          </div>
        ) : null}

        {activeTab === 'artifacts' ? (
          <div className="review-artifacts">
            <div className="review-section-title">
              <Text size="1" weight="bold" color="gray">
                Agent events
              </Text>
              <Badge color={socketConnected ? 'green' : 'gray'} variant="soft">
                {socketConnected ? 'subscribed' : 'idle'}
              </Badge>
            </div>
            {socketEvents.length ? (
              socketEvents.slice(-8).map((event, index) => (
                <pre className="event-pill" key={index}>
                  {JSON.stringify(event, null, 2)}
                </pre>
              ))
            ) : (
              <ReviewEmpty
                icon={<ArchiveIcon />}
                title="No artifacts yet"
                body="Generated files, event updates, and background activity will appear here after connection."
              />
            )}
          </div>
        ) : null}

        {activeTab === 'terminal' ? (
          <div className="review-terminal">
            <div className="review-section-title">
              <Text size="1" weight="bold" color="gray">
                Terminal
              </Text>
              <Badge color={terminalConnected ? 'green' : 'gray'} variant="soft">
                {terminalConnected ? 'connected' : 'idle'}
              </Badge>
            </div>
            <pre className="terminal-preview">
              {terminalLines.length
                ? terminalLines.slice(-20).join('\n')
                : 'Start a sandbox terminal to stream output here.'}
            </pre>
          </div>
        ) : null}
      </div>
    </aside>
  );
}

function ReviewEmpty({
  icon,
  title,
  body,
}: {
  icon: ReactNode;
  title: string;
  body: string;
}) {
  return (
    <div className="review-empty">
      <span>{icon}</span>
      <strong>{title}</strong>
      <p>{body}</p>
    </div>
  );
}

function reviewTabToWorkflowTarget(tab: ReviewTab): WorkflowTarget {
  if (tab === 'pull') return 'pull';
  if (tab === 'plan') return 'plan';
  if (tab === 'background') return 'background';
  if (tab === 'artifacts') return 'artifacts';
  if (tab === 'terminal') return 'runtime';
  return 'changes';
}

function chatWorkflowTargetForReviewTab(tab: ReviewTab): ChatWorkflowTarget {
  if (tab === 'pull') return 'pull';
  if (tab === 'background') return 'background';
  if (tab === 'artifacts') return 'artifacts';
  if (tab === 'changes') return 'changes';
  return 'plan';
}

function signedOutTargetForSection(section: WorkbenchSection, tab: ReviewTab): WorkflowTarget {
  if (section === 'board') return 'changes';
  if (section === 'status') return 'background';
  if (section === 'memory') return 'runtime';
  return reviewTabToWorkflowTarget(tab);
}

function signedOutWorkflowContext(target: WorkflowTarget): { title: string; body: string } {
  if (target === 'plan') {
    return {
      title: 'Plan snapshot',
      body: 'Sign in to load the active plan, checkpoints, and open decisions.',
    };
  }
  if (target === 'pull') {
    return {
      title: 'Pull request',
      body: 'Connect a GitHub-backed workspace to show PR overview, checks, branch state, and review actions.',
    };
  }
  if (target === 'board') {
    return {
      title: 'Task board',
      body: 'Sign in to show workspace tasks as board lanes with status, progress, and priority.',
    };
  }
  if (target === 'background') {
    return {
      title: 'Background agents',
      body: 'Background work, queued checks, and progress updates appear here after connection.',
    };
  }
  if (target === 'artifacts') {
    return {
      title: 'Artifacts and events',
      body: 'Generated files, event updates, and background activity appear here after connection.',
    };
  }
  if (target === 'runtime') {
    return {
      title: 'Local workspace',
      body: 'Sign in or configure a connection to start the sandbox desktop and terminal.',
    };
  }
  return {
    title: 'Workspace changes',
    body: 'No repository diff is loaded yet. Sign in or configure a connection to sync this session.',
  };
}

function CommandPalette({
  inputRef,
  query,
  items,
  onQueryChange,
  onClose,
}: {
  inputRef: RefObject<HTMLInputElement | null>;
  query: string;
  items: CommandPaletteItem[];
  onQueryChange: (query: string) => void;
  onClose: (restoreFocus?: boolean) => void;
}) {
  const paletteRef = useRef<HTMLElement>(null);
  const enabledItems = useMemo(() => items.filter((item) => !item.disabled), [items]);
  const [activeItemId, setActiveItemId] = useState<string | null>(null);
  const activeItem = enabledItems.find((item) => item.id === activeItemId) ?? enabledItems[0];
  const activeOptionId = activeItem ? `command-option-${activeItem.id}` : undefined;

  useEffect(() => {
    setActiveItemId((current) => {
      if (current && enabledItems.some((item) => item.id === current)) {
        return current;
      }
      return enabledItems[0]?.id ?? null;
    });
  }, [enabledItems]);

  useEffect(() => {
    if (!activeOptionId) return;
    document.getElementById(activeOptionId)?.scrollIntoView({ block: 'nearest' });
  }, [activeOptionId]);

  useEffect(() => {
    const keepFocusInsidePalette = (event: FocusEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (paletteRef.current?.contains(target)) return;
      inputRef.current?.focus();
    };

    window.addEventListener('focusin', keepFocusInsidePalette);
    return () => window.removeEventListener('focusin', keepFocusInsidePalette);
  }, [inputRef]);

  const runItem = (item: CommandPaletteItem) => {
    if (item.disabled) return;
    item.onSelect();
    onClose(false);
  };

  const moveActiveItem = (delta: number) => {
    setActiveItemId((current) => {
      if (enabledItems.length === 0) return null;
      const currentIndex = enabledItems.findIndex((item) => item.id === current);
      const startIndex = currentIndex === -1 ? (delta > 0 ? -1 : 0) : currentIndex;
      const nextIndex = (startIndex + delta + enabledItems.length) % enabledItems.length;
      return enabledItems[nextIndex].id;
    });
  };

  const containTabFocus = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (event.defaultPrevented || event.key !== 'Tab') return;
    const focusableElements = getCommandPaletteFocusableElements(paletteRef.current);
    if (!focusableElements.length) return;
    const firstElement = focusableElements[0];
    const lastElement = focusableElements[focusableElements.length - 1];
    const activeElement = document.activeElement;

    if (event.shiftKey && activeElement === firstElement) {
      event.preventDefault();
      lastElement.focus();
      return;
    }
    if (!event.shiftKey && activeElement === lastElement) {
      event.preventDefault();
      firstElement.focus();
    }
  };

  return (
    <div className="command-palette-backdrop" onMouseDown={() => onClose(true)}>
      <section
        ref={paletteRef}
        className="command-palette"
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        onKeyDown={containTabFocus}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <label className="command-search">
          <MagnifyingGlassIcon />
          <input
            ref={inputRef}
            value={query}
            aria-label="Search commands"
            placeholder="Search commands, sessions, tools..."
            aria-activedescendant={activeOptionId}
            onChange={(event) => onQueryChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'ArrowDown') {
                event.preventDefault();
                moveActiveItem(1);
              }
              if (event.key === 'ArrowUp') {
                event.preventDefault();
                moveActiveItem(-1);
              }
              if (event.key === 'Home' && enabledItems[0]) {
                event.preventDefault();
                setActiveItemId(enabledItems[0].id);
              }
              if (event.key === 'End' && enabledItems[enabledItems.length - 1]) {
                event.preventDefault();
                setActiveItemId(enabledItems[enabledItems.length - 1].id);
              }
              if (event.key === 'Enter' && activeItem) {
                event.preventDefault();
                runItem(activeItem);
              }
              if (event.key === 'Escape') {
                event.preventDefault();
                onClose(true);
              }
            }}
          />
        </label>
        <div className="command-list" role="listbox" aria-label="Command results">
          {items.length === 0 ? (
            <div className="command-empty">No commands found.</div>
          ) : (
            items.map((item) => (
              <button
                id={`command-option-${item.id}`}
                className={`command-row ${item.disabled ? 'disabled' : ''} ${
                  item.id === activeItem?.id ? 'selected' : ''
                }`}
                type="button"
                role="option"
                aria-selected={item.id === activeItem?.id}
                key={item.id}
                disabled={item.disabled}
                onMouseEnter={() => {
                  if (!item.disabled) {
                    setActiveItemId(item.id);
                  }
                }}
                onClick={() => runItem(item)}
              >
                <span className="command-icon">{item.icon}</span>
                <span className="command-copy">
                  <strong>{item.label}</strong>
                  <em>{item.description}</em>
                </span>
              </button>
            ))
          )}
        </div>
      </section>
    </div>
  );
}

function getCommandPaletteFocusableElements(container: HTMLElement | null): HTMLElement[] {
  if (!container) return [];
  const selectors = [
    'button:not(:disabled)',
    'input:not(:disabled)',
    'textarea:not(:disabled)',
    'select:not(:disabled)',
    '[tabindex]:not([tabindex="-1"])',
  ].join(',');
  return Array.from(container.querySelectorAll<HTMLElement>(selectors)).filter(
    (element) => element.getAttribute('aria-hidden') !== 'true',
  );
}

function OverviewMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric overview-metric">
      <Text size="1" color="gray">
        {label}
      </Text>
      <Text size="2" weight="bold">
        {value}
      </Text>
    </div>
  );
}

function SettingMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric setting-metric">
      <Text size="1" color="gray">
        {label}
      </Text>
      <Text size="2" weight="bold">
        {value}
      </Text>
    </div>
  );
}
