/**
 * SandboxPanelContext - Shared state for SandboxPanel compound components
 */

import { createContext, useContext, useState, useCallback, ReactNode } from "react";

import type { SandboxPanelContextValue, SandboxTabKey } from "./types";

const SandboxPanelContext = createContext<SandboxPanelContextValue | null>(null);

export interface SandboxProviderProps {
  sandboxId: string | null;
  defaultTab?: SandboxTabKey;
  toolExecutions: SandboxPanelContextValue["toolExecutions"];
  currentTool: SandboxPanelContextValue["currentTool"];
  desktopStatus: SandboxPanelContextValue["desktopStatus"];
  terminalStatus: SandboxPanelContextValue["terminalStatus"];
  onDesktopStart?: () => void;
  onDesktopStop?: () => void;
  onTerminalStart?: () => void;
  onTerminalStop?: () => void;
  isDesktopLoading: boolean;
  isTerminalLoading: boolean;
  onFileClick?: (filePath: string) => void;
  onClose?: () => void;
  children: ReactNode;
}

/**
 * Provider for SandboxPanel state
 */
export const SandboxPanelProvider: React.FC<SandboxProviderProps> = ({
  sandboxId,
  defaultTab = "terminal",
  toolExecutions,
  currentTool,
  desktopStatus,
  terminalStatus,
  onDesktopStart,
  onDesktopStop,
  onTerminalStart,
  onTerminalStop,
  isDesktopLoading = false,
  isTerminalLoading = false,
  onFileClick,
  onClose,
  children,
}) => {
  const [activeTab, setActiveTabState] = useState<SandboxTabKey>(defaultTab);

  const setActiveTab = useCallback((tab: SandboxTabKey) => {
    setActiveTabState(tab);
  }, []);

  const value: SandboxPanelContextValue = {
    sandboxId,
    activeTab,
    setActiveTab,
    toolExecutions,
    currentTool,
    desktopStatus,
    terminalStatus,
    onDesktopStart,
    onDesktopStop,
    onTerminalStart,
    onTerminalStop,
    isDesktopLoading,
    isTerminalLoading,
    onFileClick,
    onClose,
  };

  return <SandboxPanelContext.Provider value={value}>{children}</SandboxPanelContext.Provider>;
};

/**
 * Hook to access SandboxPanel context
 */
export const useSandboxPanelContext = (): SandboxPanelContextValue => {
  const context = useContext(SandboxPanelContext);
  if (!context) {
    throw new Error("SandboxPanel compound components must be used within SandboxPanel");
  }
  return context;
};
