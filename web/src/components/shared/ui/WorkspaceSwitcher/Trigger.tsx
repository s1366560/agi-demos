/**
 * WorkspaceSwitcherTrigger - Trigger button for the dropdown menu
 *
 * Handles click and keyboard interactions to open/close the menu.
 */

import { forwardRef, useEffect, type KeyboardEvent } from 'react';

import { useWorkspaceContext } from './WorkspaceContext';

import type { WorkspaceTriggerProps } from './types';

export const WorkspaceSwitcherTrigger = forwardRef<HTMLButtonElement, WorkspaceTriggerProps>(
  ({ className = '', children, ...props }, ref) => {
    const { isOpen, setIsOpen, triggerButtonRef, setFocusedIndex, getMenuItemRef, menuItemsCount } =
      useWorkspaceContext();

    // Combine refs
    const setRef = (element: HTMLButtonElement | null) => {
      if (element) {
        triggerButtonRef.current = element;
      }
      if (typeof ref === 'function') {
        ref(element);
      } else if (ref) {
        ref.current = element;
      }
    };

    // Focus first menu item when menu opens
    useEffect(() => {
      if (isOpen && menuItemsCount > 0) {
        setFocusedIndex(0);
        // Use setTimeout to ensure the DOM has been updated
        const timeoutId = setTimeout(() => {
          getMenuItemRef(0)?.focus();
        }, 0);
        return () => {
          clearTimeout(timeoutId);
        };
      }
      return undefined;
    }, [isOpen, menuItemsCount, setFocusedIndex, getMenuItemRef]);

    const handleClick = () => {
      setIsOpen(!isOpen);
    };

    const handleKeyDown = (e: KeyboardEvent<HTMLButtonElement>) => {
      switch (e.key) {
        case 'ArrowDown':
        case 'ArrowUp':
        case 'Enter':
        case ' ':
          e.preventDefault();
          setIsOpen(true);
          break;
        case 'Escape':
          e.preventDefault();
          setIsOpen(false);
          break;
      }
    };

    const baseClasses =
      'flex items-center gap-2 w-full p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors text-left focus:outline-none focus:ring-2 focus:ring-primary/50';

    return (
      <button
        ref={setRef}
        type="button"
        onClick={handleClick}
        onKeyDown={handleKeyDown}
        aria-expanded={isOpen}
        aria-haspopup="listbox"
        className={`${baseClasses} ${className}`}
        {...props}
      >
        {children}
      </button>
    );
  }
);

WorkspaceSwitcherTrigger.displayName = 'WorkspaceSwitcherTrigger';
