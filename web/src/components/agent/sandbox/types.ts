/**
 * SandboxPanel Compound Component Types
 *
 * Defines the type system for the compound SandboxPanel component.
 */

import type { DesktopStatus, TerminalStatus } from '../../../types/agent';

// Re-export ToolExecution from SandboxOutputViewer
export type { ToolExecution } from './SandboxOutputViewer';

/**
 * Available tabs in the SandboxPanel
 */
export type SandboxTabKey = 'terminal' | 'desktop' | 'control' | 'output';

/**
 * Sandbox panel context shared across compound components
 */
export interface SandboxPanelContextValue {
  /** Active sandbox ID */
  sandboxId: string | null;
  /** Currently active tab */
  activeTab: SandboxTabKey;
  /** Change active tab */
  setActiveTab: (tab: SandboxTabKey) => void;
  /** Tool execution history */
  toolExecutions: SandboxPanelToolExecution[];
  /** Current tool being executed */
  currentTool: { name: string; input: Record<string, unknown> } | null;
  /** Desktop status information */
  desktopStatus: DesktopStatus | null;
  /** Terminal status information */
  terminalStatus: TerminalStatus | null;
  /** Project ID for constructing proxy URLs */
  projectId?: string | null;
  /** Callbacks for desktop/terminal control */
  onDesktopStart?: () => void;
  onDesktopStop?: () => void;
  onTerminalStart?: () => void;
  onTerminalStop?: () => void;
  /** Loading states */
  isDesktopLoading: boolean;
  isTerminalLoading: boolean;
  /** File click handler */
  onFileClick?: (filePath: string) => void;
  /** Close handler */
  onClose?: () => void;
}

/**
 * Tool execution record (alias for backward compatibility)
 */
export interface SandboxPanelToolExecution {
  id: string;
  toolName: string;
  input: Record<string, unknown>;
  output: string | unknown;
  timestamp: number;
  status?: 'pending' | 'running' | 'success' | 'error';
}

/**
 * Props for the root SandboxPanel component
 */
export interface SandboxPanelRootProps {
  /** Active sandbox ID */
  sandboxId: string | null;
  /** Default active tab (default: "terminal") */
  defaultTab?: SandboxTabKey;
  /** Tool execution history */
  toolExecutions?: SandboxPanelToolExecution[];
  /** Current tool being executed */
  currentTool?: { name: string; input: Record<string, unknown> } | null;
  /** Called when panel is closed */
  onClose?: () => void;
  /** Called when file is clicked in output */
  onFileClick?: (filePath: string) => void;
  /** Desktop status information */
  desktopStatus?: DesktopStatus | null;
  /** Terminal status information */
  terminalStatus?: TerminalStatus | null;
  /** Called when start desktop is requested */
  onDesktopStart?: () => void;
  /** Called when stop desktop is requested */
  onDesktopStop?: () => void;
  /** Called when start terminal is requested */
  onTerminalStart?: () => void;
  /** Called when stop terminal is requested */
  onTerminalStop?: () => void;
  /** Loading state for desktop operations */
  isDesktopLoading?: boolean;
  /** Loading state for terminal operations */
  isTerminalLoading?: boolean;
  /** Children for compound component pattern */
  children?: React.ReactNode;
}

/**
 * Props for Terminal sub-component
 */
export interface SandboxTerminalProps {
  /** Optional custom class name */
  className?: string;
}

/**
 * Props for Desktop sub-component
 */
export interface SandboxDesktopProps {
  /** Optional custom class name */
  className?: string;
}

/**
 * Props for Control sub-component
 */
export interface SandboxControlProps {
  /** Optional custom class name */
  className?: string;
}

/**
 * Props for Output sub-component
 */
export interface SandboxOutputProps {
  /** Optional custom class name */
  className?: string;
}

/**
 * Props for Header sub-component
 */
export interface SandboxHeaderProps {
  /** Optional custom class name */
  className?: string;
}

/**
 * Legacy SandboxPanelProps for backward compatibility
 * @deprecated Use SandboxPanelRootProps with compound components instead
 */
export interface LegacySandboxPanelProps {
  /** Active sandbox ID */
  sandboxId: string | null;
  /** Tool execution history */
  toolExecutions?: SandboxPanelToolExecution[];
  /** Current tool being executed */
  currentTool?: { name: string; input: Record<string, unknown> } | null;
  /** Called when panel is closed */
  onClose?: () => void;
  /** Called when file is clicked in output */
  onFileClick?: (filePath: string) => void;
  /** Default tab (default: "terminal") */
  defaultTab?: SandboxTabKey;
  /** Desktop status information */
  desktopStatus?: DesktopStatus | null;
  /** Terminal status information */
  terminalStatus?: TerminalStatus | null;
  /** Called when start desktop is requested */
  onDesktopStart?: () => void;
  /** Called when stop desktop is requested */
  onDesktopStop?: () => void;
  /** Called when start terminal is requested */
  onTerminalStart?: () => void;
  /** Called when stop terminal is requested */
  onTerminalStop?: () => void;
  /** Loading state for desktop operations */
  isDesktopLoading?: boolean;
  /** Loading state for terminal operations */
  isTerminalLoading?: boolean;
}
