/**
 * WorkspaceContext - Shared state for WorkspaceSwitcher compound components
 */

import { createContext, useContext, useRef, useState, useCallback } from 'react';

import type { WorkspaceContextValue, WorkspaceMode } from './types';

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export interface WorkspaceProviderProps {
  mode: WorkspaceMode;
  defaultOpen?: boolean | undefined;
  onOpenChange?: ((open: boolean) => void) | undefined;
  children: React.ReactNode;
}

/**
 * Provider for WorkspaceSwitcher state
 */

export const WorkspaceProvider: React.FC<WorkspaceProviderProps> = ({
  mode,
  defaultOpen = false,
  onOpenChange,
  children,
}) => {
  const [isOpen, setIsOpenState] = useState(defaultOpen);
  const [focusedIndex, setFocusedIndexState] = useState(-1);
  const [menuItemsCount, setMenuItemsCountState] = useState(0);

  const triggerButtonRef = useRef<HTMLButtonElement>(null);
  const menuItemRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const setIsOpen = useCallback(
    (open: boolean) => {
      setIsOpenState(open);
      onOpenChange?.(open);

      // Reset focused index when closing
      if (!open) {
        setFocusedIndexState(-1);
        menuItemRefs.current = [];
      }
    },
    [onOpenChange]
  );

  const setFocusedIndex = useCallback((index: number) => {
    setFocusedIndexState(index);
  }, []);

  const setMenuItemsCount = useCallback((count: number) => {
    setMenuItemsCountState(count);
  }, []);

  const registerMenuItemRef = useCallback((index: number, ref: HTMLButtonElement | null) => {
    menuItemRefs.current[index] = ref;
  }, []);

  const getMenuItemRef = useCallback((index: number): HTMLButtonElement | null => {
    return menuItemRefs.current[index] || null;
  }, []);

  const value: WorkspaceContextValue = {
    mode,
    isOpen,
    setIsOpen,
    focusedIndex,
    setFocusedIndex,
    menuItemsCount,
    setMenuItemsCount,
    registerMenuItemRef,
    getMenuItemRef,
    triggerButtonRef,
  };

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
};

/**
 * Hook to access WorkspaceSwitcher context
 */

// eslint-disable-next-line react-refresh/only-export-components
export const useWorkspaceContext = (): WorkspaceContextValue => {
  const context = useContext(WorkspaceContext);
  if (!context) {
    throw new Error(
      'WorkspaceSwitcher compound components must be used within WorkspaceSwitcherRoot'
    );
  }
  return context;
};
