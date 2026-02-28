/**
 * WorkspaceSwitcherMenu - Dropdown menu container
 *
 * Renders the dropdown menu when open and handles click-outside to close.
 */

import { useEffect, useRef, type KeyboardEvent } from 'react';

import { useWorkspaceContext } from './WorkspaceContext';

import type { WorkspaceMenuProps } from './types';

export const WorkspaceSwitcherMenu: React.FC<WorkspaceMenuProps> = ({
  className = '',
  children,
  label,
}) => {
  const { isOpen, setIsOpen, triggerButtonRef } = useWorkspaceContext();
  const menuRef = useRef<HTMLDivElement>(null);

  // Close dropdown when clicking outside
  useEffect(() => {
    if (!isOpen) return;

    const handleClickOutside = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isOpen, setIsOpen]);

  // Handle keyboard navigation at menu level
  const handleKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    switch (e.key) {
      case 'Escape':
        e.preventDefault();
        setIsOpen(false);
        // Focus the trigger button after closing
        setTimeout(() => {
          triggerButtonRef.current?.focus();
        }, 0);
        break;
      case 'Tab':
        setIsOpen(false);
        break;
    }
  };

  if (!isOpen) return null;

  const baseClasses =
    'absolute top-full left-0 w-64 mt-2 bg-white dark:bg-[#1e2332] border border-slate-200 dark:border-slate-700 rounded-xl shadow-xl z-50 overflow-hidden animate-in fade-in zoom-in-95 duration-100';

  return (
    <div
      ref={menuRef}
      role="listbox"
      aria-orientation="vertical"
      aria-labelledby="workspace-switcher-label"
      onKeyDown={handleKeyDown}
      className={`${baseClasses} ${className}`}
    >
      <div className="p-2">
        <div
          id="workspace-switcher-label"
          className="px-3 py-2 text-xs font-semibold text-slate-400 uppercase tracking-wider"
        >
          {label}
        </div>
        {children}
      </div>
    </div>
  );
};
