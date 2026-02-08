/**
 * Sandbox Components - Interactive sandbox debugging tools
 *
 * Provides terminal access, remote desktop, and tool output viewing for sandbox containers.
 *
 * ## Usage
 *
 * ### Compound Components (Recommended)
 * ```tsx
 * <SandboxPanel sandboxId="abc">
 *   <SandboxPanel.Terminal />
 *   <SandboxPanel.Desktop />
 *   <SandboxPanel.Control />
 * </SandboxPanel>
 * ```
 *
 * ### Backward Compatible
 * ```tsx
 * <SandboxPanel sandboxId="abc" />
 * ```
 */

export { SandboxTerminal } from './SandboxTerminal';
export type { SandboxTerminalProps } from './SandboxTerminal';

export { SandboxOutputViewer } from './SandboxOutputViewer';
export type { SandboxOutputViewerProps, ToolExecution } from './SandboxOutputViewer';

export { SandboxPanel } from './SandboxPanel';
export type {
  SandboxPanelRootProps,
  SandboxTerminalProps as SandboxPanelTerminalProps,
  SandboxDesktopProps as SandboxPanelDesktopProps,
  SandboxControlProps as SandboxPanelControlProps,
  SandboxOutputProps as SandboxPanelOutputProps,
  SandboxHeaderProps as SandboxPanelHeaderProps,
  LegacySandboxPanelProps,
} from './types';

// Re-export types from SandboxPanel
export type { SandboxTabKey, SandboxPanelContextValue, SandboxPanelToolExecution } from './types';

export { RemoteDesktopViewer } from './RemoteDesktopViewer';
export type { RemoteDesktopViewerProps } from './RemoteDesktopViewer';

export { KasmVNCViewer } from './KasmVNCViewer';
export type { KasmVNCViewerProps } from './KasmVNCViewer';

export { SandboxControlPanel } from './SandboxControlPanel';
export type { SandboxControlPanelProps } from './SandboxControlPanel';

export { SandboxStatusIndicator } from './SandboxStatusIndicator';
